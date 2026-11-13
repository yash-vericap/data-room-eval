"""Page rows and document entries in the stored shape."""
from __future__ import annotations

from pathlib import Path

from .config import _doc, _now, _sha


def _rows(room: str, rows: list[dict]) -> list[dict]:
    """Page rows in the stored shape. Rows for the same page are joined, as the local reader does."""
    merged: dict[tuple, dict] = {}
    for r in rows:
        doc, page = str(r.get("doc_id") or "").upper(), r.get("page")
        text = "\n" + str(r.get("text") or "")          # exactly what the local reader builds, so both give the same text
        if (doc, page) in merged:
            merged[(doc, page)]["text"] += text
        else:
            merged[(doc, page)] = {"data_room": room, "doc_id": doc, "page": page, "text": text,
                                   "method": r.get("method") or r.get("read_by") or "text"}
    at = _now()
    return [{**c, "sha256": _sha(c["text"]), "created_at": at} for c in merged.values()]


def _pdf_bytes(pdfs) -> dict[str, tuple[str, bytes]]:
    """{doc_id: (file name, bytes)} from {file name: bytes or path} or a list of paths."""
    items = pdfs.items() if isinstance(pdfs, dict) else [(Path(p).name, p) for p in pdfs or []]
    out = {}
    for name, data in items:
        doc = _doc(name)
        if doc:
            out[doc] = (Path(str(name)).name, data if isinstance(data, (bytes, bytearray)) else Path(data).read_bytes())
    return out


def _documents(room: str, chunks: list[dict], pdfs: dict[str, tuple[str, bytes]], names: dict[str, str]) -> list[dict]:
    at, out = _now(), []
    for doc in sorted({c["doc_id"] for c in chunks} | set(pdfs)):
        pages = sorted((c for c in chunks if c["doc_id"] == doc), key=lambda c: (c["page"] is None, c["page"]))
        name, data = pdfs.get(doc, (names.get(doc, ""), None))
        out.append({"data_room": room, "doc_id": doc, "file_name": name, "pages": len(pages),
                    "sha256": _sha(data) if data is not None else _sha("".join(c["sha256"] for c in pages)),
                    "size": len(data) if data is not None else sum(len(c["text"]) for c in pages),
                    "pdf_stored": data is not None, "created_at": at})
    return out
