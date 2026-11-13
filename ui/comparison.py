"""Comparison: every ground-truth case next to what the run said, grouped by verdict, any groups at once."""
from __future__ import annotations

import streamlit as st

from eval import reality_check as rc

from .case_detail import case_list

MISSED, PARTIAL, FOUND, MISC = "🔴 Missed", "🟠 Partially found", "🟢 Found", "Miscellaneous"


def groups(res: dict) -> dict[str, list[dict]]:
    rows = res["cases"]
    return {MISSED: [r for r in rows if r["status"] in (rc.MISSED, rc.REVIEW, "Not checked")],
            PARTIAL: [r for r in rows if r["status"] == rc.PARTIAL],
            FOUND: [r for r in rows if r["status"] == rc.FOUND]}


def comparison(check: dict, res: dict, cmp: dict, chunks: dict, by_f: dict):
    g = groups(res)
    non = res["non_issues"]
    counts = {**{k: len(v) for k, v in g.items()}, MISC: len(non)}
    st.caption("Each ground-truth case next to what the run said about it. Pick one group or several; open a case to "
               "read the two side by side and act on its verdict.")
    picked = st.segmented_control("Show", list(counts), selection_mode="multi", default=list(counts),
                                  format_func=lambda k: f"{k} ({counts[k]})", key=f"cmp_show_{check['check_id']}")
    if not picked:
        st.info("Pick at least one group above.")
    about = {MISSED: "Cases the run did not report, or that are not decided yet. Fix these first.",
             PARTIAL: "The run reported these, but left out or got wrong an essential part.",
             FOUND: "The run reported these with their essential facts."}
    for k in (MISSED, PARTIAL, FOUND):
        if k in picked:
            st.markdown(f"#### {k} ({counts[k]})")
            st.caption(about[k])
            case_list(check, g[k], cmp, chunks, by_f, "None.")
    if MISC in picked:
        _misc(check, non, cmp, chunks, by_f)


def _misc(check: dict, non: list[dict], cmp: dict, chunks: dict, by_f: dict):
    st.markdown(f"#### {MISC} ({len(non)})")
    st.caption("Non-issues: things in the ground truth that look like problems but are not, for example a recorded "
               "change. They are not part of the accuracy.")
    said = [r for r in non if r["finding_ids"]]
    silent = [r for r in non if not r["finding_ids"]]
    wrong = sum(r["status"] == rc.WRONG for r in said)
    st.markdown(f"**The run mentions them ({len(said)})**" + (f" · 🔴 {wrong} reported as a problem" if wrong else ""))
    st.caption("A finding in the run is about each of these. Right if it explains it is not a problem; wrong if it "
               "reports it as one.")
    case_list(check, said, cmp, chunks, by_f, "The run mentions none of them.")
    st.markdown(f"**The run says nothing about them ({len(silent)})**")
    st.caption("No finding is about these, which is the right outcome for a non-issue.")
    case_list(check, silent, cmp, chunks, by_f, "None.")
