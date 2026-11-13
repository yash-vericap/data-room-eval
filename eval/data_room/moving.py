"""Moves rooms that are already in data_room/ to the document store, deleting each folder once verified."""
from __future__ import annotations

import re
import shutil

from .. import doc_store, store


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
