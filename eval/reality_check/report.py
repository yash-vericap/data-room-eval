"""The written report of one check, in Markdown."""
from __future__ import annotations

from .. import context, library
from .labels import CANDIDATE, FOUND, MISSED, PARTIAL, REJECTED_EVALUATOR, REJECTED_RULE, REVIEW, WRONG
from .results import verdict_sentence


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def markdown(check: dict, res: dict, cmp: dict | None = None, snapshot_label: str = "") -> str:
    m, a = res["metrics"], res["metrics"]["all"]
    found_by, n_base = (cmp or {}).get("found_by", {}), (cmp or {}).get("baselines", 0)
    order = lambda rows: sorted(rows, key=lambda r: -r["weight"])
    L = [f"# Vericap run check: {check['label']}", "",
         f"Data room {check['data_room']}. Answer key: {snapshot_label or check.get('snapshot') or 'not recorded'}. "
         f"Model: {check['model']} via {check['provider']}. Checked {check['created_at'][:10]}.", "",
         "## Result", "", verdict_sentence(res, check["label"]), "",
         f"- Accuracy: {_pct(a['accuracy'])} ({a['points']:g} of {a['possible']:g} points). Found earns the full weight, "
         f"partially found half.",
         f"- Found {a['found']}, partially found {a['partial']}, missed {a['missed']} of {a['cases']} cases. "
         f"Critical missed: {a['critical_missed']}.",
         f"- Withheld set: {_pct(m['withheld']['accuracy'])}. Development set: {_pct(m['development']['accuracy'])}.",
         f"- Findings: {m['findings']}. Backed by the documents: {m['grounded']}. Real issues not in the ground truth: "
         f"{m['new_real']}. Not in the documents: {m['not_in_documents']}. Not discrepancies: {m['not_a_discrepancy']}. "
         f"Known changes: {m['known_change']}. Non-issues flagged as problems: {m['wrongly_flagged']}.",
         f"- Quote check: {_pct(m['quotes_found'])} of {m['quotes_checked']} quoted passages are in their document.", ""]
    if cmp:
        L += ["## Against the baselines", "",
              f"Rank {cmp['rank']} of {cmp['runs']} runs on {check['data_room']}, by the same rules for every run. "
              f"This can differ from the accuracy above, which comes from the model's verdicts.", ""]
        L += [f"- {r['Run']} ({r['System']}): weighted recall {_pct(r['Weighted recall, all cases (rules)'])}, "
              f"{r['Cases found']} cases found, {r['Critical missed']} Critical missed, precision {_pct(r['Precision'])}, "
              f"{r['Findings']} findings" for r in cmp["table"]] + [""]

    def section(title, status, extra=False):
        rows = order([r for r in res["cases"] if r["status"] == status])
        out = [f"## {title} ({len(rows)})", ""]
        for r in rows:
            text = f"- {r['case_id']} ({r['severity']}): {r['summary']}"
            if r["finding_ids"]:
                text += f" Findings: {', '.join(r['finding_ids'])}."
            if status == PARTIAL and r["missing"]:
                text += f" Left out: {r['missing']}"
            if extra and n_base:
                text += f" Found by {len(found_by.get(r['case_id'], []))} of {n_base} baselines."
            out.append(text)
        return out + ([""] if rows else ["None.", ""])

    L += section("Missed", MISSED, True) + section("Partially found", PARTIAL, True) + section("Found", FOUND)
    open_cases = [r for r in res["cases"] + res["non_issues"] if r["status"] in (REVIEW, "Not checked")]
    if open_cases:
        L += [f"## Case verdicts still open ({len(open_cases)})", ""] + [f"- {r['case_id']}: {r['status']}. {r['explanation']}" for r in open_cases] + [""]

    cands = [n for n in res["new"] if n["band"] in (CANDIDATE, REJECTED_EVALUATOR)]
    L += [f"## Candidates for the ground truth ({len(cands) + m['accepted']})", ""]
    for p in [p for p in library.load_pending() if p.get("check_id") == check["check_id"] and p["kind"] == "case"]:
        L.append(f"- Accepted as {p['case_id']}: {p['case']['summary']} Reason: {p['reason']}")
    for n in cands:
        decision = f"Rejected by the evaluator. Reason: {n['note']}" if n["band"] == REJECTED_EVALUATOR else "Not decided yet."
        L.append(f"- {n['finding_id']} ({n['severity_judged'] or n['severity_given'] or 'no severity'}): {n['summary']} {decision}")
    L += ["" if cands or m["accepted"] else "None.", ""]
    L += [f"## Rejected by rules ({m['rejected_by_rules']})", ""]
    for rule, count in sorted(m["rejected_per_rule"].items()):
        L.append(f"### {context.rule_name(rule)} ({count})")
        L += [f"- {n['finding_id']}: {n['summary']} {n['reason']}" for n in res["new"] if n["band"] == REJECTED_RULE and (n["rule_id"] or "(no rule)") == rule]
        L.append("")
    review = [n for n in res["new"] if n["band"] in (REVIEW, "Not checked")]
    L += [f"## Needs review ({len(review)})", ""] + [f"- {n['finding_id']}: {n['summary']} {n['reason'] or n['explanation']}" for n in review] + [""]
    wrong = [r for r in res["non_issues"] if r["status"] == WRONG]
    L += [f"## Known non-issues flagged as problems ({len(wrong)})", ""]
    for r in wrong:
        rule = f" Rule broken: {', '.join(context.rule_name(x) for x in r['rule_ids'])}." if r["rule_ids"] else ""
        L.append(f"- {r['case_id']}: {r['summary']} Findings: {', '.join(r['finding_ids'])}.{rule}")
    L += ["", "## Answer key changes", ""]
    changes = [e for e in library.load_changelog() if e.get("origin") == check["check_id"]]
    L += [f"- {e['at'][:10]} {e['action']} {e['object']} {e['id']}: {e['reason']}" for e in changes] or ["None from this check."]
    if m["from_this_run"]:
        b = m["all_before"]
        L += ["", f"{m['from_this_run']} cases in the answer key came from this run. Without them the accuracy is "
                  f"{_pct(b['accuracy'])} ({b['points']:g} of {b['possible']:g} points)."]
    return "\n".join(L) + "\n"
