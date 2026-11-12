"""Writes the comparison report (Markdown) and the score table (CSV) into reports/."""
from __future__ import annotations

import csv
from datetime import datetime

from . import compare, contract, judge, scoring, store


def pct(x, digits=1):
    return "-" if x is None else f"{100 * x:.{digits}f}%"


def num(x, digits=2):
    return "-" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def score_row(res: dict) -> dict:
    m, r = res["metrics"], res["run"]
    return {
        "Run": r["run_id"], "Source": r["source"], "System": r["system"], "Version": r["version"],
        "Data room": r["data_room"], "Weighted recall": m["weighted_recall"], "Recall": m["recall"],
        "Found": m["found"], "Reportable": m["reportable"], "Critical missed": m["critical_missed"],
        "Precision": m["precision"], "False positives": m["false_positives"], "Findings": m["findings"],
        "Class accuracy": m["class_accuracy"], "Severity accuracy": m["severity_accuracy"],
        "Evidence sufficient": m["evidence_sufficient"], "Reasoning (0-2)": m["reasoning_avg"],
        "Needs review": m["needs_review"], "Minutes": m["duration_minutes"], "Cost (USD)": m["cost_usd"],
        "Contract problems": len(res["problems"]),
    }


PCT_COLS = ["Weighted recall", "Recall", "Precision", "Class accuracy", "Severity accuracy", "Evidence sufficient"]


def _table(rows: list[dict], cols: list[str]) -> str:
    def cell(row, c):
        v = row.get(c)
        if c in PCT_COLS or any(k in c.lower() for k in ("recall", "accuracy", "precision", "evidence sufficient")):
            return pct(v) if isinstance(v, (int, float)) or v is None else str(v)
        return num(v) if v is not None else "-"
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(cell(r, c).replace("|", "/") for c in cols) + " |" for r in rows]
    return "\n".join(out)


def build(results: list[dict] | None = None) -> str:
    results = scoring.score_all() if results is None else results
    cases, reviews, docs = store.load_cases(), store.load_reviews(), store.load_documents()
    L = [f"# Data room evaluation report", "", f"Generated {datetime.now():%Y-%m-%d %H:%M}. "
         f"Answer key: {cases[0]['snapshot']}, {len(cases)} cases. Runs scored: {len(results)}.", "",
         "The headline number is severity-weighted recall on the withheld set. Every run is scored with the same "
         "matching, the same metrics and the same answer key.", ""]

    L += ["## Scores per run", ""]
    rows = sorted((score_row(r) for r in results), key=lambda r: (r["Data room"], -(r["Weighted recall"] or 0)))
    L += [_table(rows, ["Run", "Source", "Data room", "Weighted recall", "Recall", "Found", "Reportable",
                        "Critical missed", "Precision", "False positives", "Class accuracy", "Severity accuracy",
                        "Evidence sufficient", "Reasoning (0-2)", "Needs review", "Minutes"]), ""]

    L += ["## Systems, averaged over repeated runs", ""]
    grp = compare.groups(results)
    rel_rows = []
    for key, g in sorted(grp.items(), key=lambda kv: (kv[0][2], -(compare.averaged(kv[1])["weighted_recall"] or 0))):
        a, rel = compare.averaged(g), compare.reliability(g)
        rel_rows.append({"System": compare.group_label(key), "Source": g[0]["run"]["source"], "Runs": len(g),
                         "Weighted recall": a["weighted_recall"],
                         "Lowest": pct(rel["weighted_recall_min"]), "Highest": pct(rel["weighted_recall_max"]),
                         "Found in every run": rel["found_every_run"], "Some runs": rel["found_some_runs"],
                         "No run": rel["found_no_run"], "Precision": a["precision"],
                         "Class accuracy": a["class_accuracy"], "Minutes": a["duration_minutes"]})
    L += [_table(rel_rows, ["System", "Source", "Runs", "Weighted recall", "Lowest", "Highest", "Found in every run",
                            "Some runs", "No run", "Precision", "Class accuracy", "Minutes"]), "",
          "Reliability needs at least two runs of the same system, version and data room. With one run, "
          "\"found in every run\" only repeats that run.", ""]

    ours = {k: g for k, g in grp.items() if g[0]["run"]["source"] == "Our system"}
    if ours:
        L += ["## Our system against the others", ""]
        for key, g in ours.items():
            for other_key, og in grp.items():
                if other_key == key or other_key[2] != key[2]:
                    continue
                c = compare.compare(g, og)
                verdict = "better" if c["improved"] else "not better"
                L += [f"**{compare.group_label(key)}** against **{compare.group_label(other_key)}**: {verdict}. "
                      f"Weighted recall {pct(c['new']['weighted_recall'])} against {pct(c['old']['weighted_recall'])}. "
                      f"Gained {len(c['gained'])} cases, lost {len(c['lost'])}"
                      + (f", including Critical cases {', '.join(c['lost_critical'])}." if c["lost_critical"] else "."), ""]
    else:
        L += ["## Our system against the others", "", "No run from our system has been submitted yet. "
              "Only baseline models are scored below.", ""]

    L += ["## Each run in detail", ""]
    for res in sorted(results, key=lambda r: (r["run"]["data_room"], r["run"]["run_id"])):
        m, r = res["metrics"], res["run"]
        L += [f"### {r['run_id']} ({r['system']}, {r['data_room']})", "",
              f"Weighted recall {pct(m['weighted_recall'])} ({m['weighted_found']} of {m['weighted_possible']} points), "
              f"recall {pct(m['recall'])} ({m['found']} of {m['reportable']} withheld cases), "
              f"precision {pct(m['precision'])}, {m['false_positives']} false positives, "
              f"{m['needs_review']} findings waiting for a manual decision.",
              f"Development set: weighted recall {pct(m['development']['weighted_recall'])} "
              f"({m['development']['found']} of {m['development']['reportable']} cases). "
              f"Withheld set without the ambiguous cases: {pct(m['withheld_clear_cases']['weighted_recall'])}.", ""]
        if res["problems"]:
            L += [f"Contract problems ({len(res['problems'])}):", ""] + [f"- {p}" for p in res["problems"][:12]] + [""]
        missed = [c for c in res["cases"] if c["outcome"] == "Missed"]
        if missed:
            L += ["Missed cases:", ""] + [f"- {c['case_id']} ({c['expected_severity']}, {c['set']}): {c['summary']}"
                                          for c in sorted(missed, key=lambda c: -c["weight"])] + [""]
        alarms = [c for c in res["cases"] if c["outcome"] == "False alarm"]
        if alarms:
            L += ["Negative cases reported as a discrepancy:", ""] + [
                f"- {c['case_id']}, expected {c['expected_class']}, reported {c['class']} in {c['finding_id']}: {c['summary']}"
                for c in alarms] + [""]
        loose = [x for x in res["rows"] if x["status"] in ("False positive candidate", "Needs review")]
        if loose:
            L += ["Findings with no confirmed case:", ""] + [f"- {x['finding_id']} ({x['status']}): {x['summary']}"
                                                              for x in loose] + [""]
        wrong = [x for x in res["rows"] if x["status"] == "Match" and x["class_correct"] is False]
        if wrong:
            L += ["Wrong class:", ""] + [f"- {x['finding_id']} on {x['case_id']}: expected {x['expected_class']}, "
                                         f"reported {x['classification']}" for x in wrong] + [""]
        L += ["Recall by severity:", "", _table(scoring.breakdown(res, "severity"),
                                                ["severity", "reportable", "found", "recall"]), ""]
        L += ["Recall by class:", "", _table(scoring.breakdown(res, "class"),
                                             ["class", "cases", "reportable", "found", "recall", "negative",
                                              "false_alarms", "class_accuracy"]), ""]

    agree = compare.matcher_agreement(store.load_runs(), cases, reviews)
    L += ["## How far the automatic matching can be trusted", ""]
    if agree["decided_by_hand"]:
        L += [f"{agree['decided_by_hand']} findings have a case chosen by hand. Run with no manual decisions, the "
              f"rule-based matcher lands on the same case for {agree['same_case']} of them ({pct(agree['agreement'])}).",
              "", _table([{"Outcome": k, "Findings": v} for k, v in sorted(agree["outcomes"].items())],
                         ["Outcome", "Findings"]), "",
              "The thresholds were set on these same findings, so this is agreement on known data, not a forecast "
              "for a new data room. Scores above use the manual decision wherever one exists.", ""]
    else:
        L += ["No manual decisions are stored yet, so the matcher has nothing to be checked against.", ""]
    verdicts = judge.load_verdicts()
    L += ["## Rules against the LLM judge", ""]
    if verdicts:
        all_runs = store.load_runs()
        t = judge.trust(all_runs, cases, reviews, verdicts)
        rows = []
        for run in all_runs:
            b = judge.score_run(run, cases, verdicts)
            if b is None:
                continue
            a = next(r for r in results if r["run"]["run_id"] == run["run"]["run_id"])
            cmp_ = judge.compare_run(run, cases, reviews, verdicts)
            rows.append({"Run": run["run"]["run_id"], "Judged": f"{cmp_['judged']}/{cmp_['findings']}",
                         "Weighted recall": a["metrics"]["weighted_recall"],
                         "Weighted recall (judge)": b["metrics"]["weighted_recall"],
                         "Precision": a["metrics"]["precision"], "Precision (judge)": b["metrics"]["precision"],
                         "Evidence sufficient (judge)": b["metrics"]["evidence_sufficient"],
                         "Reasoning (judge)": b["metrics"]["reasoning_avg"],
                         "Disagreements": sum(r["agree"] is False for r in cmp_["rows"]),
                         "For manual review": sum(r["needs_manual"] for r in cmp_["rows"])})
        L += [_table(rows, list(rows[0])), "",
              "The first score of each pair is the headline (rules plus manual decisions). The judge score is what "
              "the same run would get if the judge's verdicts were taken as they are. It never replaces the headline.", "",
              _table([
                  {"Check": "Rules and judge pick the same case", "Rate": pct(t["rules_and_judge_agree"][0]), "Findings": t["rules_and_judge_agree"][1]},
                  {"Check": "Judge picks the case chosen by hand", "Rate": pct(t["judge_matches_manual"][0]), "Findings": t["judge_matches_manual"][1]},
                  {"Check": "Rules pick the case chosen by hand, same findings", "Rate": pct(t["rules_match_manual_same_findings"][0]), "Findings": t["rules_match_manual_same_findings"][1]},
                  {"Check": "Judge gives the evidence check given by hand", "Rate": pct(t["evidence_matches_manual"][0]), "Findings": t["evidence_matches_manual"][1]},
                  {"Check": "Judge gives the reasoning score given by hand", "Rate": pct(t["reasoning_matches_manual"][0]), "Findings": t["reasoning_matches_manual"][1]},
              ], ["Check", "Rate", "Findings"]), "",
              f"Where rules and judge differed and a manual decision exists, the judge alone was right {t['only_judge_right']} "
              f"times and the rules alone {t['only_rules_right']} times. {t['unstable']} verdicts changed between the two "
              f"passes. {t['needs_manual']} findings were sent to manual review by the judge's own safeguards.", ""]
    else:
        L += ["The judge has not been run yet. Run: python -m eval judge", ""]
    L += ["## What is not measured here", "",
          "- Quotes are checked against the documents only for data rooms whose text is stored in data_room/. "
          "A quote marked not found is either invented or reworded, and needs a look.",
          "- Reasoning scores in the headline come from manual review. The judge's scores are shown beside them.", ""]
    return "\n".join(L)


def write(results: list[dict] | None = None) -> tuple[str, str]:
    results = scoring.score_all() if results is None else results
    store.REPORTS.mkdir(exist_ok=True)
    md = store.REPORTS / "report.md"
    md.write_text(build(results), encoding="utf-8")
    rows = [score_row(r) for r in results]
    path = store.REPORTS / "scores.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["Run"])
        w.writeheader()
        w.writerows(rows)
    return str(md), str(path)
