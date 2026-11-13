"""The page text of a data room, from the document store or the local data_room/ folder.

Local text is cached by file and modification time, so a screen that reads a room on every click parses
its pages once."""
from __future__ import annotations

import json
import re

from . import store


_CHUNKS_PROBLEM: str | None = None


def chunks_problem() -> str | None:
    """Why page text could not be read from the document store on the last try, or None."""
    return _CHUNKS_PROBLEM


def load_chunks(data_room: str) -> dict[str, dict[int | None, str]]:
    """{doc_id: {page: text}} for one data room.

    With MONGO_URI set, the text comes from the document store (eval/doc_store.py). A room that is not
    in the store yet is read from the local folder. Without MONGO_URI everything is read locally. When
    the store cannot be reached the answer is empty, so quote checks show "Not checked" and the rest of
    the scoring still works; chunks_problem() says why."""
    global _CHUNKS_PROBLEM
    from . import doc_store
    if doc_store.enabled():
        try:
            out = doc_store.load_chunks(data_room)
            _CHUNKS_PROBLEM = None
            if out:
                return out
        except doc_store.StoreUnavailable as e:
            _CHUNKS_PROBLEM = str(e)
            return {}
    return load_local_chunks(data_room)


def load_local_chunks(data_room: str) -> dict[str, dict[int | None, str]]:
    """Reads data_room/<room>/chunks.json ([{doc_id, page, text}]) and any DOC-xx.txt files (pages
    separated by a form feed). Empty when no text is stored locally."""
    folder = store.DATA_ROOM / data_room
    path = folder / "chunks.json"
    stamp = (str(path), path.stat().st_mtime if path.exists() else None,
             tuple(sorted((t.name, t.stat().st_mtime) for t in folder.glob("DOC-*.txt"))) if folder.exists() else ())
    if _LOCAL.get(data_room, (None,))[0] != stamp:
        _LOCAL[data_room] = (stamp, _read_local(folder))
    return _LOCAL[data_room][1]


_LOCAL: dict[str, tuple] = {}


def _read_local(folder) -> dict[str, dict[int | None, str]]:
    out: dict[str, dict] = {}
    rows = json.loads((folder / "chunks.json").read_text(encoding="utf-8")) if (folder / "chunks.json").exists() else []
    for row in rows or []:
        doc = str(row.get("doc_id", "")).upper()
        page = row.get("page")
        out.setdefault(doc, {})
        out[doc][page] = out[doc].get(page, "") + "\n" + str(row.get("text", ""))
    for path in sorted(folder.glob("DOC-*.txt")) if folder.exists() else []:
        doc = re.match(r"(DOC-\d+)", path.stem.upper()).group(1)
        for i, text in enumerate(path.read_text(encoding="utf-8", errors="ignore").split("\f"), start=1):
            out.setdefault(doc, {})[i] = text
    return out
