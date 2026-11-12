"""Adds the documents of a data room to the tool, so quotes can be checked against the real text.

    python -m eval add-data-room path/to/HTC03_Some_Project.zip
    python -m eval add-data-room path/to/folder --room HTC03

Each PDF must start with its document ID (DOC-01_..., DOC-02_...). Every page is read once:
pages with a text layer through pdftotext, scanned pages through OCR (tesseract).

Where the result goes:
- With MONGO_URI set, the page text is written to MongoDB (eval/doc_store.py), and the PDFs too when
  EVAL_STORE_PDFS=1. Everything is read back and compared. Only when that passes are no local copies
  kept (--keep-local keeps them). When it fails, the local copies are written and the failure is reported.
- Without MONGO_URI, the result is stored as data_room/<room>/chunks.json, one entry per page:
  {doc_id, page, text, read_by}, and the PDFs are copied to data_room/<room>/documents/.

    python -m eval move-to-mongo [--rooms HTC01 HTC02] [--with-pdfs]

moves rooms that are already in data_room/ to MongoDB the same way, and deletes each local folder after
its copy is verified.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import doc_store, scoring, store

MIN_TEXT = 40          # a page with fewer characters than this is treated as a scan


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def _page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def read_pdf(pdf: Path) -> list[dict]:
    """[{page, text, read_by}] for one PDF. read_by is 'text', 'ocr' or 'unreadable'."""
    have_pdftotext, have_ocr = shutil.which("pdftotext"), shutil.which("tesseract") and shutil.which("pdftoppm")
    n = _page_count(pdf)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, n + 1):
            text = ""
            if have_pdftotext:
                text = _run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"])
            else:
                from pypdf import PdfReader
                text = PdfReader(str(pdf)).pages[page - 1].extract_text() or ""
            read_by = "text"
            if len(text.strip()) < MIN_TEXT:
                read_by = "unreadable"
                if have_ocr:
                    stem = Path(tmp) / f"p{page}"
                    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(page), "-l", str(page),
                                    "-singlefile", str(pdf), str(stem)], capture_output=True, check=False)
                    ocr = _run(["tesseract", f"{stem}.png", "-", "--psm", "6"])
                    if len(ocr.strip()) >= MIN_TEXT:
                        text, read_by = ocr, "ocr"
            out.append({"page": page, "text": text.replace("\f", "").strip(), "read_by": read_by})
    return out


def add(source: str | Path, room: str | None = None, verbose: bool = True, keep_local: bool = False) -> dict:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    say = print if verbose else (lambda *a: None)
    with tempfile.TemporaryDirectory() as tmp:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as z:
                for name in z.namelist():
                    target = (Path(tmp) / name).resolve()
                    if not str(target).startswith(str(Path(tmp).resolve())):
                        raise ValueError(f"Unsafe path in zip: {name}")
                z.extractall(tmp)
            folder = Path(tmp)
        else:
            folder = source
        pdfs = sorted(p for p in folder.rglob("*.pdf") if re.match(r"DOC-\d+", p.name, re.I))
        if not pdfs:
            raise ValueError("No PDF named DOC-<number>_... was found.")
        if room is None:
            m = re.search(r"([A-Z]{2,5}\d{2,3})", pdfs[0].parent.name + " " + source.name)
            if not m:
                raise ValueError("Could not tell the data room ID from the folder name. Pass --room, for example --room HTC03.")
            room = m.group(1)
        room = room.upper()
        chunks, summary = [], []
        for pdf in pdfs:
            doc = re.match(r"(DOC-\d+)", pdf.name, re.I).group(1).upper()
            pages = read_pdf(pdf)
            chunks += [{"doc_id": doc, **p} for p in pages]
            row = {"doc_id": doc, "file": pdf.name, "pages": len(pages),
                   "ocr": sum(p["read_by"] == "ocr" for p in pages),
                   "unreadable": [p["page"] for p in pages if p["read_by"] == "unreadable"]}
            summary.append(row)
            say(f"{room} {doc}: {row['pages']} pages, {row['ocr']} by OCR"
                + (f", unreadable: {row['unreadable']}" if row["unreadable"] else ""))

        stored, problems = "local files", []
        if doc_store.enabled():
            keep_pdfs = pdfs if doc_store.store_pdfs() else None
            try:
                doc_store.save_room(room, chunks, keep_pdfs, {r["doc_id"]: r["file"] for r in summary})
                check = doc_store.verify_room(room, chunks, keep_pdfs)
                problems = check["problems"]
            except doc_store.StoreUnavailable as e:
                problems = [str(e)]
            if problems:
                say("The copy in the document store could not be verified, so the local copies are kept:")
                for p in problems:
                    say(f"  {p}")
            else:
                stored = doc_store.describe()
                say(f"Stored and verified in {stored}" + (" with the PDFs." if keep_pdfs else ". The PDFs were not stored (EVAL_STORE_PDFS=1 stores them)."))
        if stored == "local files" or keep_local:
            dest = store.DATA_ROOM / room
            (dest / "documents").mkdir(parents=True, exist_ok=True)
            for pdf in pdfs:
                shutil.copy2(pdf, dest / "documents" / pdf.name)
            store._write(dest / "chunks.json", chunks)
    key = check_answer_key(room)
    if verbose:
        if not shutil.which("tesseract"):
            print("Note: tesseract is not installed, so scanned pages could not be read.")
        if key["cases"]:
            print(f"Answer key for {room}: {key['real']} of {key['checked']} quoted passages found in the documents.")
            for r in key["not_found"]:
                print(f"  not found: {r['case_id']}  {r['citation'][:110]}")
        else:
            print(f"No answer-key case exists for {room} yet. Add its cases to the sheet and run import-sheet.")
    return {"room": room, "documents": summary, "answer_key": key, "stored": stored, "problems": problems}


def local_rooms() -> list[str]:
    """Data rooms that still have a folder with page text under data_room/."""
    if not store.DATA_ROOM.exists():
        return []
    return sorted(p.name for p in store.DATA_ROOM.iterdir() if p.is_dir() and (p / "chunks.json").exists())


def move_to_mongo(rooms: list[str] | None = None, with_pdfs: bool = False, keep_local: bool = False,
                  verbose: bool = True) -> list[dict]:
    """Writes each local room's page text (and PDFs, when asked) to the document store, reads it back,
    and deletes the local folder only when the copy is verified. Returns one row per room:
    {"room", "pages", "documents", "pdfs", "verified", "local_deleted", "problems"}."""
    if not doc_store.enabled():
        raise doc_store.StoreUnavailable("MONGO_URI is not set. Put the connection string in .env first.")
    say = print if verbose else (lambda *a: None)
    out = []
    for room in rooms or local_rooms():
        room = room.upper()
        folder = store.DATA_ROOM / room
        rows = store._read(folder / "chunks.json", []) or []
        if not rows:
            out.append({"room": room, "pages": 0, "documents": 0, "pdfs": 0, "verified": False, "local_deleted": False,
                        "problems": [f"No page text found in {folder}."]})
            say(f"{room}: no page text found in {folder}.")
            continue
        pdfs = sorted((folder / "documents").glob("*.pdf")) if with_pdfs and (folder / "documents").exists() else None
        names = {m.group(1).upper(): p.name for p in sorted((folder / "documents").glob("*.pdf"))
                 if (m := re.match(r"(DOC-\d+)", p.name, re.I))} if (folder / "documents").exists() else {}
        try:
            saved = doc_store.save_room(room, rows, pdfs, names)
            check = doc_store.verify_room(room, rows, pdfs)
        except doc_store.StoreUnavailable as e:
            saved, check = {"pages": 0, "documents": 0, "pdfs": 0}, {"ok": False, "problems": [str(e)]}
        deleted = False
        if check["ok"] and not keep_local:
            shutil.rmtree(folder)
            deleted = True
        out.append({"room": room, "pages": saved["pages"], "documents": saved["documents"], "pdfs": saved["pdfs"],
                    "verified": check["ok"], "local_deleted": deleted, "problems": check["problems"]})
        if check["ok"]:
            say(f"{room}: {saved['pages']} pages of {saved['documents']} documents" + (f" and {saved['pdfs']} PDFs" if saved["pdfs"] else "")
                + " stored and verified. " + ("The local folder was deleted." if deleted else "The local folder was kept."))
        else:
            say(f"{room}: not verified, so the local folder was kept.")
            for p in check["problems"]:
                say(f"  {p}")
    return out


def check_answer_key(room: str) -> dict:
    """Checks every quote in the answer key against the stored document text. A quote that is not
    found is either an OCR miss or a slip in the answer key, and is worth a look either way."""
    chunks = store.load_chunks(room)
    try:
        cases = [c for c in store.load_cases() if c["data_room"] == room]
    except FileNotFoundError:
        cases = []
    checked = real = 0
    problems = []
    for c in cases:
        for cit in c["citations"]:
            pages = chunks.get(cit["doc_id"] or "")
            if not pages or not cit["quote"] or cit["quote"].startswith("["):
                continue
            res = scoring.quote_is_real(cit["quote"], pages, cit["page"])
            if res == "Not checked":
                continue
            checked += 1
            if res == "Real":
                real += 1
            else:
                problems.append({"case_id": c["case_id"], "citation": cit["raw"], "result": res})
    return {"cases": len(cases), "checked": checked, "real": real,
            "not_found": [p for p in problems if p["result"] == "Not found"],
            "wrong_page": [p for p in problems if p["result"] == "Wrong page"]}
