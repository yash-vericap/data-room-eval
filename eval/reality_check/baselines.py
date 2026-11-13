"""The run next to the baseline models, all scored by the same fixed rules; and what was sent to the model."""
from __future__ import annotations

from .. import contract, scoring, store


def as_contract_run(check: dict) -> dict:
    """The run in the output contract format, so the rule-based scorer and the other screens can read it."""
    meta = check.get("run_meta") or {}
    return {
        "run": {"run_id": check["label"], "data_room": check["data_room"], "source": "Our system",
                "system": str(meta.get("system") or "Vericap"), "version": str(meta.get("version") or ""),
                "model": str(meta.get("model") or ""), "notes": f"Read by the Vericap run check ({check['check_id']})."},
        "findings": [{"finding_id": f["finding_id"], "classification": f["classification"], "severity": f["severity"],
                      "summary": f["summary"], "claims_compared": f["claims_compared"],
                      "citations": [{"doc_id": c["doc_id"], "page": c["page"], "location": c["location"], "quote": c["quote"]}
                                    for c in f["citations"]],
                      "explanation": f["explanation"], "confidence": f["confidence"]} for f in check["findings"]],
    }


def baseline_comparison(check: dict, scored_runs: list[dict], cases: list[dict] | None = None) -> dict:
    """The run next to every baseline on the same data room, all scored by the same rules with no manual
    decisions for our run. Returns {"table", "rank", "runs", "baselines", "found_by", "baseline_ids"}."""
    cases = store.load_cases() if cases is None else cases
    run, problems = contract.normalise(as_contract_run(check))
    run["run"]["problems"] = problems
    ours = scoring.score_run(run, cases, {})
    base = [r for r in scored_runs if r["run"]["data_room"] == check["data_room"] and r["run"]["source"] == "Baseline model"]

    def row(res, mine=False):
        m, a = res["metrics"], res["metrics"]["all_cases"]
        return {"Run": res["run"]["run_id"], "System": "Vericap (this run)" if mine else res["run"]["system"],
                "Weighted recall, all cases (rules)": a["weighted_recall"], "Cases found": a["found"],
                "Critical missed": a["critical_missed"], "Precision": m["precision"], "Findings": m["findings"], "ours": mine}

    table = sorted([row(ours, True)] + [row(r) for r in base],
                   key=lambda r: -(r["Weighted recall, all cases (rules)"] or 0))
    found_by: dict[str, list[str]] = {}
    for r in base:
        for c in r["cases"]:
            if c["report"] and c["outcome"] == "Found":
                found_by.setdefault(c["case_id"], []).append(r["run"]["run_id"])
    return {"table": table, "rank": next(i for i, r in enumerate(table, start=1) if r["ours"]), "runs": len(table),
            "baselines": len(base), "found_by": found_by, "baseline_ids": [r["run"]["run_id"] for r in base]}


def pages_sent(check: dict) -> list[dict]:
    """What left the machine: every document page sent to the model, with the provider and model."""
    seen: dict[tuple, dict] = {}
    for kind, bucket in (("case", check["case_verdicts"]), ("finding", check["new_verdicts"])):
        for key, v in bucket.items():
            s = v.get("sent") or {}
            for doc, page in s.get("pages") or []:
                row = seen.setdefault((doc, page, s.get("provider"), s.get("model")),
                                      {"doc_id": doc, "page": page, "provider": s.get("provider"), "model": s.get("model"),
                                       "calls": 0, "last_sent": s.get("at")})
                row["calls"] += 1
                row["last_sent"] = max(row["last_sent"] or "", s.get("at") or "")
    return sorted(seen.values(), key=lambda r: (r["doc_id"], r["page"] if r["page"] is not None else -1))
