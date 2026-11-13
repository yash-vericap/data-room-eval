"""Runs already checked on a data room: open one again, or delete it."""
from __future__ import annotations

import streamlit as st

from eval import reality_check as rc


def _earlier(room: str):
    """Every run checked on this data room, newest first. Each JSON file is its own check, so several runs of
    one data room sit side by side; Stats compares them."""
    earlier = rc.list_checks(room)
    if not earlier:
        st.info(f"No run has been checked on {room} yet.")
        return
    pick = st.selectbox(f"Runs checked on {room} ({len(earlier)})", earlier, format_func=lambda c: f"{c['label']} · "
                        f"{(c['created_at'] or '')[:16].replace('T', ' ')} · {c['findings']} findings · {c['verdicts']} verdicts")
    b1, b2 = st.columns([1, 3])
    if b1.button("Open the check", type="primary"):
        st.session_state["rc_check"] = pick["check_id"]
    with b2.popover("Delete this check"):
        st.write(f"Deletes the check of {pick['label']} and its verdicts. Cases accepted from it stay in the answer key.")
        if st.button("Delete", key="rc_delete"):
            rc.delete_check(pick["check_id"])
            if st.session_state.get("rc_check") == pick["check_id"]:
                st.session_state.pop("rc_check")
            st.rerun()
