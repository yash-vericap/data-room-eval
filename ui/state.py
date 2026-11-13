"""What every screen shares: the answer key in use, the scored runs, the data rooms, and cached results."""
from __future__ import annotations

from types import SimpleNamespace

import streamlit as st

from eval import doc_store, scoring, store
from eval import reality_check as rc

S = SimpleNamespace(snapshot=None, keys=[], cases=[], results=[], documents={}, rooms=[], room="All", case_by_id={})


def stamp() -> float:
    """Changes whenever a stored file the screens read changes, so cached results are recomputed then only."""
    files = (list(store.SUBMISSIONS.rglob("*.json")) + list(store.ANSWER_KEY.glob("*.json"))
             + list(store.DATA_ROOM.glob("*/chunks.json")))
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0) + doc_store.generation


@st.cache_data(show_spinner="Scoring runs...")
def _load(data_stamp: float, snapshot: str):
    cases = store.load_cases(snapshot)
    return scoring.score_all(cases=cases), cases, store.load_documents()


def refresh() -> bool:
    """Fills S for this rerun. False when there is no answer key at all."""
    keys = list(reversed(store.snapshots())) + ([store.DRAFT] if store.has_draft() else [])
    if not keys:
        return False
    ss = st.session_state
    if ss.pop("use_draft", False) and store.DRAFT in keys:      # after a candidate is accepted or a sheet is uploaded
        ss["answer_key"] = ss["w_answer_key"] = store.DRAFT
    if ss.get("answer_key") not in keys:
        ss["answer_key"] = keys[0]
        ss.pop("w_answer_key", None)
    S.keys, S.snapshot = keys, ss["answer_key"]
    S.results, S.cases, S.documents = _load(stamp(), S.snapshot)
    S.case_by_id = {c["case_id"]: c for c in S.cases}
    S.rooms = store.data_rooms(S.cases)
    S.room = ss.get("room_filter") if ss.get("room_filter") in S.rooms else "All"
    return True


def _mtime(check_id: str) -> float:
    p = rc.storage._path(check_id)
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner=False, max_entries=64)
def _results(check_id: str, check_mtime: float, data_stamp: float, snapshot: str):
    scored, cases, _ = _load(data_stamp, snapshot)
    check = rc.load_check(check_id)
    return rc.results(check, cases), rc.baseline_comparison(check, scored, cases)


def results_of(check: dict) -> tuple[dict, dict]:
    """(results, baseline comparison) of a check, worked out once per change to the check or the data."""
    return _results(check["check_id"], _mtime(check["check_id"]), stamp(), S.snapshot)


def checked_runs(room: str | None) -> list[tuple[dict, dict]]:
    """(check, results) for every check with verdicts on a data room (all rooms for None), oldest first."""
    from eval import stats
    return [(c, results_of(c)[0]) for c in (rc.load_check(m["check_id"]) for m in stats.checked(room)) if c]
