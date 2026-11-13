"""Stats breakdowns: by severity and class, where findings went, rules, models and tokens, and what is stored."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import context, contract, stats

from .common import BAR, PCT
from .rooms import _room_rows
from .state import S


def breakdowns(runs: list[tuple[dict, dict]]):
    st.markdown("##### Found, by severity and by class")
    st.caption("Shares of case verdicts over the selected runs. A gap at Critical matters most.")
    c1, c2 = st.columns(2)
    cfg = {"Found": BAR, "Partially found": PCT, "Missed": PCT}
    c1.dataframe(pd.DataFrame(stats.by_dimension(runs, S.cases, "severity")), hide_index=True, width="stretch", column_config=cfg)
    c2.dataframe(pd.DataFrame(stats.by_dimension(runs, S.cases, "class")), hide_index=True, width="stretch", column_config=cfg)


def findings_and_models(runs: list[tuple[dict, dict]]):
    st.markdown("##### Where the findings went")
    flow = stats.finding_flow(runs)
    if flow:
        st.dataframe(pd.DataFrame(flow).pivot_table(index="Class given", columns="Went to", values="Findings", fill_value=0,
                                                    aggfunc="sum"), width="stretch")
    c1, c2 = st.columns(2)
    rules = stats.rule_rejections(runs)
    c1.markdown("##### Rejected by rules")
    c1.caption("Findings outside the ground truth that a rule excludes. A reviewer never sees them.")
    c1.dataframe(pd.DataFrame([{"Rule": context.rule_name(r), "Findings": n} for r, n in sorted(rules.items())])
                 if rules else pd.DataFrame(columns=["Rule", "Findings"]), hide_index=True, width="stretch")
    c2.markdown("##### Models and tokens")
    used = stats.models(runs)
    c2.dataframe(pd.DataFrame([{"Model": m, "Verdicts": n} for m, n in sorted(used.items(), key=lambda kv: -kv[1])]),
                 hide_index=True, width="stretch")
    tin = sum(c.get("input_tokens") or 0 for c, _ in runs)
    tout = sum(c.get("output_tokens") or 0 for c, _ in runs)
    c2.caption(f"{tin:,} tokens sent and {tout:,} received over the selected runs.")


def inventory():
    """What is stored: data rooms, the answer key's cases, and the baseline runs."""
    pick = [r for r in S.rooms if S.room in ("All", r)]
    st.markdown("##### Data rooms")
    st.dataframe(pd.DataFrame([r for r in _room_rows() if r["Data room"] in pick]), hide_index=True, width="stretch")
    lib = [c for c in S.cases if c["data_room"] in pick]
    st.markdown(f"##### Answer key: {len(lib)} cases")
    if lib:
        c1, c2 = st.columns(2)
        c1.caption("Cases by class and severity. A zero is a gap in the map.")
        c1.dataframe(pd.crosstab(pd.Series([c["classification"] for c in lib], name="Class"),
                                 pd.Series([c["severity"] for c in lib], name="Severity")).reindex(
            index=contract.CLASSES, columns=contract.SEVERITIES, fill_value=0), width="stretch")
        c2.caption("Cases by data room and set.")
        c2.dataframe(pd.crosstab(pd.Series([c["data_room"] for c in lib], name="Data room"),
                                 pd.Series([f"{c['set']}, {'report' if c['report'] else 'do not report'}" for c in lib], name="")),
                     width="stretch")
    base = [r for r in S.results if r["run"]["source"] == "Baseline model" and r["run"]["data_room"] in pick]
    if base:
        st.markdown(f"##### Baseline runs: {len(base)}")
        st.caption("General models on the same data rooms, scored by the fixed rules. The run check ranks each run against these.")
        st.dataframe(pd.DataFrame([{"Run": r["run"]["run_id"], "System": r["run"]["system"], "Data room": r["run"]["data_room"],
                                    "Weighted recall, all cases": r["metrics"]["all_cases"]["weighted_recall"],
                                    "Cases found": r["metrics"]["all_cases"]["found"], "Precision": r["metrics"]["precision"]}
                                   for r in base]).sort_values(["Data room", "Weighted recall, all cases"], ascending=[True, False]),
                     hide_index=True, width="stretch", column_config={"Weighted recall, all cases": BAR, "Precision": PCT})
