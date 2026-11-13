"""The Vericap run check screen: the steps, then the result in tabs."""
from __future__ import annotations

import streamlit as st

from eval import reality_check as rc

from .state import S
from .common import page_header
from .run_results import show_results
from .run_steps import _step1, _step2
from .run_step3 import _step3


def screen_run_check():
    page_header("Vericap run check",
                "Give one run of our system. The tool reads it, checks every ground-truth case against it, checks every "
                "other finding against the documents, and ranks the run against the baselines.")
    _step1()
    check = rc.load_check(st.session_state["rc_check"]) if st.session_state.get("rc_check") else None
    if check is None:
        st.info("**How it works.** 1. Pick the data room and paste or upload the run. 2. Check what was read. "
                "3. Run the check. The result shows what was found, partly found and missed, what the run reported "
                "that the ground truth does not have, and the rank against the baselines.")
        return
    if check["data_room"] not in S.rooms:
        st.error(f"This check is for data room {check['data_room']}, which is not in the list any more.")
        return

    _step2(check)
    _step3(check)
    check = rc.load_check(check["check_id"])
    if not check["case_verdicts"] and not check["new_verdicts"] and not check["manual"]:
        return
    show_results(check)
