"""One ground-truth case: the ground truth and the run side by side, why it got its verdict, and what to do about it.
Shown inside a toggle on Comparison, or inside a pop-up from Summary and Run details."""
from __future__ import annotations

import streamlit as st

from eval import matching
from eval import reality_check as rc

from .state import S
from .common import case_facts
from .compare import closest, side_by_side
from .forms import correction_form, verdict_form

FIX, WRONG_GT = "Change the verdict", "The ground truth is wrong"


def room_index(room: str) -> matching.RoomIndex:
    return matching.RoomIndex([c for c in S.cases if c["data_room"] == room])


def _decided_by(r: dict) -> str:
    if r["manual"]:
        return f"by hand, over the model's \"{r['model_status'] or 'no verdict'}\""
    if r.get("by_rule"):
        return "by rule: no finding in the run is related to this case, so no model was asked"
    return "by the model, after reading the case, the related findings and the cited pages"


def case_view(check: dict, r: dict, cmp: dict, chunks: dict, by_f: dict, index, in_dialog: bool = False):
    c = S.case_by_id[r["case_id"]]
    findings = [by_f[i] for i in r["finding_ids"] if i in by_f]
    empty = ("The run has no finding on this case." if c["report"]
             else "The run did not mention this. That is right: it is a non-issue.")
    st.markdown(side_by_side(c, findings, chunks, empty), unsafe_allow_html=True)
    if len(findings) > 3:
        st.caption("Also linked: " + ", ".join(f["finding_id"] for f in findings[3:]) + ". See Run details.")
    if not findings and c["report"]:
        near = closest(c, check["findings"], index)
        st.markdown("**Closest the run came** (not linked to this case by the verdict)")
        for s, f in near:
            st.caption(f"{f['finding_id']} · match {s:.2f} · {f['summary'][:160]}")
        if not near:
            st.caption("No finding in the run shares a document or wording with this case.")

    st.markdown(f"**Why {r['status'].lower()}** · decided {_decided_by(r)}")
    for title, text in (("What the run got right", r["covered"]), ("What is missing or wrong", r["missing"]),
                        ("Reasoning", r["explanation"]), ("Reason given by hand", r["note"] if r["manual"] else "")):
        if text:
            st.write(f"*{title}.* {text}")
    if r["quote"]:
        st.caption(f"Passage the verdict relies on: “{r['quote']}”")
    if c["report"]:
        who = cmp["found_by"].get(c["case_id"], [])
        st.caption(f"Baseline runs that found it: {len(who)} of {cmp['baselines']}" + (f" ({', '.join(who)})" if who else ""))
    if c.get("register_ids"):
        case_facts(c)
    if r["manual"] and r["stale"]:
        st.warning("The case changed after you set this verdict.")
    _actions(check, r, c, by_f, in_dialog)


def _can_go_back(r: dict) -> bool:
    """Only when the model gave a verdict. A case accepted from this run has none, and removing its verdict
    would reopen the run."""
    return r["manual"] and bool(r["model_status"])


def _actions(check: dict, r: dict, c: dict, by_f: dict, in_dialog: bool):
    key = f"{check['check_id']}_{c['case_id']}_{'d' if in_dialog else 'p'}"
    if in_dialog:                                  # already in a pop-up: the form opens right here
        pick = st.radio("Action", [FIX, WRONG_GT] + (["Back to the model's verdict"] if _can_go_back(r) else []),
                        index=None, horizontal=True, key=f"act_{key}")
        if pick == FIX:
            verdict_form(check, r, c, by_f, key)
        elif pick == WRONG_GT:
            correction_form(check, c, key)
        elif pick:
            rc.clear_manual(check, "case", c["case_id"])
            st.rerun()
        return
    from .dialogs import correction_dialog, verdict_dialog
    b1, b2, b3, _ = st.columns(4)
    if b1.button(FIX, key=f"chg_{key}", width="stretch"):
        verdict_dialog(check, r, c, by_f)
    if b2.button(WRONG_GT, key=f"fix_{key}", width="stretch"):
        correction_dialog(check, c)
    if _can_go_back(r) and b3.button("Back to the model's verdict", key=f"back_{key}", width="stretch"):
        rc.clear_manual(check, "case", c["case_id"])
        st.rerun()
