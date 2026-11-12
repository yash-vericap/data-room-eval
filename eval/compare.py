"""Comparisons across runs: repeated runs of one system, one system against another, and the
automatic matcher against the manual decisions."""
from __future__ import annotations

from collections import defaultdict

from . import matching


def group_key(result: dict) -> tuple[str, str, str]:
    r = result["run"]
    return (r.get("system") or r["run_id"], r.get("version") or "", r["data_room"])


def group_label(key: tuple[str, str, str]) -> str:
    system, version, room = key
    return f"{system} {version}".strip() + f" · {room}"


def groups(results: list[dict]) -> dict[tuple, list[dict]]:
    out = defaultdict(list)
    for res in results:
        out[group_key(res)].append(res)
    return dict(out)


def reliability(group: list[dict]) -> dict:
    """Stability of one system across its repeated runs on one data room."""
    n = len(group)
    hits = defaultdict(int)
    meta = {}
    for res in group:
        for c in res["cases"]:
            if c["report"]:
                meta[c["case_id"]] = c
                hits[c["case_id"]] += c["outcome"] == "Found"
    rows = [{"case_id": cid, "severity": meta[cid]["expected_severity"], "set": meta[cid]["set"],
             "summary": meta[cid]["summary"], "found_in": hits[cid], "runs": n,
             "stability": "Every run" if hits[cid] == n else ("No run" if hits[cid] == 0 else "Some runs")}
            for cid in sorted(meta)]
    recalls = [res["metrics"]["weighted_recall"] for res in group if res["metrics"]["weighted_recall"] is not None]
    withheld = [r for r in rows if r["set"] == "Withheld"]
    return {
        "runs": n, "run_ids": [res["run"]["run_id"] for res in group], "cases": rows,
        "found_every_run": sum(r["stability"] == "Every run" for r in withheld),
        "found_some_runs": sum(r["stability"] == "Some runs" for r in withheld),
        "found_no_run": sum(r["stability"] == "No run" for r in withheld),
        "stable_share": (sum(r["stability"] == "Every run" for r in withheld) / len(withheld)) if withheld else None,
        "weighted_recall_min": min(recalls) if recalls else None,
        "weighted_recall_max": max(recalls) if recalls else None,
        "weighted_recall_avg": (sum(recalls) / len(recalls)) if recalls else None,
    }


def averaged(group: list[dict]) -> dict:
    """Metrics averaged over the repeated runs of one system."""
    keys = ["weighted_recall", "recall", "precision", "class_accuracy", "severity_accuracy", "evidence_sufficient",
            "reasoning_avg", "false_positives", "critical_missed", "findings", "duration_minutes", "cost_usd",
            "cost_per_valid_finding", "minutes_per_valid_finding", "needs_review", "invented_citations"]
    out = {"runs": len(group)}
    for k in keys:
        vals = [res["metrics"][k] for res in group if res["metrics"].get(k) is not None]
        out[k] = (sum(vals) / len(vals)) if vals else None
    return out


def _found_any(group: list[dict]) -> dict[str, dict]:
    """Per reportable case: found in at least one run of the group, and in how many."""
    out = {}
    for res in group:
        for c in res["cases"]:
            if not c["report"]:
                continue
            d = out.setdefault(c["case_id"], {**c, "found_in": 0, "runs": 0})
            d["runs"] += 1
            d["found_in"] += c["outcome"] == "Found"
    return out


def compare(new: list[dict], old: list[dict]) -> dict:
    """Case-by-case comparison of two systems (each a list of repeated runs) on the same data room.

    A case counts as found by a system when it is found in more than half of its runs.
    'improved' follows the methodology: weighted recall on the withheld set rises, and no Critical
    case the old system found is now missed.
    """
    a, b = _found_any(new), _found_any(old)

    def found(d, cid):
        return cid in d and d[cid]["found_in"] * 2 > d[cid]["runs"]

    rows = []
    for cid in sorted(set(a) | set(b)):
        c = a.get(cid) or b[cid]
        fa, fb = found(a, cid), found(b, cid)
        change = "Gained" if fa and not fb else "Lost" if fb and not fa else "Both found" if fa else "Both missed"
        rows.append({"case_id": cid, "severity": c["expected_severity"], "set": c["set"], "summary": c["summary"],
                     "new": f"{a[cid]['found_in']}/{a[cid]['runs']}" if cid in a else "-",
                     "old": f"{b[cid]['found_in']}/{b[cid]['runs']}" if cid in b else "-", "change": change})
    ma, mb = averaged(new), averaged(old)
    lost_critical = [r["case_id"] for r in rows if r["change"] == "Lost" and r["severity"] == "Critical"]
    wr_a, wr_b = ma["weighted_recall"], mb["weighted_recall"]
    improved = wr_a is not None and wr_b is not None and wr_a > wr_b and not lost_critical
    return {"cases": rows, "new": ma, "old": mb, "lost_critical": lost_critical, "improved": improved,
            "gained": [r["case_id"] for r in rows if r["change"] == "Gained"],
            "lost": [r["case_id"] for r in rows if r["change"] == "Lost"]}


def matcher_agreement(runs: list[dict], cases: list[dict], reviews: dict) -> dict:
    """How often the rule-based matcher, run with no manual decisions, lands on the case the
    evaluator chose by hand. This is the check on the matcher itself."""
    total = same = 0
    outcomes = defaultdict(int)
    disagreements = []
    for run in runs:
        rid = run["run"]["run_id"]
        room_cases = [c for c in cases if c["data_room"] == run["run"]["data_room"]]
        auto = defaultdict(list)
        for row in matching.match_run(run["findings"], room_cases, {}, rid):
            auto[row["finding_id"]].append(row)
        for f in run["findings"]:
            rv = reviews.get(f"{rid}::{f['finding_id']}")
            if not rv:
                continue
            rows = auto[f["finding_id"]]
            auto_status = rows[0]["status"]
            auto_cases = {r["case_id"] for r in rows if r["status"] in ("Match", "Duplicate") and r["case_id"]}
            manual_cases = set(rv.get("case_ids") or [])
            if rv["status"] in ("Match", "Duplicate") and manual_cases:
                total += 1
                ok = bool(auto_cases & manual_cases) and (auto_cases <= manual_cases or manual_cases <= auto_cases)
                same += ok
                kind = "Same case" if ok else ("Sent to review" if auto_status == "Needs review" else
                                               "No case found" if not auto_cases else "Different case")
                outcomes[kind] += 1
                if not ok:
                    disagreements.append({"run_id": rid, "finding_id": f["finding_id"], "manual": sorted(manual_cases),
                                          "rules": sorted(auto_cases), "rules_status": auto_status,
                                          "best_score": rows[0]["candidates"][0]["score"] if rows[0]["candidates"] else None})
            else:
                outcomes[f"Manual '{rv['status']}', rules '{auto_status}'"] += 1
    return {"decided_by_hand": total, "same_case": same, "agreement": (same / total) if total else None,
            "outcomes": dict(outcomes), "disagreements": disagreements}
