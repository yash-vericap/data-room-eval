"""The Upload evaluation sheet screen: preview, confirm, pending rows, freezing and the change log."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from eval import library, store

from .common import page_header


# Upload evaluation sheet
def screen_upload():
    page_header("Upload evaluation sheet",
                "The Google Sheet stays the place where cases, facts, documents, rules and baseline runs are written. "
                "Export it as .xlsx and upload it here. Nothing is written until you confirm.")
    up = st.file_uploader("Sheet export (.xlsx)", type=["xlsx", "json"])
    if up is not None:
        try:
            staged = library.stage(library.read(up.getvalue(), up.name))
        except Exception as e:                       # a broken workbook must not crash the page
            st.error(f"The file could not be read: {e}")
            staged = None
        if staged is not None:
            problems, pv = library.validate(staged), library.preview(staged)
            st.caption(f"Tabs read: {', '.join(staged['tabs'])}. A tab that is missing leaves what is stored as it is.")
            st.subheader("What will change")
            st.dataframe(pd.DataFrame(pv["tabs"]).rename(columns={"tab": "Tab", "new": "New", "changed": "Changed", "removed": "Removed"}),
                         hide_index=True, width="stretch")
            for tab in ("Ground Truth", "Fact Sheet"):
                d = pv["changes"].get(tab)
                if d and d["changed"]:
                    with st.expander(f"{tab}: {len(d['changed'])} changed, field by field", expanded=len(d["changed"]) <= 10):
                        st.dataframe(pd.DataFrame([{"ID": c["id"], "Field": f, "Before": json.dumps(library._plain(v[0]), ensure_ascii=False, default=str),
                                                    "After": json.dumps(library._plain(v[1]), ensure_ascii=False, default=str)}
                                                   for c in d["changed"] for f, v in c["fields"].items()]),
                                     hide_index=True, width="stretch")
                if d and (d["new"] or d["removed"]):
                    st.caption(f"{tab}: new {', '.join(map(str, d['new'])) or 'none'}; removed {', '.join(map(str, d['removed'])) or 'none'}.")
            if pv["pending_cleared"] or pv["pending_kept"]:
                st.write(f"Pending rows this upload clears: {', '.join(p['case_id'] for p in pv['pending_cleared']) or 'none'}. "
                         f"Still pending afterwards: {', '.join(p['case_id'] for p in pv['pending_kept']) or 'none'}.")
            if problems["errors"]:
                st.error(f"{len(problems['errors'])} blocking errors. Fix them in the sheet and upload again.")
                st.write("\n".join(f"- {e}" for e in problems["errors"]))
            if problems["warnings"]:
                with st.expander(f"Warnings ({len(problems['warnings'])})"):
                    st.write("\n".join(f"- {w}" for w in problems["warnings"]))
            note = st.text_input("Note for the change log (optional)")
            if st.button("Confirm and write", type="primary", disabled=bool(problems["errors"])):
                out = library.apply(staged, up.name, note.strip())
                st.session_state["use_draft"] = True
                st.cache_data.clear()
                st.success(f"Written. {out['logged']} change-log entries. Cases went to the working draft; freeze it "
                           f"below to make it the answer key every run is scored against.")
    t1, t2 = st.columns(2)
    t1.download_button("Download the sheet template", library.template_xlsx(), "evaluation_sheet_template.xlsx")
    pending = library.load_pending()
    if pending:
        t2.download_button(f"Download pending rows ({len(pending)})", library.pending_xlsx(), "pending_rows.xlsx")

    st.subheader("Pending rows")
    if pending:
        st.caption("Accepted candidates and correction requests that are not in the sheet yet. Paste them into the sheet; "
                   "an upload that contains the case clears its row.")
        st.dataframe(pd.DataFrame([{"Case": p["case_id"], "Kind": p["kind"], "Status": p["status"], "Reason": p["reason"],
                                    "From check": p["check_id"], "At": p["at"]} for p in pending]), hide_index=True, width="stretch")
    else:
        st.write("None.")

    st.subheader("Working draft and snapshots")
    names = store.snapshots()
    differs = library.draft_differs()
    st.write(f"Frozen snapshots: {', '.join(store.snapshot_label(n) for n in names) or 'none'}. "
             + (f"The working draft differs from {store.snapshot_label(names[-1])} in {differs} cases." if store.has_draft() and names
                else "No working draft yet: it is created by the first upload or the first accepted candidate."))
    if store.has_draft():
        nxt = f"Library v{int(names[-1].split('_v')[1]) + 1 if names else 1}"
        if [p for p in pending if p["kind"] == "case"]:
            st.warning("Some accepted cases are not in the sheet yet. Freezing keeps them, but the sheet will be behind.")
        why = st.text_input("Reason for freezing now")
        if st.button(f"Freeze as {nxt}", disabled=not differs and bool(names)):
            out = library.freeze(why.strip())
            st.session_state.pop("answer_key", None)
            st.session_state.pop("w_answer_key", None)
            st.cache_data.clear()
            st.success(f"Frozen as {store.snapshot_label(out['name'])}: {out['cases']} cases. Every stored run is now scored against it.")

    st.subheader("Change log")
    log = library.load_changelog()
    if not log:
        st.write("No change yet.")
        return
    g1, g2 = st.columns(2)
    actions = g1.multiselect("Action", sorted({e["action"] for e in log}), default=sorted({e["action"] for e in log}))
    objects = g2.multiselect("Object", sorted({e["object"] for e in log}), default=sorted({e["object"] for e in log}))
    text = lambda v: v if isinstance(v, str) or v is None else json.dumps(v, ensure_ascii=False, default=str)
    st.dataframe(pd.DataFrame([{**e, "before": text(e["before"]), "after": text(e["after"])} for e in reversed(log)
                               if e["action"] in actions and e["object"] in objects]), hide_index=True, width="stretch")
