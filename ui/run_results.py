"""The result of a check in four tabs: Summary, Comparison, Run details, Report and audit.
Any case or finding opens in a pop-up with its resolution inside."""
from __future__ import annotations

import streamlit as st

from eval import store

from .state import results_of
from .comparison import comparison
from .compare import CSS
from .run_audit import report_and_audit
from .run_details import run_details
from .summary import summary


def show_results(check: dict):
    res, cmp = results_of(check)                      # cached until the check or the data changes
    chunks = store.load_chunks(check["data_room"])
    by_f = {f["finding_id"]: f for f in check["findings"]}
    st.markdown(CSS, unsafe_allow_html=True)
    st.subheader("Result")
    t_sum, t_cmp, t_run, t_out = st.tabs(["Summary", f"Comparison ({len(res['cases']) + len(res['non_issues'])} cases)",
                                          f"Run details ({len(check['findings'])} findings)", "Report and audit"])
    with t_sum:
        summary(check, res, cmp, chunks, by_f)
    with t_cmp:
        comparison(check, res, cmp, chunks, by_f)
    with t_run:
        run_details(check, res, cmp, chunks, by_f)
    with t_out:
        report_and_audit(check, res, cmp)
