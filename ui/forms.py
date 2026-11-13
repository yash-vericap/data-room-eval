"""The small forms behind every action, so they can sit in a pop-up of their own or inside a bigger pop-up."""
from __future__ import annotations

import streamlit as st

from eval import context, library
from eval import reality_check as rc


def verdict_form(check: dict, row: dict, case: dict, by_f: dict, key: str):
    st.caption(f"Verdict now: {row['status']}" + (" (set by hand)" if row["manual"] else ""))
    options = [rc.FOUND, rc.PARTIAL, rc.MISSED, rc.REVIEW] if case["report"] else [rc.NOT_FLAGGED, rc.LABELLED, rc.WRONG, rc.REVIEW]
    status = st.radio("New verdict", options, horizontal=True, key=f"vs_{key}",
                      index=options.index(row["status"]) if row["status"] in options else len(options) - 1)
    ids = []
    if status in rc.LINKING:
        ids = st.multiselect("The findings this verdict rests on", list(by_f), default=row["finding_ids"], key=f"vf_{key}",
                             format_func=lambda i: f"{i} · {by_f[i]['summary'][:70]}")
    note = st.text_area("Reason", key=f"vn_{key}", placeholder="Why the model's verdict is wrong here. Kept with the verdict.")
    if st.button("Save the verdict", type="primary", key=f"vb_{key}"):
        if status in rc.LINKING and not ids:
            st.error("Pick the finding this verdict rests on.")
        elif not note.strip():
            st.error("Give a reason.")
        else:
            rc.set_manual(check, "case", case["case_id"], status, ids, note.strip(),
                          rc.case_hash(case, context.block_for_case(case)))
            st.rerun()


def correction_form(check: dict, case: dict, key: str):
    st.caption("This stores a correction request with the pending rows. The case changes only when the corrected "
               "evaluation sheet is uploaded.")
    what = st.text_input("What is wrong", key=f"cw_{key}", placeholder="For example: the severity, a figure, a citation")
    corrected = st.text_input("The corrected value or label", key=f"cc_{key}")
    why = st.text_area("Reason", key=f"cr_{key}")
    if st.button("Store the correction request", type="primary", key=f"cb_{key}"):
        if not (what.strip() and corrected.strip() and why.strip()):
            st.error("Fill in all three fields.")
        else:
            library.add_correction(case["case_id"], case["data_room"], what.strip(), corrected.strip(), why.strip(),
                                   check["check_id"])
            st.success("Stored with the pending rows.")


def restore_form(check: dict, fid: str, rule: str, key: str):
    st.caption(f"Rejected by the rule: {rule}")
    why = st.text_area("Why the rule is wrong here", key=f"rw_{key}")
    if st.button("Restore to review", type="primary", key=f"rb_{key}"):
        if not why.strip():
            st.error("Give a reason.")
        else:
            rc.restore(check, fid, why.strip())
            st.rerun()
