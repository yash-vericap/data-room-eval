"""Runs whatever is still open: every case without a current verdict, then every finding that maps to no
case, then the rule gate."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from .. import context, judge, library, matching, store
from ..providers import JudgeQuotaReached, JudgeUnavailable, settings
from .labels import MISSED, NOT_FLAGGED
from .messages import focused, rank_findings
from .state import _room_cases, remaining, scope
from .storage import _LOCK, _now, save
from .verdicts import case_hash, judge_case, judge_leftover


def run_check(check: dict, cases: list[dict], client=None, progress=None, snapshot: str | None = None,
              workers: int | None = None, notify=None, recheck: bool = False) -> dict:
    """Runs whatever is still open: first every case without a current verdict, then every finding that maps
    to no case, then the rule gate. Each verdict is saved as soon as it exists.

    The first run fixes which cases the run is judged on (see state.scope). recheck also takes in the cases
    added to the answer key since, and asks again about cases changed since their verdict.

    progress(step, i, n) is called after every verdict. Returns {"asked", "left", "stopped"}; `stopped`
    holds the provider's message when a limit ended the run early."""
    cfg = settings()
    model = check["model"]
    room = check["data_room"]
    if check.get("case_ids") is None or recheck:      # fix the run's cases once; recheck takes in the newer ones
        keep = scope(check)
        every = {c["case_id"] for c in _room_cases(check, cases, every=True)} if keep is None or recheck else set()
        check["case_ids"] = sorted((keep or set()) | every)
        save(check)
    room_cases = _room_cases(check, cases)
    chunks = store.load_chunks(room)
    facts, rules, docs = context.load_facts(room), context.load_rules(), context.doc_info(room)
    todo = remaining(check, cases, facts, rules, recheck)
    out = {"asked": 0, "left": todo["total"], "stopped": None, "by_rule": 0, "switches": [], "models": []}
    if not todo["total"]:
        _gate_all(check, room_cases, rules)
        return out
    client = client or judge._client()
    if hasattr(client, "on_event"):
        client.on_event = notify
    if hasattr(client, "warm_up"):        # find the busy and used-up models at once, not one after another
        if progress:
            progress("Checking which models answer", 0, 1)
        ready = [u["model"] for u in client.warm_up() if u["state"] == "ready"]
        if notify:
            notify(f"Models answering now: {', '.join(ready) or 'none; the check waits for the first to come back'}.")
    index = matching.RoomIndex(room_cases)
    by_id = {c["case_id"]: c for c in room_cases}
    stop = threading.Event()
    if snapshot:
        check["snapshot"] = snapshot

    def guarded(fn, key, bucket):
        def work(item):
            if stop.is_set():
                return False
            try:
                res = fn(item)
            except JudgeQuotaReached as e:
                stop.set()
                out["stopped"] = str(e)
                return False
            except JudgeUnavailable:
                stop.set()
                raise
            with _LOCK:                       # save at once: nothing is lost if the run stops
                check[bucket][key(item)] = res
                check["input_tokens"] += res.pop("input_tokens", 0)
                check["output_tokens"] += res.pop("output_tokens", 0)
                res["at"] = _now()
                save(check)
            return True
        return work

    def run(step, items, work):
        done, n = 0, workers or cfg["workers"]
        if progress and items:
            progress(step, 0, len(items))
        if n <= 1:                        # one at a time, in this thread, so the screen can show each step as it happens
            for i, item in enumerate(items, start=1):
                done += bool(work(item))
                if progress:
                    progress(step, i, len(items))
            return done
        with ThreadPoolExecutor(max_workers=n) as pool:
            for i, ok in enumerate(pool.map(work, items), start=1):
                done += bool(ok)
                if progress:
                    progress(step, i, len(items))
        return done

    todo_cases = [by_id[c] for c in todo["cases"]]
    ranked = {c["case_id"]: rank_findings(c, check["findings"], index) for c in todo_cases}
    if focused():               # nothing in the run is about these cases: decided by rule, no model call
        for c in [c for c in todo_cases if not ranked[c["case_id"]]]:
            status, raw = (MISSED, "missed") if c["report"] else (NOT_FLAGGED, "not_flagged")
            check["case_verdicts"][c["case_id"]] = {
                "status": status, "raw_status": raw, "finding_ids": [], "covered": "", "missing": "", "quote": "",
                "explanation": "No finding of the run shares a document, a figure or wording with this case, so it was "
                               "decided by rule without a model call.",
                "case_hash": case_hash(c, context.block_for_case(c, facts, rules)), "by_rule": True,
                "sent": {"provider": "rule", "model": "no model call", "at": _now(), "pages": []}, "at": _now()}
            out["by_rule"] = out.get("by_rule", 0) + 1
        save(check)
        todo_cases = [c for c in todo_cases if ranked[c["case_id"]]]
    out["asked"] += run("Cases against the run", todo_cases, guarded(
        lambda c: judge_case(c, check["findings"], ranked[c["case_id"]], chunks, client, model, cfg,
                             facts, rules), lambda c: c["case_id"], "case_verdicts"))
    if not stop.is_set():
        left = remaining(check, cases, facts, rules, recheck)
        if not left["cases"]:                 # step 2 only once every case has a verdict
            by_f = {f["finding_id"]: f for f in check["findings"]}
            out["asked"] += run("Leftover findings against the documents", [by_f[i] for i in left["findings"]], guarded(
                lambda f: judge_leftover(f, room, chunks, client, model, cfg, facts, rules, docs),
                lambda f: f["finding_id"], "new_verdicts"))
    _gate_all(check, room_cases, rules)
    out["left"] = remaining(check, cases, facts, rules)["total"]
    out["switches"] = list(getattr(client, "events", []))
    out["models"] = client.usage() if hasattr(client, "usage") else []
    return out


def _gate_all(check: dict, room_cases: list[dict], rules: list[dict] | None = None) -> None:
    """Runs the rule gate over every judged leftover finding and stores the outcome with its verdict."""
    rejected = [r for r in library.load_rejected() if r.get("check_id") != check["check_id"]]
    by_f = {f["finding_id"]: f for f in check["findings"]}
    changed = False
    for fid, v in check["new_verdicts"].items():
        g = context.gate(by_f[fid], v.get("precheck"), v, check["data_room"], rules, rejected)
        if v.get("gate") != g:
            v["gate"], changed = g, True
    if changed:
        save(check)
