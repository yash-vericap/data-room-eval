"""Adds the documents of a data room to the tool, so quotes can be checked against the real text.

    python -m eval add-data-room path/to/HTC03_Some_Project.zip
    python -m eval add-data-room path/to/folder --room HTC03

Each PDF must start with its document ID (DOC-01_..., DOC-02_...). Every page is read once:
pages with a text layer through pdftotext, scanned pages through OCR (tesseract). The result is
stored as data_room/<room>/chunks.json, one entry per page: {doc_id, page, text, read_by}.
The PDFs are copied to data_room/<room>/documents/.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import scoring, store

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


def add(source: str | Path, room: str | None = None, verbose: bool = True) -> dict:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
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
        dest = store.DATA_ROOM / room
        (dest / "documents").mkdir(parents=True, exist_ok=True)
        chunks, summary = [], []
        for pdf in pdfs:
            doc = re.match(r"(DOC-\d+)", pdf.name, re.I).group(1).upper()
            pages = read_pdf(pdf)
            chunks += [{"doc_id": doc, **p} for p in pages]
            shutil.copy2(pdf, dest / "documents" / pdf.name)
            row = {"doc_id": doc, "file": pdf.name, "pages": len(pages),
                   "ocr": sum(p["read_by"] == "ocr" for p in pages),
                   "unreadable": [p["page"] for p in pages if p["read_by"] == "unreadable"]}
            summary.append(row)
            if verbose:
                print(f"{room} {doc}: {row['pages']} pages, {row['ocr']} by OCR"
                      + (f", unreadable: {row['unreadable']}" if row["unreadable"] else ""))
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
    return {"room": room, "documents": summary, "answer_key": key}


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
