"""Summary: the result in a sentence, the main misses (each opens in a pop-up), the accuracy explained on a toggle,
and how the run compares with the baselines on this data room."""
from __future__ import annotations

import streamlit as st

from eval import report
from eval import reality_check as rc

from .baseline_view import baselines
from .dialogs import case_dialog
from .how import how_calculated

MAIN = 6                                           # misses shown as cards; the rest are on Comparison


def summary(check: dict, res: dict, cmp: dict, chunks: dict, by_f: dict):
    m, a = res["metrics"], res["metrics"]["all"]
    if m["stale"]:
        st.info(f"{m['stale']} verdicts are stale: their case changed after it was checked. Run the check again.")
    st.markdown(f"#### {rc.verdict_sentence(res)}")
    k = st.columns(4)
    k[0].metric("Accuracy", report.pct(a["accuracy"]), f"{a['points']:g} of {a['possible']:g} points", delta_color="off",
                help="Points earned ÷ points possible. Turn on \"Explain the accuracy\" below for the working.")
    k[1].metric("Found", a["found"], f"of {a['cases']} cases", delta_color="off")
    k[2].metric("Partially found", a["partial"], f"of {a['cases']} cases", delta_color="off")
    k[3].metric("Missed", a["missed"], f"{a['critical_missed']} Critical", delta_color="off")
    st.caption(f"Backed by documents: {report.pct(m['grounded_share'])} of the run's {m['findings']} findings. "
               f"Not in the ground truth: {len(res['new'])} findings, {m['new_real']} of them judged real issues. "
               f"Non-issues reported as problems: {m['wrongly_flagged']}.")
    if st.toggle("Explain the accuracy", key=f"how_{check['check_id']}"):
        with st.container(border=True):
            how_calculated(res)

    _main_misses(check, res, cmp, chunks, by_f)
    baselines(check, res, cmp, chunks, by_f)


def _main_misses(check: dict, res: dict, cmp: dict, chunks: dict, by_f: dict):
    misses = sorted([r for r in res["cases"] if r["status"] in (rc.MISSED, rc.PARTIAL)],
                    key=lambda r: (r["status"] != rc.MISSED, -r["weight"], r["case_id"]))
    st.markdown("### What the run missed")
    if not misses:
        st.success("The run missed nothing in the ground truth.")
        return
    lost = sum(r["weight"] - r["points"] for r in misses)
    st.caption(f"{len(misses)} cases cost {lost:g} points: missed first, then partially found, most severe first. "
               f"Open one to see the ground truth next to the run and to act on it. The full list is on Comparison.")
    cols = st.columns(2)
    for i, r in enumerate(misses[:MAIN]):
        with cols[i % 2].container(border=True):
            mark = "🔴" if r["status"] == rc.MISSED else "🟠"
            st.markdown(f"{mark} **{r['case_id']}** · {r['severity']} · {r['status']} · "
                        f"{r['weight'] - r['points']:g} points lost")
            st.write(r["summary"])
            why = r["missing"] or r["explanation"]
            if why:
                st.caption(why[:260] + ("…" if len(why) > 260 else ""))
            who = cmp["found_by"].get(r["case_id"], [])
            if cmp["baselines"]:
                st.caption(f"Found by {len(who)} of {cmp['baselines']} baseline runs.")
            if st.button("Open", key=f"open_{check['check_id']}_{r['case_id']}"):
                case_dialog(check, r, cmp, chunks, by_f)
    if len(misses) > MAIN:
        st.caption(f"And {len(misses) - MAIN} more on Comparison.")
