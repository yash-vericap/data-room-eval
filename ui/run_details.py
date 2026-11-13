"""Run details: every finding in the run and where it went. Select a row to open it, with its case or its review."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import context
from eval import reality_check as rc

from .common import MARK
from .dialogs import finding_dialog

IN_GT, NON, OUTSIDE = "Matches a ground-truth case", "Matches a non-issue", "Not in the ground truth"


def _rows(check: dict, res: dict) -> list[dict]:
    by_case = {}
    for r in res["cases"] + res["non_issues"]:
        for fid in r["finding_ids"]:
            by_case.setdefault(fid, []).append(r)
    new = {n["finding_id"]: n for n in res["new"]}
    out = []
    for f in check["findings"]:
        fid, cases = f["finding_id"], by_case.get(f["finding_id"], [])
        if cases:
            group = IN_GT if any(r["report"] for r in cases) else NON
            went = ", ".join(f"{MARK[r['status']]} {r['case_id']} · {r['status']}" for r in cases)
        else:
            n = new.get(fid) or {"band": "Not checked", "status": "Not checked", "rule_id": None}
            group = OUTSIDE
            went = n["band"] + (f" · {context.rule_name(n['rule_id'])}" if n["band"] == rc.REJECTED_RULE and n["rule_id"]
                                else f" · {n['status']}" if n["status"] != n["band"] else "")
        out.append({"Finding": fid, "Severity": f["severity"] or f["raw_severity"] or "", "Class": f["classification"] or "",
                    "Summary": f["summary"], "Where it went": went, "Group": group})
    return out


def run_details(check: dict, res: dict, cmp: dict, chunks: dict, by_f: dict):
    rows = _rows(check, res)
    counts = {g: sum(r["Group"] == g for r in rows) for g in (IN_GT, NON, OUTSIDE)}
    st.caption(f"Every one of the run's {len(rows)} findings and where it went: {counts[IN_GT]} match a ground-truth case, "
               f"{counts[NON]} a non-issue, {counts[OUTSIDE]} nothing in the ground truth. Select a row to open the "
               f"finding next to its case, or to review it.")
    f1, f2, f3 = st.columns([2, 1, 2])
    groups = f1.multiselect("Where it went", list(counts), default=list(counts), format_func=lambda g: f"{g} ({counts[g]})")
    sevs = sorted({r["Severity"] for r in rows})
    pick_sev = f2.multiselect("Severity", sevs, default=sevs)
    text = f3.text_input("Search", placeholder="A word, a figure, a finding ID")
    shown = [r for r in rows if r["Group"] in groups and r["Severity"] in pick_sev
             and (not text or text.lower() in " ".join(map(str, r.values())).lower())]
    if not shown:
        st.info("No finding matches these filters.")
        return
    n = st.session_state.get(f"rd_n_{check['check_id']}", 0)      # a fresh table after each pop-up, so it opens once
    event = st.dataframe(pd.DataFrame(shown).drop(columns="Group"), hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row", key=f"rd_{check['check_id']}_{n}",
                         column_config={"Summary": st.column_config.TextColumn(width="large")})
    picked = event.selection.rows if event is not None and hasattr(event, "selection") else []
    if picked and picked[0] < len(shown):
        st.session_state[f"rd_n_{check['check_id']}"] = n + 1
        finding_dialog(check, shown[picked[0]]["Finding"], res, cmp, chunks, by_f)
