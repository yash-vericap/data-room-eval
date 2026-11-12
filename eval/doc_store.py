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

Two backends: MongoDB, and one in memory for the tests (use_memory()).
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import providers


class StoreUnavailable(RuntimeError):
    """The document store cannot be used: wrong settings, a refused host, or MongoDB cannot be reached."""


def _sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _doc(name: str) -> str | None:
    m = re.match(r"(DOC-\d+)", Path(str(name)).name, re.I)
    return m.group(1).upper() if m else None


# ---- settings and the host check ------------------------------------------------------------------------

def uri() -> str:
    return (os.environ.get("MONGO_URI") or "").strip()


def db_name() -> str:
    return (os.environ.get("MONGO_DB") or "dataroom_eval").strip()


def store_pdfs() -> bool:
    return (os.environ.get("EVAL_STORE_PDFS") or "").strip() == "1"


def hosts(mongo_uri: str) -> list[str]:
    """The host names in a MongoDB connection string, without credentials or ports."""
    rest = re.sub(r"^mongodb(\+srv)?://", "", mongo_uri)
    rest = rest.rsplit("@", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return [h.strip().lower().rsplit(":", 1)[0].strip("[]") if not h.strip().startswith("[") else
            h.strip().lower().split("]")[0].strip("[") for h in rest.split(",") if h.strip()]


def check_uri(mongo_uri: str) -> None:
    """Refuses a connection string that would send page text over an open line or to a host that is not
    allowed. A local host needs neither TLS nor a place on the allowed list."""
    if not re.match(r"^mongodb(\+srv)?://", mongo_uri):
        raise StoreUnavailable("MONGO_URI must start with mongodb:// or mongodb+srv://.")
    names = hosts(mongo_uri)
    if not names:
        raise StoreUnavailable("MONGO_URI names no host.")
    remote = [h for h in names if not providers.is_local_host(h)]
    if not remote:
        return
    if not (mongo_uri.startswith("mongodb+srv://") or re.search(r"[?&](tls|ssl)=true", mongo_uri, re.I)):
        raise StoreUnavailable(f"MongoDB at {', '.join(remote)} is not on this machine, so TLS is required. "
                               f"Use a mongodb+srv:// address or add tls=true to MONGO_URI.")
    if providers.data_policy() == "strict":
        allowed = providers._names("EVAL_ALLOWED_HOSTS")
        bad = [h for h in remote if not any(h == a or h.endswith("." + a) for a in allowed)]
        if bad:
            raise StoreUnavailable(f"The data policy is strict and MongoDB host {', '.join(bad)} is not in "
                                   f"EVAL_ALLOWED_HOSTS. Add it there (next to the model's host) to allow it on purpose.")


# ---- backends ---------------------------------------------------------------------------------------------

class Memory:
    """Holds everything in dictionaries. For the tests."""
    name = "memory"

    def __init__(self):
        self.chunks: dict[tuple, dict] = {}
        self.documents: dict[tuple, dict] = {}
        self.pdfs: dict[tuple, bytes] = {}

    def replace_room(self, room: str, chunks: list[dict], documents: list[dict], pdfs: dict[str, bytes]) -> None:
        self.delete_room(room)
        self.chunks.update({(room, c["doc_id"], c["page"]): dict(c) for c in chunks})
        self.documents.update({(room, d["doc_id"]): dict(d) for d in documents})
        self.pdfs.update({(room, doc): data for doc, data in pdfs.items()})

    def room_chunks(self, room: str) -> list[dict]:
        return [dict(c) for (r, _, _), c in self.chunks.items() if r == room]

    def room_documents(self, room: str) -> list[dict]:
        return [dict(d) for (r, _), d in self.documents.items() if r == room]

    def pdf(self, room: str, doc_id: str) -> bytes | None:
        return self.pdfs.get((room, doc_id))

    def delete_room(self, room: str) -> None:
        for bucket in (self.chunks, self.documents, self.pdfs):
            for key in [k for k in bucket if k[0] == room]:
                del bucket[key]

    def rooms(self) -> list[str]:
        return sorted({k[0] for k in self.chunks} | {k[0] for k in self.documents})


class Mongo:
    name = "mongodb"

    def __init__(self, mongo_uri: str, database: str):
        check_uri(mongo_uri)
        try:
            import gridfs
            import pymongo
        except ImportError as e:
            raise StoreUnavailable("The 'pymongo' package is not installed. Run: pip install -r requirements.txt") from e
        self._errors = pymongo.errors.PyMongoError
        try:
            self.client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=6000, appname="dataroom-eval")
            self.db = self.client[database]
            self.db.chunks.create_index([("data_room", 1), ("doc_id", 1), ("page", 1)], unique=True)
            self.db.documents.create_index([("data_room", 1), ("doc_id", 1)], unique=True)
            self.fs = gridfs.GridFSBucket(self.db, bucket_name="pdfs")
        except self._errors as e:
            raise StoreUnavailable(f"MongoDB cannot be reached at {', '.join(hosts(mongo_uri))}: {str(e)[:200]}") from e

    def _guard(self, fn):
        try:
            return fn()
        except self._errors as e:
            raise StoreUnavailable(f"MongoDB did not answer: {str(e)[:200]}") from e

    def replace_room(self, room: str, chunks: list[dict], documents: list[dict], pdfs: dict[str, bytes]) -> None:
        def write():
            self.delete_room(room)
            if chunks:
                self.db.chunks.insert_many([dict(c) for c in chunks])
            if documents:
                self.db.documents.insert_many([dict(d) for d in documents])
            for doc, data in pdfs.items():
                self.fs.upload_from_stream(f"{room}/{doc}.pdf", data, metadata={"data_room": room, "doc_id": doc})
        self._guard(write)

    def room_chunks(self, room: str) -> list[dict]:
        return self._guard(lambda: list(self.db.chunks.find({"data_room": room}, {"_id": 0})))

    def room_documents(self, room: str) -> list[dict]:
        return self._guard(lambda: list(self.db.documents.find({"data_room": room}, {"_id": 0})))

    def pdf(self, room: str, doc_id: str) -> bytes | None:
        def read():
            f = self.db["pdfs.files"].find_one({"metadata.data_room": room, "metadata.doc_id": doc_id})
            return self.fs.open_download_stream(f["_id"]).read() if f else None
        return self._guard(read)

    def delete_room(self, room: str) -> None:
        def drop():
            self.db.chunks.delete_many({"data_room": room})
            self.db.documents.delete_many({"data_room": room})
            for f in list(self.db["pdfs.files"].find({"metadata.data_room": room}, {"_id": 1})):
                self.fs.delete(f["_id"])
        self._guard(drop)

    def rooms(self) -> list[str]:
        return self._guard(lambda: sorted(set(self.db.chunks.distinct("data_room")) | set(self.db.documents.distinct("data_room"))))


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


# ---- the public functions -----------------------------------------------------------------------------------

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
