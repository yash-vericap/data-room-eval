"""The metrics of one scored run."""
from __future__ import annotations

from collections import Counter


def _rate(n, d):
    return n / d if d else None


def metrics(info, findings, rows, case_rows) -> dict:
    status = {}
    for r in rows:                                    # one status per finding (first row carries it)
        status.setdefault(r["finding_id"], r["status"])
    counted = [fid for fid, s in status.items() if s != "Duplicate"]
    matched = [r for r in rows if r["status"] == "Match" and r["case_id"]]

    def is_valid(r):                                  # reportable case found, or a negative case labelled correctly
        return r["case_report"] or r["class_correct"]

    valid = {r["finding_id"] for r in matched if is_valid(r)}
    false_alarm = {r["finding_id"] for r in matched if not is_valid(r)} - valid
    fp_candidates = [fid for fid, s in status.items() if s == "False positive candidate"]
    needs_review = [fid for fid, s in status.items() if s == "Needs review"]

    def detection(scope):
        rep = [c for c in case_rows if c["report"] and scope(c)]
        found = [c for c in rep if c["outcome"] == "Found"]
        w_all, w_found = sum(c["weight"] for c in rep), sum(c["weight"] for c in found)
        crit = [c for c in rep if c["expected_severity"] == "Critical"]
        return {
            "reportable": len(rep), "found": len(found), "recall": _rate(len(found), len(rep)),
            "weighted_found": w_found, "weighted_possible": w_all, "weighted_recall": _rate(w_found, w_all),
            "critical": len(crit), "critical_missed": sum(c["outcome"] == "Missed" for c in crit),
            "missed_ids": [c["case_id"] for c in rep if c["outcome"] == "Missed"],
        }

    withheld = detection(lambda c: c["set"] == "Withheld")
    reasoning = [r["reasoning"] for r in matched if r["reasoning"] is not None]
    evidence = Counter(r["evidence"] for r in matched if r["evidence"])
    real = [r["real_share"] for r in rows if r["real_share"] is not None]
    n_valid = len(valid)
    cost, minutes = info.get("cost_usd"), info.get("duration_minutes")
    return {
        "findings": len(counted), "findings_submitted": len(findings),
        "duplicates": sum(s == "Duplicate" for s in status.values()),
        "needs_review": len(needs_review), "manual_decisions": sum(r["decided"] == "manual" for r in rows),
        # headline: withheld set
        **{k: withheld[k] for k in ("reportable", "found", "recall", "weighted_found", "weighted_possible",
                                    "weighted_recall", "critical_missed")},
        "missed": withheld["missed_ids"],
        "development": detection(lambda c: c["set"] == "Development"),
        "all_cases": detection(lambda c: True),
        "withheld_clear_cases": detection(lambda c: c["set"] == "Withheld" and not c["ambiguous"]),
        "withheld_ambiguous_cases": detection(lambda c: c["set"] == "Withheld" and c["ambiguous"]),
        "precision": _rate(n_valid, len(counted)),
        "false_positives": len(fp_candidates) + len(false_alarm),
        "false_positive_candidates": fp_candidates, "false_alarms_on_negative_cases": sorted(false_alarm),
        "negative_cases": sum(not c["report"] for c in case_rows),
        "negative_cases_false_alarm": sum(c["outcome"] == "False alarm" for c in case_rows),
        "class_accuracy": _rate(sum(bool(r["class_correct"]) for r in matched), len(matched)),
        "severity_accuracy": _rate(sum(bool(r["severity_correct"]) for r in matched), len(matched)),
        "evidence_sufficient": _rate(evidence.get("Sufficient", 0), sum(evidence.values())),
        "evidence_counts": dict(evidence),
        "quotes_real": (sum(real) / len(real)) if real else None,
        "invented_citations": sum(r["invented"] for r in rows if not r.get("merged_row")),
        "reasoning_avg": (sum(reasoning) / len(reasoning)) if reasoning else None,
        "reasoning_scored": len(reasoning),
        "duration_minutes": minutes, "cost_usd": cost,
        "input_tokens": info.get("input_tokens"), "output_tokens": info.get("output_tokens"), "steps": info.get("steps"),
        "cost_per_valid_finding": _rate(cost, n_valid) if cost is not None else None,
        "minutes_per_valid_finding": _rate(minutes, n_valid) if minutes is not None else None,
        "contract_problems": len(info.get("problems", [])),
    }
