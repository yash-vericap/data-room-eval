"""Runs of one data room side by side: how stable each case is, and what changed between two runs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import stats

from .common import MARK

PATTERN = {"Found every time": "🟢 Found every time", "Found sometimes": "🟠 Found sometimes", "Never found": "🔴 Never found"}
CHANGE = {"Gained": "🟢 Gained", "Better": "🟢 Better", "Lost": "🔴 Lost", "Worse": "🔴 Worse", "Changed": "⚪ Changed", "Same": "Same"}


def stability(runs: list[tuple[dict, dict]]):
    st.markdown("##### How stable each case is")
    if len(runs) < 2:
        st.info("Check a second run of this data room to see which cases every run finds and which it finds only sometimes.")
        return
    rows = stats.stability(runs)
    counts = pd.Series([r["Pattern"] for r in rows]).value_counts()
    k = st.columns(3)
    for col, key in zip(k, ["Found every time", "Found sometimes", "Never found"]):
        col.metric(key, int(counts.get(key, 0)), "reportable cases", delta_color="off")
    st.caption(f"One row per reportable case, with its verdict in each of the {len(runs)} runs. \"Found in\" counts full "
               f"finds only. Cases no run finds come first: they are where the system is blind.")
    show = st.multiselect("Show", list(PATTERN), default=["Never found", "Found sometimes"], key="st_pattern")
    table = [{**r, "Pattern": PATTERN[r["Pattern"]],
              **{c["label"]: f"{MARK.get(r.get(c['label']), '')} {r.get(c['label'], '-')}" for c, _ in runs}}
             for r in rows if r["Pattern"] in show]
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")


def compare_two(runs: list[tuple[dict, dict]]):
    st.markdown("##### Two runs side by side")
    if len(runs) < 2:
        return
    labels = [c["label"] for c, _ in runs]
    c1, c2 = st.columns(2)
    a = c1.selectbox("Earlier run", labels, index=len(labels) - 2, key="st_a")
    b = c2.selectbox("Later run", labels, index=len(labels) - 1, key="st_b")
    if a == b:
        st.info("Pick two different runs.")
        return
    by = {c["label"]: (c, r) for c, r in runs}
    rows = stats.compare(by[a], by[b])
    counts = pd.Series([r["Change"] for r in rows]).value_counts()
    k = st.columns(5)
    for col, key in zip(k, ["Gained", "Better", "Lost", "Worse", "Same"]):
        col.metric(key, int(counts.get(key, 0)))
    ra, rb = by[a][1]["metrics"]["all"], by[b][1]["metrics"]["all"]
    st.caption(f"Accuracy {_pct(ra['accuracy'])} → {_pct(rb['accuracy'])}. Gained: missed before, found now. Better: from "
               f"missed to partly found, or partly to fully found. Lost and Worse are the reverse.")
    changed = [{**r, "Change": CHANGE[r["Change"]]} for r in rows if r["Change"] != "Same"]
    if changed:
        st.dataframe(pd.DataFrame(changed), hide_index=True, width="stretch")
    else:
        st.write("Every case has the same verdict in both runs.")


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"
