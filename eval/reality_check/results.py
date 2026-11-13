"""Everything the screen and the report show: one row per case, one per unmapped finding, and the metrics."""
from __future__ import annotations

from .. import context, store
from .labels import (CANDIDATE, FOUND, KNOWN, MISSED, NOT_DISC, NOT_IN_DOCS, PARTIAL, PARTIAL_CREDIT, REAL,
                     REJECTED_EVALUATOR, REJECTED_RULE, REVIEW, WRONG)
from .state import _room_cases, _stale, case_verdict, linked
from .verdicts import case_hash, own_quotes


def finding_band(check: dict, fid: str) -> tuple[str, dict]:
    """Where an unmapped finding sits: Candidate, Needs review, Rejected by rule or Rejected by evaluator,
    with its verdict. A manual verdict on the finding wins."""
    v = dict(check["new_verdicts"].get(fid) or {})
    manual = check["manual"].get(f"finding::{fid}")
    if manual:
        v.update(manual=True, note=manual["note"], model_status=v.get("status"))
        if manual["status"] == REJECTED_EVALUATOR:
            return REJECTED_EVALUATOR, v
        v["status"] = manual["status"]
        band = CANDIDATE if manual["status"] == REAL else REVIEW if manual["status"] == REVIEW else REJECTED_EVALUATOR
        return band, v
    if not v:
        return "Not checked", {"status": "Not checked"}
    return (v.get("gate") or {}).get("outcome") or REVIEW, v


def _block(rows: list[dict]) -> dict:
    points, possible = sum(r["points"] for r in rows), sum(r["weight"] for r in rows)
    crit = [r for r in rows if r["severity"] == "Critical"]
    return {"cases": len(rows), "found": sum(r["status"] == FOUND for r in rows),
            "partial": sum(r["status"] == PARTIAL for r in rows), "missed": sum(r["status"] == MISSED for r in rows),
            "open": sum(r["status"] in (REVIEW, "Not checked") for r in rows),
            "points": points, "possible": possible, "accuracy": points / possible if possible else None,
            "critical": len(crit), "critical_missed": sum(r["status"] == MISSED for r in crit)}


def results(check: dict, cases: list[dict], chunks: dict | None = None) -> dict:
    """Everything the screen and the report show: {"cases", "non_issues", "new", "metrics"}.

    cases and non_issues: one row per ground-truth case with the verdict in force. new: one row per finding
    that maps to no case, with its band. Found earns the full weight, Partially found half."""
    room_cases = _room_cases(check, cases)
    by_f = {f["finding_id"]: f for f in check["findings"]}
    rules = context.load_rules()
    rep, non = [], []
    for c in room_cases:
        v = case_verdict(check, c["case_id"]) or {"status": "Not checked", "finding_ids": [], "manual": False}
        fids = [i for i in v.get("finding_ids") or [] if i in by_f]
        stale = _stale(check, c) if not v.get("manual") else bool(v.get("manual_case_hash")) and v["manual_case_hash"] != case_hash(c, context.block_for_case(c))
        row = {"case_id": c["case_id"], "status": v["status"], "severity": c["severity"], "weight": c["weight"],
               "set": c["set"], "report": c["report"], "summary": c["summary"], "classification": c["classification"],
               "finding_ids": fids, "covered": v.get("covered") or "", "missing": v.get("missing") or "",
               "quote": v.get("quote") or "", "explanation": v.get("explanation") or "", "manual": bool(v.get("manual")),
               "note": v.get("note") or "", "model_status": v.get("model_status"), "stale": stale,
               "by_rule": bool(v.get("by_rule")) and not v.get("manual"),
               "origin_check": c.get("origin_check"), "rule_ids": context.case_rules(c, rules)}
        if c["report"]:
            row["points"] = c["weight"] if v["status"] == FOUND else PARTIAL_CREDIT * c["weight"] if v["status"] == PARTIAL else 0
            row["classes"] = [by_f[i]["classification"] for i in fids]
            row["severities"] = [by_f[i]["severity"] for i in fids]
            row["class_correct"] = (c["classification"] in row["classes"]) if fids and v["status"] in (FOUND, PARTIAL) else None
            rep.append(row)
        else:
            non.append(row)

    links = linked(check, {c["case_id"] for c in room_cases})
    new = []
    for f in check["findings"]:
        if f["finding_id"] in links:
            continue
        band, v = finding_band(check, f["finding_id"])
        gate = v.get("gate") or {}
        new.append({"finding_id": f["finding_id"], "band": band, "status": v.get("status") or "Not checked",
                    "summary": f["summary"], "severity_given": f["severity"], "severity_judged": v.get("severity"),
                    "documents": sorted({c["doc_id"] for c in f["citations"] if c["doc_id"]}),
                    "precheck": (v.get("precheck") or {}).get("tag"), "rule_id": gate.get("rule_id"),
                    "reason": gate.get("reason") or "", "explanation": v.get("explanation") or "",
                    "manual": bool(v.get("manual")), "note": v.get("note") or "", "quote": v.get("quote") or "",
                    "quote_found": v.get("quote_found"), "rule_ids": v.get("rule_ids") or []})

    mine = {r["case_id"] for r in rep if r["origin_check"] == check["check_id"]}
    grounded_cases = {r["case_id"] for r in rep if r["status"] in (FOUND, PARTIAL)}
    grounded = sum(any(c in grounded_cases for c in cids) for cids in links.values()) + sum(n["status"] == REAL for n in new)
    by_rule: dict[str, int] = {}
    for n in new:
        if n["band"] == REJECTED_RULE:
            by_rule[n["rule_id"] or "(no rule)"] = by_rule.get(n["rule_id"] or "(no rule)", 0) + 1
    chunks = store.load_chunks(check["data_room"]) if chunks is None else chunks
    quotes = [q for f in check["findings"] for q in own_quotes(f, chunks) if q != "Not checked"]
    judged_class = [r["class_correct"] for r in rep if r["class_correct"] is not None]
    n_find = len(check["findings"])
    rejected = sum(by_rule.values())
    metrics = {
        "all": _block(rep), "withheld": _block([r for r in rep if r["set"] == "Withheld"]),
        "development": _block([r for r in rep if r["set"] == "Development"]),
        "all_before": _block([r for r in rep if r["case_id"] not in mine]), "from_this_run": len(mine),
        "findings": n_find, "grounded": grounded, "grounded_share": grounded / n_find if n_find else None,
        "new_real": sum(n["status"] == REAL for n in new), "known_change": sum(n["status"] == KNOWN for n in new),
        "not_in_documents": sum(n["status"] == NOT_IN_DOCS for n in new),
        "not_a_discrepancy": sum(n["status"] == NOT_DISC for n in new),
        "wrongly_flagged": sum(r["status"] == WRONG for r in non),
        "wrongly_flagged_rules": {r["case_id"]: r["rule_ids"] for r in non if r["status"] == WRONG},
        "rejected_by_rules": rejected, "rejected_per_rule": by_rule, "noise_share": rejected / n_find if n_find else None,
        "made_up": sum(n["band"] == REJECTED_RULE and n["status"] == NOT_IN_DOCS for n in new),
        "candidates": sum(n["band"] == CANDIDATE for n in new), "accepted": len(mine),
        "needs_review": sum(n["band"] == REVIEW for n in new),
        "rejected_by_evaluator": sum(n["band"] == REJECTED_EVALUATOR for n in new),
        "not_checked": sum(n["band"] == "Not checked" for n in new),
        "stale": sum(r["stale"] for r in rep + non),
        "class_accuracy": sum(judged_class) / len(judged_class) if judged_class else None,
        "quotes_checked": len(quotes),
        "quotes_found": sum(q != "Not found" for q in quotes) / len(quotes) if quotes else None,
    }
    return {"cases": rep, "non_issues": non, "new": new, "metrics": metrics}


def verdict_sentence(res: dict, label: str = "Vericap") -> str:
    """The result in one plain sentence, built from the numbers."""
    m, a = res["metrics"], res["metrics"]["all"]
    text = (f"{label} found {a['found']} of {a['cases']} cases fully, {a['partial']} partly and missed {a['missed']}"
            + (f", including {a['critical_missed']} Critical" if a["critical_missed"] else "") + ".")
    if a["open"]:
        text += f" {a['open']} case verdicts are still open."
    extra = []
    if m["new_real"]:
        extra.append(f"{m['new_real']} finding{'s are real issues' if m['new_real'] != 1 else ' is a real issue'} the ground truth does not have")
    if m["known_change"] + m["wrongly_flagged"]:
        n = m["known_change"] + m["wrongly_flagged"]
        extra.append(f"{n} {'were known changes or non-issues' if n != 1 else 'was a known change or non-issue'} reported as problems")
    if m["made_up"]:
        extra.append(f"{m['made_up']} could not be found in the documents")
    return text + (" " + ", and ".join(extra).capitalize() + "." if extra else "")
