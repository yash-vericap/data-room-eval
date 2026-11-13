"""The three steps of the run check: give the run, see what was read, run the check."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from eval import reality_check as rc

from .state import S
from .earlier import _earlier


def _step1():
    with st.container(border=True):
        st.markdown("##### Step 1 · Give the run")
        c1, c2 = st.columns(2)
        check_room = c1.selectbox("Data room", S.rooms, key="rc_room", help="The data room this run was made on. "
                                  "Add a new one on the Data rooms screen.")
        name = c2.text_input("Name for this run (optional)", key="rc_name", help="Left empty, the run's own ID is used.")
        mode = st.radio("How to give the run", ["Paste JSON", "Upload a file", "Open an earlier check"], horizontal=True)
        if mode == "Open an earlier check":
            _earlier(check_room)
        else:
            text = st.text_area("Run JSON", height=160, key="rc_text", placeholder="Paste the JSON the system returned") \
                if mode == "Paste JSON" else None
            up = st.file_uploader("Run file (.json)", type="json", key="rc_file") if mode == "Upload a file" else None
            if st.button("Read the run", type="primary"):
                raw = text if mode == "Paste JSON" else (up.getvalue().decode("utf-8", errors="replace") if up else "")
                st.session_state.pop("rc_check", None)
                if not raw.strip():
                    st.error("Nothing to read. Paste the JSON or choose a file first.")
                else:
                    try:
                        read = rc.read_findings(json.loads(raw))
                    except json.JSONDecodeError as e:
                        st.error(f"Not valid JSON: {e}")
                    except ValueError as e:
                        st.error(str(e))
                    else:
                        label = name.strip() or str(read["run_meta"].get("run_id") or "").strip() or "Vericap run"
                        st.session_state["rc_check"] = rc.open_check(check_room, label, read)["check_id"]


def _step2(check: dict):
    with st.container(border=True):
        st.markdown(f"##### Step 2 · What was read · {check['label']} · {check['data_room']}")
        others = len(rc.list_checks(check["data_room"])) - 1
        st.write(f"**{len(check['findings'])} findings** read from `{check['source_path']}`."
                 + (f" {others} other run{'s' if others != 1 else ''} of {check['data_room']} {'are' if others != 1 else 'is'} "
                    f"checked too; compare them on Stats." if others > 0 else ""))
        file_room = (check.get("run_meta") or {}).get("data_room")
        if file_room and file_room != check["data_room"]:
            st.warning(f"The file names data room {file_room}. The selected data room, {check['data_room']}, is used.")
        by_class = pd.Series([f["classification"] or "Class not read" for f in check["findings"]]).value_counts()
        by_sev = pd.Series([f["severity"] or "Severity not read" for f in check["findings"]]).value_counts()
        st.caption("By class: " + ", ".join(f"{k} {v}" for k, v in by_class.items()) + ". By severity: "
                   + ", ".join(f"{k} {v}" for k, v in by_sev.items()) + ".")
        for n in check["read_notes"]:
            st.caption(f"⚠️ {n}")
        own = (check.get("run_meta") or {}).get("summary") or {}
        if own:
            with st.expander("The run's own summary"):
                if own.get("overview"):
                    st.write(own["overview"])
                totals = own.get("totals") or {}
                st.write(f"By category, as the run reports it: {totals.get('by_category') or 'not given'}. "
                         f"By severity, as the run reports it: {totals.get('by_severity') or 'not given'}.")
                for label, key in (("Limitations the run reports", "limitations"), ("Documents with no findings", "documents_without_findings")):
                    if own.get(key):
                        st.write(f"{label}: {', '.join(map(str, own[key]))}.")
        with st.expander("Every finding as read"):
            st.dataframe(pd.DataFrame([{"ID": f["finding_id"], "Class": f["classification"] or f"(not read: {f['raw_classification']})",
                                        "Severity": f["severity"] or f"(not read: {f['raw_severity']})", "Summary": f["summary"],
                                        "Documents": ", ".join(sorted({c['doc_id'] for c in f['citations'] if c['doc_id']}))}
                                       for f in check["findings"]]), hide_index=True, width="stretch")
