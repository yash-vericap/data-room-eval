"""Report and audit: the downloads with a preview, the models that gave the verdicts, and what left the machine."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from eval import store
from eval import reality_check as rc

from .state import S


def report_and_audit(check: dict, res: dict, cmp: dict):
    text = rc.markdown(check, res, cmp, store.snapshot_label(S.snapshot))
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in check["label"])
    with st.container(border=True):
        st.markdown("#### The report")
        st.caption(f"{check['label']} · {check['data_room']} · checked {check['created_at'][:10]} · answer key "
                   f"{store.snapshot_label(S.snapshot)}")
        b1, b2, _ = st.columns([1, 1, 2])
        b1.download_button("Download the report (.md)", text, f"{safe}_check.md", width="stretch", type="primary")
        b2.download_button("Download everything (.json)", json.dumps({"check": check, "results": res, "baselines": cmp},
                           indent=1, ensure_ascii=False, default=str), f"{safe}_check.json", width="stretch")
        if st.toggle("Preview the report", key=f"prev_{check['check_id']}"):
            with st.container(height=460, border=True):
                st.markdown(text.replace("$", "\\$"))

    left, right = st.columns(2)
    with left.container(border=True):
        st.markdown("#### Models that gave the verdicts")
        used = sorted(rc.models_used(check).items(), key=lambda kv: -kv[1])
        total = sum(v for _, v in used) or 1
        if not used:
            st.caption("No model verdict yet.")
        for model, n in used:
            st.markdown(f"**{model}** · {n} verdict{'s' if n != 1 else ''}")
            st.progress(n / total)
        by_rule = sum(bool(r.get("by_rule")) for r in res["cases"] + res["non_issues"])
        by_hand = sum(r["manual"] for r in res["cases"] + res["non_issues"])
        st.caption(f"Also: {by_rule} decided by rule with no model call, {by_hand} set by hand.")
    with right.container(border=True):
        st.markdown("#### Keep this run")
        st.caption("Stores a copy in submissions/system, next to the baseline runs, in the standard run format.")
        if st.button("Keep this run with the other runs"):
            if any(r["run"]["run_id"] == check["label"] and r["run"]["source"] == "Baseline model" for r in S.results):
                st.error(f"A baseline run is already called {check['label']}. Read the run again under another name first.")
            else:
                path, _ = store.save_submission(rc.as_contract_run(check), folder="system", allow_problems=True)
                st.cache_data.clear()
                st.success(f"Stored as {path.relative_to(store.DATA)}.")
    _sent(check)


def _sent(check: dict):
    sent = rc.pages_sent(check)
    with st.container(border=True):
        st.markdown("#### What left the machine")
        if not sent:
            st.caption("No document page has been sent to a model for this run.")
            return
        frame = pd.DataFrame(sent)
        endpoints = sorted({f"{r['model']} ({r['provider']})" for r in sent})
        k = st.columns(3)
        k[0].metric("Documents", frame["doc_id"].nunique())
        k[1].metric("Pages", len(frame[["doc_id", "page"]].drop_duplicates()))
        k[2].metric("Times sent", int(frame["calls"].sum()))
        st.caption("Only these pages were sent, to: " + ", ".join(endpoints) + ". The page text is not stored here.")
        grouped = [{"Document": doc, "Pages": ", ".join(str(p) for p in sorted({int(x) for x in g["page"].dropna()})) or "?",
                    "Times sent": int(g["calls"].sum()), "Models": ", ".join(sorted(set(g["model"].dropna()))),
                    "Last sent": (max(g["last_sent"].dropna()) if g["last_sent"].notna().any() else "")[:16].replace("T", " ")}
                   for doc, g in frame.groupby("doc_id")]
        st.dataframe(pd.DataFrame(grouped), hide_index=True, width="stretch")
