"""Fixtures: a stand-in model on this machine, no outside document store, and data folders in tmp_path."""
import json as _json
import os
import shutil

import pytest

from eval import doc_store, store

from helpers import ROOT


def _local_model(monkeypatch):
    """A stand-in model on this machine, and no document store: the tests never depend on outside services."""
    for k in list(os.environ):
        if k.startswith("EVAL_") or k.startswith("MONGO_") or k.endswith("_API_KEY") or k.endswith("_TOKEN"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "stand-in")
    monkeypatch.setenv("EVAL_RC_FOCUS", "0")          # every finding for every case, as the brief's tests expect
    doc_store.use_settings()


@pytest.fixture(autouse=True)
def _no_outside_store(monkeypatch):
    """Every test reads page text from files or the in-memory store, whatever .env says."""
    monkeypatch.delenv("MONGO_URI", raising=False)
    doc_store.use_settings()
    yield
    doc_store.use_settings()


EXTRA_PAGES = [("HTC02", "DOC-04", 6, "Qualified rehabilitation expenditures: $39.8M"),
               ("HTC02", "DOC-05", 7, "Qualified rehabilitation expenditures (revised): $36.45M")]


def _page_text_from_the_answer_key(folder):
    """Page text built from the quotes the answer key cites, so the tests need no data room on disk."""
    pages: dict[tuple, list[str]] = {}
    for c in _json.loads((ROOT / "answer_key" / "library_v1.json").read_text(encoding="utf-8"))["cases"]:
        for cit in c["citations"]:
            if cit["doc_id"] and cit["quote"] and not cit["quote"].startswith("["):
                pages.setdefault((c["data_room"], cit["doc_id"], cit["page"] or 1), []).append(cit["quote"])
    for room, doc, page, text in EXTRA_PAGES:
        pages.setdefault((room, doc, page), []).append(text)
    for room in sorted({k[0] for k in pages}):
        store._write(folder / room / "chunks.json", [{"doc_id": d, "page": p, "text": "\n".join(q), "read_by": "text"}
                                                     for (r, d, p), q in sorted(pages.items()) if r == room])


@pytest.fixture
def empty(tmp_path, monkeypatch):
    """No stored data at all: checks, facts, rules and the change log go to an empty folder."""
    _local_model(monkeypatch)
    monkeypatch.setattr(store, "ANSWER_KEY", tmp_path / "answer_key")
    monkeypatch.setattr(store, "DATA_ROOM", tmp_path / "data_room")
    monkeypatch.setattr(store, "DATA", tmp_path)                 # checks go to tmp_path/reality_checks
    return tmp_path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the repository data, so nothing in the real answer key is changed."""
    _local_model(monkeypatch)
    working = {"library_draft.json", "pending.json", "changelog.json", "rejected_candidates.json"}   # yours, not the tests'
    for d in ("answer_key", "submissions", "reviews"):
        shutil.copytree(ROOT / d, tmp_path / d, ignore=lambda _, names: [n for n in names if n in working])
    _page_text_from_the_answer_key(tmp_path / "data_room")
    for name, path in [("DATA", tmp_path), ("ANSWER_KEY", tmp_path / "answer_key"), ("SUBMISSIONS", tmp_path / "submissions"),
                       ("REVIEWS", tmp_path / "reviews" / "decisions.json"), ("DATA_ROOM", tmp_path / "data_room"),
                       ("REPORTS", tmp_path / "reports")]:
        monkeypatch.setattr(store, name, path)
    return tmp_path


@pytest.fixture
def local_model(monkeypatch):
    _local_model(monkeypatch)
