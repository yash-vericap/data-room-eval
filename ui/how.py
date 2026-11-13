"""How every number in the summary is worked out, written with this run's own numbers."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import contract, report
from eval import reality_check as rc


def _points_table(rows: list[dict]) -> pd.DataFrame:
    out = []
    for sev in contract.SEVERITIES:
        mine = [r for r in rows if r["severity"] == sev]
        if not mine:
            continue
        out.append({"Severity": sev, "Points per case": contract.WEIGHTS[sev], "Cases": len(mine),
                    "Found (full points)": sum(r["status"] == rc.FOUND for r in mine),
                    "Partially found (half)": sum(r["status"] == rc.PARTIAL for r in mine),
                    "Missed (0)": sum(r["status"] == rc.MISSED for r in mine),
                    "Not decided (0)": sum(r["status"] in (rc.REVIEW, "Not checked") for r in mine),
                    "Points earned": sum(r["points"] for r in mine), "Points possible": sum(r["weight"] for r in mine)})
    if out:
        total = {k: sum(o[k] for o in out) for k in out[0] if k not in ("Severity", "Points per case")}
        out.append({"Severity": "Total", "Points per case": None, **total})
    return pd.DataFrame(out)


def how_calculated(res: dict):
    m, a, rows, non = res["metrics"], res["metrics"]["all"], res["cases"], res["non_issues"]
    full = sum(r["points"] for r in rows if r["status"] == rc.FOUND)
    half = sum(r["points"] for r in rows if r["status"] == rc.PARTIAL)
    by_model = sum(not r["manual"] and not r.get("by_rule") and r["status"] not in ("Not checked",) for r in rows + non)
    by_rule = sum(bool(r.get("by_rule")) for r in rows + non)
    by_hand = sum(r["manual"] for r in rows + non)
    linked = m["grounded"] - m["new_real"]

    st.markdown("#### How these numbers are calculated")
    st.markdown(
        f"**1. Every ground-truth case gets one verdict.** The ground truth for this data room has {a['cases']} cases "
        f"the run should report and {len(non)} non-issues it should leave alone. For each case the run's related "
        f"findings are compared with it:\n"
        f"- **Found**: a finding states the same problem with its essential facts (the figures, dates and documents).\n"
        f"- **Partially found**: a finding is about the problem but leaves out or gets wrong an essential part.\n"
        f"- **Missed**: no finding is about the problem.\n\n"
        f"Who decided: the model {by_model}, a rule {by_rule} (no finding was related, so the case is missed "
        f"without asking a model), by hand {by_hand}.")
    st.markdown("**2. Each case is worth points by its severity**: Critical 8, High 4, Medium 2, Low 1. "
                "A found case earns all its points, a partially found case half, a missed case none.")
    st.dataframe(_points_table(rows), hide_index=True, width="stretch")
    st.markdown(
        f"**3. Accuracy = points earned ÷ points possible.** Found cases {full:g} + partially found cases {half:g} "
        f"= **{a['points']:g} of {a['possible']:g} points = {report.pct(a['accuracy'])}**. So missing one Critical case "
        f"costs as much as missing eight Low ones.")
    st.markdown(
        f"**4. Found, Partially found and Missed are counts of cases**, not points: {a['found']} + {a['partial']} + "
        f"{a['missed']}" + (f" + {a['open']} not decided" if a["open"] else "") + f" = {a['cases']} cases.")
    st.markdown(
        f"**5. Non-issues are not in the accuracy.** Of {len(non)}, the run wrongly reported {m['wrongly_flagged']} "
        f"as problems. These are under Miscellaneous on the Comparison tab.")
    st.markdown(
        f"**6. Backed by documents = findings that hold up ÷ all findings.** {linked} findings are linked to a found or "
        f"partially found case, plus {m['new_real']} unlinked findings the model judged a real issue in the documents: "
        f"{m['grounded']} of {m['findings']} = {report.pct(m['grounded_share'])}.")
    st.markdown(
        f"**7. Newly found** = findings linked to no case that the model judged a real issue in the documents "
        f"({m['new_real']}). {m['candidates']} of them passed the rules and wait for your decision; "
        f"{m['rejected_by_rules']} findings were set aside by a context rule.")
    st.markdown(
        f"**8. Quote check**: each quoted passage is looked up word for word on its cited page. "
        f"{report.pct(m['quotes_found'])} of {m['quotes_checked']} quotes were found there.")
    st.markdown(
        f"**9. Withheld and development sets** use the same formula on their own cases: withheld "
        f"{report.pct(m['withheld']['accuracy'])}, development {report.pct(m['development']['accuracy'])}. "
        f"Withheld cases were never used to tune the system, so they are the fairer measure.")
