"""The pop-ups. A case or a finding opens in one from any tab, with its resolution inside, so nothing needs a jump."""
from __future__ import annotations

import streamlit as st

from eval import context
from eval import reality_check as rc

from .candidate import candidate_review
from .common import MARK, check_finding_card
from .forms import correction_form, restore_form, verdict_form


@st.dialog("Change the verdict", width="large")
def verdict_dialog(check: dict, row: dict, case: dict, by_f: dict):
    st.markdown(f"**{case['case_id']}** · {case['severity']} · {case['summary']}")
    verdict_form(check, row, case, by_f, f"{check['check_id']}_{case['case_id']}_v")


@st.dialog("The ground truth is wrong here", width="large")
def correction_dialog(check: dict, case: dict):
    st.markdown(f"**{case['case_id']}** · {case['summary']}")
    correction_form(check, case, f"{check['check_id']}_{case['case_id']}_c")


@st.dialog("Case", width="large")
def case_dialog(check: dict, row: dict, cmp: dict, chunks: dict, by_f: dict):
    from .case_view import case_view, room_index
    st.markdown(f"### {MARK[row['status']]} {row['case_id']} · {row['status']}")
    case_view(check, row, cmp, chunks, by_f, room_index(check["data_room"]), in_dialog=True)


@st.dialog("Finding", width="large")
def finding_dialog(check: dict, fid: str, res: dict, cmp: dict, chunks: dict, by_f: dict):
    from .case_view import case_view, room_index
    cases = [r for r in res["cases"] + res["non_issues"] if fid in r["finding_ids"]]
    if not cases:
        _unlinked(check, next(n for n in res["new"] if n["finding_id"] == fid), chunks, by_f)
        return
    st.markdown(f"### {fid} is linked to " + ", ".join(f"{MARK[r['status']]} {r['case_id']} ({r['status']})" for r in cases))
    index = room_index(check["data_room"])
    for r in cases:
        if len(cases) > 1:
            st.markdown(f"#### {r['case_id']}")
        case_view(check, r, cmp, chunks, by_f, index, in_dialog=True)


def _unlinked(check: dict, n: dict, chunks: dict, by_f: dict):
    fid = n["finding_id"]
    st.markdown(f"### {fid} · not in the ground truth · {n['band']}")
    if n["band"] in (rc.CANDIDATE, rc.REVIEW, "Not checked"):
        candidate_review(check, fid, chunks, by_f)           # the claim, evidence, checklist and the decision
        return
    check_finding_card(by_f[fid], chunks)
    st.markdown(f"**Verdict:** {n['status']}")
    if n["explanation"]:
        st.write(n["explanation"])
    if n["band"] == rc.REJECTED_RULE:
        st.caption(n["reason"])
        restore_form(check, fid, context.rule_name(n["rule_id"]), f"{check['check_id']}_{fid}")
    else:
        st.caption(f"Rejected by you: {n['note']}")
        if st.button("Undo the rejection", key=f"undo_{check['check_id']}_{fid}"):
            rc.clear_manual(check, "finding", fid)
            st.rerun()
