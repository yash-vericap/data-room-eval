"""How the run compares with the baseline runs on the same data room, and how that comparison is made."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import report
from eval import reality_check as rc

from .common import BAR, PCT
from .dialogs import case_dialog


def baselines(check: dict, res: dict, cmp: dict, chunks: dict, by_f: dict):
    room = check["data_room"]
    st.markdown(f"### Against the baselines on {room}")
    if not cmp["baselines"]:
        st.write(f"No baseline run is stored for {room}, so there is nothing to compare with yet. Baseline runs come "
                 f"from the Baseline Runs and Baseline Findings tabs of the evaluation sheet.")
        return
    ours = next(r for r in cmp["table"] if r["ours"])
    st.write(f"This run ranks **{cmp['rank']} of {cmp['runs']}** on {room}, next to {cmp['baselines']} baseline runs "
             f"made by other models on the same documents.")
    with st.container(border=True):
        st.markdown("**How the ranking works**")
        st.markdown(
            "- Every run, this one included, is scored the same way, with no model and no decisions by hand: a finding "
            "counts for a case when it cites the case's documents and shares its key figures and wording.\n"
            "- **Weighted recall** is points of the cases found ÷ points possible (Critical 8, High 4, Medium 2, "
            "Low 1). Unlike the accuracy there is no half credit: a case is found or not. Runs are ranked by it.\n"
            "- **Precision** is the share of a run's findings, duplicates left out, that correctly match a "
            "ground-truth case.\n"
            f"- The model's verdicts read meaning, not only words, so they can differ. Here: **{report.pct(ours['Weighted recall, all cases (rules)'])}** "
            f"by the fixed matching against **{report.pct(res['metrics']['all']['accuracy'])}** by the model's verdicts.")
    st.dataframe(pd.DataFrame(cmp["table"]).drop(columns="ours"), hide_index=True, width="stretch",
                 column_config={"Weighted recall, all cases (rules)": BAR, "Precision": PCT})

    n = cmp["baselines"]
    behind = sorted([r for r in res["cases"] if r["status"] in (rc.MISSED, rc.PARTIAL) and cmp["found_by"].get(r["case_id"])],
                    key=lambda r: (-len(cmp["found_by"][r["case_id"]]), -r["weight"]))
    ahead = sorted([r for r in res["cases"] if r["status"] in (rc.FOUND, rc.PARTIAL) and not cmp["found_by"].get(r["case_id"])],
                   key=lambda r: -r["weight"])
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Missed here, found by baselines ({len(behind)})**")
        st.caption("Other models found these on the same documents, so they are the most fixable misses.")
        _list(check, behind, cmp, chunks, by_f, lambda r: f"found by {len(cmp['found_by'][r['case_id']])} of {n}", "b")
    with right:
        st.markdown(f"**Found here, missed by every baseline ({len(ahead)})**")
        st.caption("Where this run does better than every other model.")
        _list(check, ahead, cmp, chunks, by_f, lambda r: r["status"].lower(), "a")


def _list(check: dict, rows: list[dict], cmp: dict, chunks: dict, by_f: dict, note, side: str):
    if not rows:
        st.caption("None.")
    for r in rows:
        a, b = st.columns([5, 1])
        a.markdown(f"**{r['case_id']}** · {r['severity']} · {note(r)}  \n{r['summary']}".replace("$", "\\$"))
        if b.button("Open", key=f"bl_{side}_{check['check_id']}_{r['case_id']}"):
            case_dialog(check, r, cmp, chunks, by_f)
