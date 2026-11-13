"""Writes a validated upload and logs every changed object."""
from __future__ import annotations

from .. import store
from .changes import _file, ensure_draft, load_pending, log_many
from .diffing import current, preview
from .validate import validate


def apply(staged: dict, file_name: str = "", note: str = "") -> dict:
    """Writes a validated upload: cases to the working draft, the rest to their files, and one change-log
    entry per changed object. Raises ValueError when blocking errors remain."""
    problems = validate(staged)
    if problems["errors"]:
        raise ValueError("The upload has blocking errors: " + "; ".join(problems["errors"][:5]))
    now, pv = current(), preview(staged)
    changes, entries = pv["changes"], []

    def record(tab: str, obj: str, old: dict, new: dict, summary):
        d = changes.get(tab) or {"new": [], "changed": [], "removed": []}
        for i in d["new"]:
            entries.append({"action": "upload", "object": obj, "id": i, "after": summary(new[i]), "reason": note or "Added in the sheet.", "origin": file_name})
        for c in d["changed"]:
            entries.append({"action": "upload", "object": obj, "id": c["id"], "before": {f: v[0] for f, v in c["fields"].items()},
                            "after": {f: v[1] for f, v in c["fields"].items()}, "reason": note or "Changed in the sheet.", "origin": file_name})
        for i in d["removed"]:
            entries.append({"action": "upload", "object": obj, "id": i, "before": summary(old[i]), "reason": note or "Removed from the sheet.", "origin": file_name})

    if staged["cases"] is not None:
        draft = ensure_draft()
        old = {c["case_id"]: c for c in draft["cases"]}
        pend = {p["case_id"]: p["case"] for p in load_pending() if p["kind"] == "case"}
        new_cases = []
        for c in staged["cases"]:
            origin = old.get(c["case_id"]) or pend.get(c["case_id"]) or {}
            new_cases.append({**c, **{k: origin[k] for k in ("origin", "origin_check") if origin.get(k)}})
        uploaded = {c["case_id"] for c in new_cases}
        new_cases += [p["case"] for p in pv["pending_kept"] if p["kind"] == "case" and p["case_id"] not in uploaded]
        d = changes["Ground Truth"]
        d["removed"] = [i for i in d["removed"] if i not in {c["case_id"] for c in new_cases}]
        store._write(_file("library_draft.json"), {**draft, "cases": new_cases})
        store._write(_file("pending.json"), pv["pending_kept"])
        record("Ground Truth", "case", old, {c["case_id"]: c for c in new_cases}, lambda c: c.get("summary"))
    if staged["documents"] is not None:
        key = lambda d: f"{d['data_room']} {d['doc_id']}"
        store._write(_file("documents.json"), staged["documents"])
        record("Documents", "document", {key(d): d for d in now["documents"]}, {key(d): d for d in staged["documents"]},
               lambda d: d.get("title"))
    if staged["facts"] is not None:
        key = lambda f: f"{f['data_room']} {f['fact_id']}"
        store._write(_file("facts.json"), staged["facts"])
        record("Fact Sheet", "fact", {key(f): f for f in now["facts"]}, {key(f): f for f in staged["facts"]},
               lambda f: f"{f.get('subject')}: {f.get('value')}")
    if staged["rules"] is not None:
        store._write(_file("context_rules.json"), staged["rules"])
        record("Context Rules", "rule", {r["rule_id"]: r for r in now["rules"]}, {r["rule_id"]: r for r in staged["rules"]},
               lambda r: r.get("name"))
    if staged["runs"] is not None:
        d = changes["Baseline Runs"]
        for rid in d["new"] + [c["id"] for c in d["changed"]]:
            payload = staged["runs"][rid]
            folder = "baseline" if payload["run"]["source"] == "Baseline model" else "system"
            store.save_submission(payload, folder=folder, allow_problems=True)
        record("Baseline Runs", "baseline", now["runs"], staged["runs"], lambda p: f"{len(p['findings'])} findings")
        reviews = store.load_reviews()
        d = changes["Baseline decisions"]
        for k in d["new"] + [c["id"] for c in d["changed"]]:
            reviews[k] = staged["reviews"][k]
        if d["new"] or d["changed"]:
            store._write(store.REVIEWS, reviews)
            entries.append({"action": "upload", "object": "baseline", "id": "manual decisions",
                            "after": f"{len(d['new'])} new, {len(d['changed'])} changed",
                            "reason": note or "Decisions made by hand in the sheet.", "origin": file_name})
    log_many(entries)
    return {"written": {t["tab"]: t for t in pv["tabs"]}, "logged": len(entries), "warnings": problems["warnings"],
            "pending_cleared": len(pv["pending_cleared"]), "pending_kept": len(pv["pending_kept"])}
