"""Document and page text storage in MongoDB, so the data room does not live in the repository.

After the PDFs of a data room are read into page text, the text goes to MongoDB. The PDFs go there too
when asked (EVAL_STORE_PDFS=1, or --with-pdfs). Local copies are deleted only after everything written
has been read back and compared.

Settings, from the environment or .env:
  MONGO_URI         the connection string. When it is not set, page text is read from data_room/ as before.
  MONGO_DB          the database name (default dataroom_eval)
  EVAL_STORE_PDFS   1 to store the PDFs as well as the page text

A host that is not this machine or a private network must use TLS (mongodb+srv://, or tls=true), and
under the strict data policy it must be named in EVAL_ALLOWED_HOSTS.

Collections:
  chunks      data_room, doc_id, page, text, method (text | ocr | unreadable), sha256, created_at
              unique on (data_room, doc_id, page)
  documents   data_room, doc_id, file_name, pages, sha256, size, pdf_stored, created_at
  pdfs        a GridFS bucket, used when PDFs are stored

Two backends: MongoDB, and one in memory for the tests (use_memory())."""
from __future__ import annotations

from .backends import Memory, Mongo
from .config import StoreUnavailable, _sha, check_uri, db_name, hosts, store_pdfs, uri  # noqa: F401
from .rows import _documents, _pdf_bytes, _rows


_BACKEND = None            # the backend in use, opened once
_FORCED = None             # a backend set by use_memory(), which wins over the settings
_OPENED_FOR = None
_CACHE: dict[str, dict] = {}
generation = 0             # goes up on every write, so callers can drop what they cached


def use_memory() -> Memory:
    """Switches to a fresh in-memory backend. For the tests."""
    global _FORCED
    _FORCED = Memory()
    _CACHE.clear()
    return _FORCED


def use_settings() -> None:
    """Goes back to the backend the settings name."""
    global _FORCED, _BACKEND, _OPENED_FOR
    _FORCED = _BACKEND = _OPENED_FOR = None
    _CACHE.clear()


def enabled() -> bool:
    return _FORCED is not None or bool(uri())


def backend():
    global _BACKEND, _OPENED_FOR
    if _FORCED is not None:
        return _FORCED
    if not uri():
        raise StoreUnavailable("MONGO_URI is not set, so page text is read from the local data_room/ folder.")
    if _BACKEND is None or _OPENED_FOR != (uri(), db_name()):
        _BACKEND, _OPENED_FOR = Mongo(uri(), db_name()), (uri(), db_name())
        _CACHE.clear()
    return _BACKEND


def describe() -> str:
    if _FORCED is not None:
        return "memory"
    return f"MongoDB at {', '.join(hosts(uri()))}, database {db_name()}" if uri() else "local files (data_room/)"


def save_room(room: str, rows: list[dict], pdfs=None, file_names: dict[str, str] | None = None) -> dict:
    """Writes one data room, replacing what was stored for it. rows: [{doc_id, page, text, method}].
    pdfs: {file name: bytes or path} or a list of paths, when the PDFs are to be stored as well."""
    global generation
    chunks, files = _rows(room, rows), _pdf_bytes(pdfs)
    documents = _documents(room, chunks, files, file_names or {})
    backend().replace_room(room, chunks, documents, {doc: data for doc, (_, data) in files.items()})
    generation += 1
    _CACHE.pop(room, None)
    return {"room": room, "documents": len(documents), "pages": len(chunks), "pdfs": len(files)}


def verify_room(room: str, rows: list[dict], pdfs=None) -> dict:
    """Reads the room back and compares it with what should be there: the pages of every document, the
    hash of every page, and the hash of every PDF. Returns {"ok", "problems"}."""
    want, files, problems = _rows(room, rows), _pdf_bytes(pdfs), []
    try:
        b = backend()
        have = {(c["doc_id"], c["page"]): c for c in b.room_chunks(room)}
        docs = {d["doc_id"]: d for d in b.room_documents(room)}
    except StoreUnavailable as e:
        return {"ok": False, "problems": [str(e)]}
    if len(have) != len(want):
        problems.append(f"{room}: {len(have)} pages stored, {len(want)} expected.")
    for c in want:
        got = have.get((c["doc_id"], c["page"]))
        if got is None:
            problems.append(f"{room} {c['doc_id']} p.{c['page']}: missing.")
        elif got.get("sha256") != c["sha256"] or _sha(got.get("text") or "") != c["sha256"]:
            problems.append(f"{room} {c['doc_id']} p.{c['page']}: the stored text differs.")
    for doc in sorted({c["doc_id"] for c in want}):
        n = sum(c["doc_id"] == doc for c in want)
        if (docs.get(doc) or {}).get("pages") != n:
            problems.append(f"{room} {doc}: the document entry says {(docs.get(doc) or {}).get('pages')} pages, {n} expected.")
    for doc, (_, data) in files.items():
        stored = b.pdf(room, doc)
        if stored is None:
            problems.append(f"{room} {doc}: the PDF is missing.")
        elif _sha(stored) != _sha(data):
            problems.append(f"{room} {doc}: the stored PDF differs.")
    return {"ok": not problems, "problems": problems[:20]}


def load_chunks(room: str) -> dict[str, dict]:
    """{doc_id: {page: text}}, the same shape the local reader gives. Cached per room until it is written."""
    if room not in _CACHE:
        out: dict[str, dict] = {}
        for c in backend().room_chunks(room):
            out.setdefault(c["doc_id"], {})[c["page"]] = c["text"]
        _CACHE[room] = out
    return _CACHE[room]


def delete_room(room: str) -> None:
    global generation
    backend().delete_room(room)
    generation += 1
    _CACHE.pop(room, None)


def list_rooms() -> list[dict]:
    """[{"room", "documents", "pages", "pdfs"}] for every data room in the store."""
    b = backend()
    out = []
    for room in b.rooms():
        docs = b.room_documents(room)
        out.append({"room": room, "documents": len(docs), "pages": sum(d.get("pages") or 0 for d in docs),
                    "pdfs": sum(bool(d.get("pdf_stored")) for d in docs)})
    return out


def get_pdf(room: str, doc_id: str) -> bytes | None:
    return backend().pdf(room, doc_id.upper())
