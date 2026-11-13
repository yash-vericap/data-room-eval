"""Two backends: MongoDB, and one in memory for the tests."""
from __future__ import annotations

from .config import StoreUnavailable, check_uri, hosts


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
