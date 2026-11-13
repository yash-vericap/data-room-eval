"""Adds a data room from uploaded files, numbering PDFs that have no document ID, and lists its documents."""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
from pathlib import Path

from .. import store
from .ingest import _stored_rows, add


ROOM_NAME = re.compile(r"[A-Z][A-Z0-9]{1,11}")




def register_documents(room: str, summary: list[dict], origin: str = "") -> list[str]:
    """Adds documents that are not in the document list yet, so a new data room can be used at once.
    The sheet's Documents tab stays the place to give them a type, date and authority."""
    path = store.ANSWER_KEY / "documents.json"
    docs = store._read(path, []) or []
    known = {(d["data_room"], d["doc_id"]) for d in docs}
    new = []
    for row in summary:
        if (room, row["doc_id"]) in known:
            continue
        title = re.sub(r"^DOC-\d+[_\- ]*", "", Path(row["file"]).stem, flags=re.I).replace("_", " ").strip()
        docs.append({"data_room": room, "doc_id": row["doc_id"], "title": title or row["doc_id"], "type": "", "role": "",
                     "status": "", "format": "Scanned" if row["ocr"] or row["unreadable"] else "Text", "pages": row["pages"],
                     "doc_date": "", "authority": ""})
        new.append(row["doc_id"])
    if new:
        store._write(path, docs)
        from .. import library
        library.log_many([{"action": "upload", "object": "document", "id": f"{room} {d}", "after": "Added with the data room.",
                           "reason": "Read from an uploaded data room.", "origin": origin} for d in new])
    return new


def add_files(room: str, files: dict[str, bytes], replace: bool = False, verbose: bool = False) -> dict:
    """Adds a data room from uploaded files: PDFs, or one zip of PDFs. A PDF whose name does not start
    with DOC-<number> is given the next free number, in name order. Returns what add() returns, plus
    "renamed" ({uploaded name: stored name}) and "registered" (document IDs new to the document list)."""
    room = (room or "").strip().upper()
    if not ROOM_NAME.fullmatch(room):
        raise ValueError("Give the data room a short name of capital letters and digits that starts with a letter, for example HTC03.")
    if not files:
        raise ValueError("Choose the PDFs of the data room, or one zip that holds them.")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / room
        folder.mkdir()
        for name, data in files.items():
            if name.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for member in z.namelist():
                        if member.lower().endswith(".pdf") and not Path(member).name.startswith((".", "__")):
                            (folder / Path(member).name).write_bytes(z.read(member))
            elif name.lower().endswith(".pdf"):
                (folder / Path(name).name).write_bytes(data)
        pdfs = sorted(folder.glob("*.pdf"))
        if not pdfs:
            raise ValueError("No PDF was found in the upload.")
        taken = {int(m.group(1)) for p in pdfs if (m := re.match(r"DOC-(\d+)", p.name, re.I))}
        if not replace:
            taken |= {int(r["doc_id"].split("-")[1]) for r in _stored_rows(room) if re.fullmatch(r"DOC-\d+", str(r.get("doc_id")))}
        renamed, n = {}, 0
        for pdf in pdfs:
            if re.match(r"DOC-\d+", pdf.name, re.I):
                continue
            n += 1
            while n in taken:
                n += 1
            taken.add(n)
            target = pdf.with_name(f"DOC-{n:02d}_{pdf.name}")
            pdf.rename(target)
            renamed[pdf.name] = target.name
        out = add(folder, room, verbose=verbose, replace=replace)
    out["renamed"] = renamed
    out["registered"] = register_documents(room, out["documents"], origin="data room upload")
    return out
