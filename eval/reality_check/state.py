"""The verdicts in force (a manual one wins), which findings they link, and what is still to ask."""
from __future__ import annotations

from .. import context, store
from .labels import LINKING
from .verdicts import case_hash


def case_verdict(check: dict, case_id: str) -> dict | None:
    """The verdict in force for a case: the manual one when there is one, otherwise the model's."""
    model = check["case_verdicts"].get(case_id)
    manual = check["manual"].get(f"case::{case_id}")
    if manual:
        return {**(model or {}), "status": manual["status"], "finding_ids": manual["finding_ids"], "manual": True,
                "note": manual["note"], "manual_case_hash": manual.get("case_hash"),
                "model_status": model["status"] if model else None}
    return {**model, "manual": False} if model else None


def linked(check: dict, case_ids: set[str] | None = None) -> dict[str, list[str]]:
    """{finding_id: [case_id, ...]} over the verdicts in force."""
    out: dict[str, list[str]] = {}
    ids = set(check["case_verdicts"]) | {k.split("::", 1)[1] for k in check["manual"] if k.startswith("case::")}
    for cid in sorted(ids):
        if case_ids is not None and cid not in case_ids:
            continue
        v = case_verdict(check, cid)
        if v and v["status"] in LINKING:
            for fid in v["finding_ids"]:
                out.setdefault(fid, []).append(cid)
    return out


def scope(check: dict) -> set[str] | None:
    """The cases this run is judged on: the data room's cases when it was first run, plus every case set by hand
    or accepted from it. A run is one fixed thing: cases added to the answer key later do not reopen it.
    None before the first run. A check from before this rule uses the answer key it was last run against."""
    ids = check.get("case_ids")
    if ids is None:
        if not check["case_verdicts"]:
            return None
        try:
            ids = [c["case_id"] for c in store.load_cases(check.get("snapshot")) if c["data_room"] == check["data_room"]]
        except Exception:                 # that answer key is gone: keep what was judged
            ids = list(check["case_verdicts"])
    return set(ids) | {k.split("::", 1)[1] for k in check["manual"] if k.startswith("case::")}


def _room_cases(check: dict, cases: list[dict], every: bool = False) -> list[dict]:
    room = [c for c in cases if c["data_room"] == check["data_room"]]
    keep = None if every else scope(check)
    return room if keep is None else [c for c in room if c["case_id"] in keep or c.get("origin_check") == check["check_id"]]


def added_since(check: dict, cases: list[dict]) -> list[str]:
    """Cases in the answer key that came after this run, so are not part of its result."""
    mine = {c["case_id"] for c in _room_cases(check, cases)}
    return [c["case_id"] for c in _room_cases(check, cases, every=True) if c["case_id"] not in mine]


def _stale(check: dict, case: dict, facts=None, rules=None) -> bool:
    v = check["case_verdicts"].get(case["case_id"])
    return bool(v) and v.get("case_hash") != case_hash(case, context.block_for_case(case, facts, rules))


def remaining(check: dict, cases: list[dict], facts=None, rules=None, recheck: bool = False) -> dict:
    """What is still to be asked: {"cases": [ids], "stale": [ids], "findings": [ids], "total"}.
    Only this run's cases without a verdict. A verdict stands once given: a case changed in the answer key
    since is listed in "stale" but asked again only with recheck, which also takes in cases added since.
    A case with a manual verdict is never asked again. Leftover findings are only known for certain once
    every case has a verdict; until then every unlinked finding is counted."""
    room_cases = _room_cases(check, cases, every=recheck)
    stale = [c["case_id"] for c in room_cases if _stale(check, c, facts, rules)]
    todo = [c["case_id"] for c in room_cases if f"case::{c['case_id']}" not in check["manual"]
            and (c["case_id"] not in check["case_verdicts"] or (recheck and c["case_id"] in stale))]
    links = linked(check, {c["case_id"] for c in room_cases})
    left = [f["finding_id"] for f in check["findings"]
            if f["finding_id"] not in links and f["finding_id"] not in check["new_verdicts"]
            and f"finding::{f['finding_id']}" not in check["manual"]]
    return {"cases": todo, "stale": [s for s in stale if f"case::{s}" not in check["manual"]], "findings": left,
            "total": len(todo) + len(left)}


def models_used(check: dict) -> dict[str, int]:
    """How many verdicts each model gave in this check ("no model call" for those decided by rule)."""
    out: dict[str, int] = {}
    for bucket in (check["case_verdicts"], check["new_verdicts"]):
        for v in bucket.values():
            m = (v.get("sent") or {}).get("model") or check["model"]
            out[m] = out.get(m, 0) + 1
    return out
