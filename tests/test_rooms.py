"""Data rooms: adding one from uploaded files, and keeping page text in the document store."""
import os

import pytest

from eval import data_room, doc_store, library, scoring, store

from fakes import ROWS, _local_room, _pdf
from helpers import CASES, F_CREDIT, run


MONGO_URI_TEST = os.environ.get("MONGO_URI_TEST")       # read here: the fixtures clear every MONGO_ setting


def test_adding_a_data_room_from_uploaded_files(empty):
    assert store.data_rooms() == []
    out = data_room.add_files("t7", {"Permit.pdf": _pdf(2), "DOC-03_Budget.pdf": _pdf()})
    assert out["room"] == "T7" and out["renamed"] == {"Permit.pdf": "DOC-01_Permit.pdf"}
    assert sorted(d["doc_id"] for d in out["documents"]) == ["DOC-01", "DOC-03"] and out["registered"] == ["DOC-01", "DOC-03"]
    assert store.data_rooms() == ["T7"] and set(store.load_chunks("T7")) == {"DOC-01", "DOC-03"}
    assert store.load_documents()[("T7", "DOC-01")]["title"] == "Permit" and library.load_changelog()[-1]["object"] == "document"
    more = data_room.add_files("T7", {"Lease.pdf": _pdf()})                   # added to what is stored
    assert more["renamed"] == {"Lease.pdf": "DOC-02_Lease.pdf"} and set(store.load_chunks("T7")) == {"DOC-01", "DOC-02", "DOC-03"}
    data_room.add_files("T7", {"DOC-01_New.pdf": _pdf()}, replace=True)       # replaces everything stored
    assert set(store.load_chunks("T7")) == {"DOC-01"}
    for bad, files in (("7T", {"a.pdf": _pdf()}), ("T8", {}), ("T8", {"notes.txt": b"x"})):
        with pytest.raises(ValueError):
            data_room.add_files(bad, files)


def test_document_store_holds_a_room_and_the_local_copy_goes(empty):
    folder = _local_room(store.DATA_ROOM)
    from_files = store.load_chunks("T9")
    mem = doc_store.use_memory()
    out = data_room.move_to_mongo(with_pdfs=True, verbose=False)
    assert [(r["room"], r["pages"], r["documents"], r["pdfs"], r["verified"], r["local_deleted"]) for r in out] == [("T9", 3, 2, 2, True, True)]
    assert not folder.exists() and store.load_chunks("T9") == from_files           # the same shape from the store as from the files
    assert doc_store.list_rooms() == [{"room": "T9", "documents": 2, "pages": 3, "pdfs": 2}]
    assert doc_store.get_pdf("T9", "doc-02") == b"%PDF-1.4 DOC-02_Budget.pdf"
    stored = next(c for c in mem.room_chunks("T9") if (c["doc_id"], c["page"]) == ("DOC-01", 1))
    assert stored["method"] == "ocr" and len(stored["sha256"]) == 64 and stored["created_at"]
    assert scoring.quote_is_real("QRE of $24,600,000", store.load_chunks("T9")["DOC-02"], 1) == "Real"
    doc_store.delete_room("T9")
    assert doc_store.list_rooms() == [] and store.load_chunks("T9") == {}


def test_failed_verification_keeps_the_local_files(empty, monkeypatch):
    folder = _local_room(store.DATA_ROOM)
    mem = doc_store.use_memory()
    real_replace = mem.replace_room
    monkeypatch.setattr(mem, "replace_room", lambda room, chunks, docs, pdfs: real_replace(room, chunks[:-1], docs, pdfs))
    out = data_room.move_to_mongo(verbose=False)
    assert out[0]["verified"] is False and out[0]["local_deleted"] is False and folder.exists()
    assert any("missing" in p or "expected" in p for p in out[0]["problems"])
    doc_store.use_settings()
    with pytest.raises(doc_store.StoreUnavailable, match="MONGO_URI is not set"):
        data_room.move_to_mongo(verbose=False)


def test_store_that_cannot_be_reached_leaves_scoring_working(empty, monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://db.example.com:27017/")          # not local, and no TLS
    assert store.load_chunks("T1") == {} and "TLS is required" in store.chunks_problem()
    res = scoring.score_run(run([F_CREDIT]), CASES, reviews={})
    assert res["metrics"]["found"] == 1 and res["rows"][0]["real"] == ["Not checked", "Not checked"]
    monkeypatch.setenv("MONGO_URI", "mongodb+srv://u:p@cluster0.example.mongodb.net/")
    with pytest.raises(doc_store.StoreUnavailable, match="EVAL_ALLOWED_HOSTS"):
        doc_store.check_uri(doc_store.uri())
    monkeypatch.setenv("EVAL_ALLOWED_HOSTS", "generativelanguage.googleapis.com, example.mongodb.net")
    doc_store.check_uri(doc_store.uri())
    doc_store.check_uri("mongodb://admin:secret@localhost:27017/?authSource=admin")


@pytest.mark.skipif(not MONGO_URI_TEST, reason="set MONGO_URI_TEST to run against a real MongoDB")
def test_document_store_against_a_real_mongodb(empty, monkeypatch):
    monkeypatch.setenv("MONGO_URI", MONGO_URI_TEST)
    monkeypatch.setenv("MONGO_DB", "dataroom_eval_test")
    doc_store.use_settings()
    try:
        doc_store.save_room("T9", ROWS, {"DOC-01_Part1.pdf": b"%PDF one"})
        assert doc_store.verify_room("T9", ROWS, {"DOC-01_Part1.pdf": b"%PDF one"}) == {"ok": True, "problems": []}
        assert store.load_chunks("T9")["DOC-01"][2].strip() == "Building A only." and doc_store.get_pdf("T9", "DOC-01") == b"%PDF one"
        assert doc_store.verify_room("T9", ROWS + [{"doc_id": "DOC-03", "page": 1, "text": "x"}])["ok"] is False
    finally:
        doc_store.delete_room("T9")
        doc_store.backend().client.drop_database("dataroom_eval_test")
