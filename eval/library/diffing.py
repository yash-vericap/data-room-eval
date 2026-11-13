"""What is stored now, and what an upload would change, field by field."""
from __future__ import annotations

import json

from .. import context, contract, store
from .changes import _file, load_pending
from .columns import CASE_SKIP


def current() -> dict:
    """What the tool holds today, in the same shape as stage()."""
    try:
        cases = store.load_cases(store.DRAFT)
    except FileNotFoundError:
        cases = []
    runs = {}
    for path in sorted((store.SUBMISSIONS / "baseline").glob("*.json")) if (store.SUBMISSIONS / "baseline").exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            runs[str((payload.get("run") or {}).get("run_id") or path.stem)] = payload
        except json.JSONDecodeError:
            continue
    return {"cases": cases, "documents": store._read(_file("documents.json"), []) or [], "facts": context.load_facts(),
            "rules": context.load_rules(), "runs": runs, "reviews": store.load_reviews()}


def _plain(v):
    """A value in the form two versions are compared in: citations by their text as written."""
    if isinstance(v, list) and v and all(isinstance(x, dict) and "raw" in x for x in v):
        return [x["raw"] for x in v]
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    return "" if v is None else v


def diff(old: list[dict], new: list[dict], key, skip: set[str] = frozenset()) -> dict:
    """{"new": [ids], "removed": [ids], "changed": [{"id", "fields": {field: [before, after]}}]}."""
    ident = (lambda r: tuple(r.get(k) for k in key)) if isinstance(key, tuple) else (lambda r: r.get(key))
    show = lambda i: " ".join(str(x) for x in i) if isinstance(i, tuple) else i
    a, b = {ident(r): r for r in old}, {ident(r): r for r in new}
    changed = []
    for i in b:
        if i in a:
            fields = {f: [a[i].get(f), b[i].get(f)] for f in sorted((set(a[i]) | set(b[i])) - set(skip))
                      if _plain(a[i].get(f)) != _plain(b[i].get(f))}
            if fields:
                changed.append({"id": show(i), "fields": fields})
    return {"new": [show(i) for i in b if i not in a], "removed": [show(i) for i in a if i not in b], "changed": changed}


def _differences(staged: dict, now: dict) -> dict:
    out = {}
    if staged["cases"] is not None:
        out["Ground Truth"] = diff(now["cases"], staged["cases"], "case_id", CASE_SKIP)
    if staged["documents"] is not None:
        out["Documents"] = diff(now["documents"], staged["documents"], ("data_room", "doc_id"))
    if staged["facts"] is not None:
        out["Fact Sheet"] = diff(now["facts"], staged["facts"], ("data_room", "fact_id"))
    if staged["rules"] is not None:
        out["Context Rules"] = diff(now["rules"], staged["rules"], "rule_id")
    if staged["runs"] is not None:
        a, b = now["runs"], staged["runs"]
        norm = lambda p: json.dumps(contract.normalise(p)[0], sort_keys=True, default=str)
        out["Baseline Runs"] = {"new": [r for r in b if r not in a], "removed": [],
                                "changed": [{"id": r, "fields": {}} for r in b if r in a and norm(a[r]) != norm(b[r])]}
        keep = lambda rv: {k: rv.get(k) for k in ("status", "case_ids", "evidence", "reasoning", "note")}
        mine = {k: rv for k, rv in staged["reviews"].items()
                if now["reviews"].get(k, {}).get("decided_by", "sheet import") == "sheet import"}
        out["Baseline decisions"] = {
            "new": [k for k in mine if k not in now["reviews"]], "removed": [],
            "changed": [{"id": k, "fields": {}} for k, rv in mine.items()
                        if k in now["reviews"] and keep(rv) != keep(now["reviews"][k])]}
    return out


def preview(staged: dict) -> dict:
    """What an upload would change. Nothing is written.

    {"tabs": [{"tab", "new", "changed", "removed"}], "changes": {tab: diff}, "pending_cleared": [...],
     "pending_kept": [...]}"""
    changes = _differences(staged, current())
    uploaded = {c["case_id"] for c in staged["cases"] or []}
    touched = {c["id"] for c in changes.get("Ground Truth", {}).get("changed", [])}
    cleared, kept = [], []
    for p in load_pending():
        done = p["case_id"] in uploaded if p["kind"] == "case" else p["case_id"] in touched
        (cleared if staged["cases"] is not None and done else kept).append(p)
    return {"tabs": [{"tab": t, "new": len(d["new"]), "changed": len(d["changed"]), "removed": len(d["removed"])}
                     for t, d in changes.items()],
            "changes": changes, "pending_cleared": cleared, "pending_kept": kept}
