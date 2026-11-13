"""The Stats screen: how every checked Vericap run did, alone and next to the other runs of its data room."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import stats

from .common import BAR, PCT, page_header
from .state import S, checked_runs
from .stats_more import breakdowns, findings_and_models, inventory
from .stats_runs import compare_two, stability


def screen_stats():
    page_header("Stats", "How every checked Vericap run did. Pick a data room to compare its runs with each other: "
                         "which cases every run finds, which none finds, and what changed between two runs.", room_filter=True)
    runs = checked_runs(None if S.room == "All" else S.room)
    if not runs:
        st.info("No run has been checked yet" + ("" if S.room == "All" else f" on {S.room}") + ". Check one on the Vericap run "
                "check screen and its numbers appear here.")
        inventory()
        return
    labels = [c["label"] for c, _ in runs]
    chosen = st.multiselect("Runs", labels, default=labels, help="Leave out a run to see the others without it.")
    runs = [(c, r) for c, r in runs if c["label"] in chosen]
    if not runs:
        st.warning("Pick at least one run.")
        return
    rows = [stats.run_row(c, r) for c, r in runs]
    _headline(rows)
    t_runs, t_cases, t_parts, t_data = st.tabs(["Runs", "Cases across runs", "Breakdowns", "Data rooms and answer key"])
    with t_runs:
        _runs(rows)
    with t_cases:
        if S.room == "All":
            st.info("Pick one data room at the top to compare its runs case by case.")
        else:
            stability(runs)
            compare_two(runs)
    with t_parts:
        breakdowns(runs)
        findings_and_models(runs)
    with t_data:
        inventory()


def _headline(rows: list[dict]):
    latest = rows[-1]
    same_room = [r for r in rows if r["Data room"] == latest["Data room"]]
    prev = same_room[-2] if len(same_room) > 1 else None
    acc = [r["Accuracy"] for r in rows if r["Accuracy"] is not None]
    k = st.columns(6)
    k[0].metric("Runs checked", len(rows))
    k[1].metric("Latest accuracy", _pct(latest["Accuracy"]), help=f"{latest['Run']} on {latest['Data room']}.",
                delta=(f"{100 * (latest['Accuracy'] - prev['Accuracy']):+.1f} points on the run before"
                       if prev and latest["Accuracy"] is not None and prev["Accuracy"] is not None else None))
    k[2].metric("Average accuracy", _pct(sum(acc) / len(acc) if acc else None), f"{_pct(min(acc) if acc else None)} to "
                f"{_pct(max(acc) if acc else None)}", delta_color="off")
    k[3].metric("Critical missed, latest run", latest["Critical missed"])
    k[4].metric("Backed by documents", _pct(_avg(rows, "Backed by documents")), "average share of findings", delta_color="off")
    noise = sum(r["Rejected by rules"] for r in rows) / max(1, sum(r["Findings"] for r in rows))
    k[5].metric("Filtered out by rules", _pct(noise), "of all findings; never reaches a reviewer", delta_color="off")


def _runs(rows: list[dict]):
    st.caption("One row per run, oldest first. Accuracy: a found case earns its weight (Critical 8, High 4, Medium 2, "
               "Low 1), a partially found case half. Withheld: the same on the withheld cases only.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Accuracy": BAR, "Withheld": PCT, "Backed by documents": PCT})
    if len(rows) > 1:
        st.markdown("##### Accuracy by run")
        chart = pd.DataFrame({"Run": [f"{i}. {r['Run']}" for i, r in enumerate(rows, start=1)],
                              "Accuracy (%)": [round(100 * (r["Accuracy"] or 0), 1) for r in rows]}).set_index("Run")
        st.bar_chart(chart, y="Accuracy (%)", height=260)
        st.caption("Runs in the order they were checked. The table above holds the same numbers.")


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def _avg(rows: list[dict], key: str):
    vals = [r[key] for r in rows if r[key] is not None]
    return sum(vals) / len(vals) if vals else None
