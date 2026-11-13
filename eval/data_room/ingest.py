"""Reads the PDFs of a data room and stores their page text, in the document store or locally."""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .. import doc_store, store
from .quotes import check_answer_key
from .reading import read_pdf
def _stored_rows(room: str) -> list[dict]:
    """The page rows already stored for a room, locally or in the document store."""
    rows = store._read(store.DATA_ROOM / room / "chunks.json", []) or []
    if not rows and doc_store.enabled():
        try:
            rows = [{"doc_id": c["doc_id"], "page": c["page"], "text": c["text"].lstrip("\n"), "read_by": c.get("method") or "text"}
                    for c in doc_store.backend().room_chunks(room)]
        except doc_store.StoreUnavailable:
            rows = []
    return rows


def add(source: str | Path, room: str | None = None, verbose: bool = True, keep_local: bool = False,
        replace: bool = True) -> dict:
    """Reads the PDFs and stores their page text. replace=False keeps the documents already stored for the
    room and adds the new ones to them (a document with the same ID is replaced)."""
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

        if not replace:
            fresh = {c["doc_id"] for c in chunks}
            chunks = [r for r in _stored_rows(room) if r.get("doc_id") not in fresh] + chunks
        stored, problems = "local files", []
        if doc_store.enabled():
            keep_pdfs = pdfs if doc_store.store_pdfs() and replace else None
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
            if replace and (dest / "documents").exists():
                shutil.rmtree(dest / "documents")
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
