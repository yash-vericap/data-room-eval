"""One run, and every stored run, scored by the fixed rules."""
from __future__ import annotations

from .. import matching, store
from .evidence import check_evidence
from .metrics import metrics


def score_run(run: dict, all_cases: list[dict], reviews: dict | None = None, chunks: dict | None = None) -> dict:
    """Returns {"run", "rows", "cases", "metrics", "problems"} for one run.

    rows:  one per finding-to-case link, with the match, class, severity and evidence results.
    cases: one per answer-key case of the run's data room, with its outcome for this run.
    """
    info, findings = run["run"], run["findings"]
    room = info["data_room"]
    cases = [c for c in all_cases if c["data_room"] == room]
    by_case = {c["case_id"]: c for c in cases}
    by_finding = {f["finding_id"]: f for f in findings}
    chunks = store.load_chunks(room) if chunks is None else chunks
    links = matching.match_run(findings, cases, reviews if reviews is not None else store.load_reviews(), info["run_id"])

    rows = []
    for link in links:
        f, case = by_finding[link["finding_id"]], by_case.get(link["case_id"])
        ev = check_evidence(f, case, chunks)
        rows.append({
            **link,
            "classification": f["classification"], "severity": f["severity"], "summary": f["summary"],
            "confidence": f["confidence"],
            "expected_class": case["classification"] if case else None,
            "expected_severity": case["severity"] if case else None,
            "case_report": case["report"] if case else None,
            "case_set": case["set"] if case else None,
            "case_weight": case["weight"] if case else None,
            "case_ambiguous": case["ambiguous"] if case else None,
            "class_correct": (f["classification"] == case["classification"]) if case else None,
            "severity_correct": (f["severity"] == case["severity"]) if case else None,
            "evidence_rule": ev["sufficient"], "evidence": link["evidence_manual"] or ev["sufficient"],
            "relevant_share": ev["relevant_share"], "real_share": ev["real_share"], "invented": ev["invented"],
            "real": ev["real"],
        })

    matched = [r for r in rows if r["status"] == "Match" and r["case_id"]]
    best_for_case = {}
    for r in matched:
        best_for_case.setdefault(r["case_id"], r)

    case_rows = []
    for c in cases:
        r = best_for_case.get(c["case_id"])
        if c["report"]:
            outcome = "Found" if r else "Missed"
        else:
            outcome = "Correct" if (r is None or r["class_correct"]) else "False alarm"
        case_rows.append({
            "case_id": c["case_id"], "expected_class": c["classification"], "expected_severity": c["severity"],
            "weight": c["weight"], "report": c["report"], "set": c["set"], "ambiguous": c["ambiguous"],
            "summary": c["summary"], "check_type": c["check_type"], "scenario_tags": c["scenario_tags"],
            "documents": c["documents"], "outcome": outcome,
            "finding_id": r["finding_id"] if r else None, "class": r["classification"] if r else None,
            "severity": r["severity"] if r else None, "class_correct": r["class_correct"] if r else None,
            "severity_correct": r["severity_correct"] if r else None, "evidence": r["evidence"] if r else None,
            "reasoning": r["reasoning"] if r else None, "points": (c["weight"] if r else 0) if c["report"] else None,
        })

    return {"run": info, "rows": rows, "cases": case_rows, "problems": run.get("problems", []),
            "metrics": metrics(info, findings, rows, case_rows)}


def score_all(runs: list[dict] | None = None, cases: list[dict] | None = None, reviews: dict | None = None) -> list[dict]:
    runs = store.load_runs() if runs is None else runs
    cases = store.load_cases() if cases is None else cases
    reviews = store.load_reviews() if reviews is None else reviews
    chunk_cache: dict[str, dict] = {}
    out = []
    for run in runs:
        room = run["run"].get("data_room", "")
        if room not in chunk_cache:
            chunk_cache[room] = store.load_chunks(room)
        run["run"]["problems"] = run.get("problems", [])
        out.append(score_run(run, cases, reviews, chunk_cache[room]))
    return out
