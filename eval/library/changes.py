"""Changes to the answer key between two uploads: the change log, the working draft and its freezing, the
pending rows, the rejected candidates and the correction requests."""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import context, store
from .columns import ACCEPTED, CASE_SKIP, CORRECTION


def _file(name: str) -> Path:
    return store.ANSWER_KEY / name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_changelog() -> list[dict]:
    return store._read(_file("changelog.json"), []) or []


def log_many(entries: list[dict]) -> None:
    if not entries:
        return
    at = _now()
    rows = load_changelog()
    rows += [{"at": at, "by": "evaluator", "action": e["action"], "object": e["object"], "id": e["id"],
              "before": e.get("before"), "after": e.get("after"), "reason": e.get("reason") or "",
              "origin": e.get("origin") or ""} for e in entries]
    store._write(_file("changelog.json"), rows)


def log(action: str, obj: str, id_: str, before=None, after=None, reason: str = "", origin: str = "") -> None:
    log_many([{"action": action, "object": obj, "id": id_, "before": before, "after": after, "reason": reason,
               "origin": origin}])


def ensure_draft() -> dict:
    """The working draft, created from the newest frozen snapshot the first time it is needed."""
    draft = store._read(_file("library_draft.json"))
    if draft is None:
        names = store.snapshots()
        cases = copy.deepcopy(store.load_cases(names[-1])) if names else []
        draft = {"snapshot": "Working draft", "base": names[-1] if names else None, "cases": cases}
        store._write(_file("library_draft.json"), draft)
    return draft


def draft_differs() -> int:
    """How many cases differ between the working draft and the newest frozen snapshot."""
    from .diffing import diff
    if not store.has_draft() or not store.snapshots():
        return 0
    d = diff(store.load_cases(), store.load_cases(store.DRAFT), "case_id", CASE_SKIP)
    return len(d["new"]) + len(d["changed"]) + len(d["removed"])


def freeze(reason: str = "") -> dict:
    """Writes the working draft as the next library_vN.json, with a copy of the facts and rules so an old
    score can be reproduced, logs it, and starts a fresh draft. Returns {"name", "cases", "pending"}."""
    draft = ensure_draft()
    names = store.snapshots()
    n = int(names[-1].split("_v")[1]) + 1 if names else 1
    name, label = f"library_v{n}", f"Library v{n}"
    cases = [{**c, "snapshot": label} for c in draft["cases"]]
    store._write(_file(f"{name}.json"), {"snapshot": label, "frozen_at": _now(), "cases": cases,
                                         "facts": context.load_facts(), "rules": context.load_rules()})
    store._write(_file("library_draft.json"), {"snapshot": "Working draft", "base": name, "cases": copy.deepcopy(cases)})
    pending = [p for p in load_pending() if p["kind"] == "case"]
    log("freeze", "case", name, before=names[-1] if names else None, after=f"{len(cases)} cases",
        reason=reason or f"Froze the working draft as {label}.", origin=name)
    return {"name": name, "cases": len(cases), "pending": len(pending)}


def load_pending() -> list[dict]:
    return store._read(_file("pending.json"), []) or []


def load_rejected() -> list[dict]:
    return store._read(_file("rejected_candidates.json"), []) or []


def next_case_id(room: str) -> str:
    """The next free case ID for a data room, over every snapshot, the draft and the pending rows."""
    ids = [c["case_id"] for c in store.load_cases(store.DRAFT)] if (store.has_draft() or store.snapshots()) else []
    ids += [c["case_id"] for name in store.snapshots() for c in store.load_cases(name)]
    ids += [p["case_id"] for p in load_pending()]
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(rf"{re.escape(room)}-(\d+)", i))]
    return f"{room}-{max(nums, default=0) + 1:03d}"


def add_pending_case(case: dict, check_id: str, reason: str) -> dict:
    """An accepted candidate: stored as a pending row, added to the working draft at once, and logged."""
    draft = ensure_draft()
    if any(c["case_id"] == case["case_id"] for c in draft["cases"]):
        raise ValueError(f"Case {case['case_id']} already exists.")
    case = {**case, "snapshot": "Working draft", "origin_check": check_id}
    draft["cases"].append(case)
    store._write(_file("library_draft.json"), draft)
    store._write(_file("pending.json"), load_pending() + [{
        "kind": "case", "case_id": case["case_id"], "data_room": case["data_room"], "case": case, "status": ACCEPTED,
        "check_id": check_id, "reason": reason, "at": _now()}])
    log("accept", "candidate", case["case_id"], after=case["summary"], reason=reason, origin=check_id)
    return case


def add_rejected(finding: dict, room: str, reason: str, rule_id: str | None, check_id: str, snapshot: str = "") -> None:
    keep = {k: finding.get(k) for k in ("finding_id", "summary", "claims_compared", "explanation", "citations",
                                        "classification", "severity")}
    store._write(_file("rejected_candidates.json"), load_rejected() + [{
        "data_room": room, "finding": keep, "reason": reason, "rule_id": rule_id, "check_id": check_id,
        "snapshot": snapshot, "at": _now()}])
    log("reject", "candidate", f"{check_id}:{finding.get('finding_id')}", after=finding.get("summary"), reason=reason,
        origin=check_id)


def add_correction(case_id: str, room: str, what: str, corrected: str, reason: str, check_id: str) -> None:
    """'The ground truth is wrong here': a request, applied only when the corrected sheet is uploaded."""
    store._write(_file("pending.json"), load_pending() + [{
        "kind": "correction", "case_id": case_id, "data_room": room, "what": what, "corrected": corrected,
        "status": CORRECTION, "check_id": check_id, "reason": reason, "at": _now()}])
    log("correction", "case", case_id, before=what, after=corrected, reason=reason, origin=check_id)
