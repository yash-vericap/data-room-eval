"""Data room evaluation.   streamlit run app.py

The sidebar only moves between screens; each screen lives in ui/ and every filter sits on its screen."""
from __future__ import annotations

import os

import streamlit as st

from eval import doc_store, judge, providers, store
from ui import state
from ui.rooms import screen_rooms
from ui.run_check import screen_run_check
from ui.stats import screen_stats
from ui.upload import screen_upload

st.set_page_config(page_title="Data room evaluation", layout="wide")
SCREENS = {"Vericap run check": screen_run_check, "Data rooms": screen_rooms, "Upload evaluation sheet": screen_upload,
           "Stats": screen_stats}

if os.environ.get("EVAL_APP_PASSWORD") and not st.session_state.get("signed_in"):
    st.title("Data room evaluation")
    if st.text_input("Password", type="password") == os.environ["EVAL_APP_PASSWORD"]:
        st.session_state["signed_in"] = True
        st.rerun()
    st.stop()

st.sidebar.title("Data room evaluation")
page = st.sidebar.radio("Screen", list(SCREENS))
if not state.refresh():
    st.error(f"No answer key found in {store.ANSWER_KEY}. Run: python -m eval import-sheet <file> --yes")
    st.stop()
S = state.S
st.sidebar.caption(f"Answer key: {store.snapshot_label(S.snapshot)}, {len(S.cases)} cases.")
st.sidebar.caption(f"Document text: {doc_store.describe()}.")
st.sidebar.caption(f"Model: {judge.judge_label() if judge.credentials_present() else 'not set up'}.")
if providers.data_policy() != "strict":
    st.warning("The data policy is open (EVAL_DATA_POLICY=open): document pages may be sent to a free-tier model whose "
               "terms may keep or train on them. Set it to strict for confidential documents.")
if store.chunks_problem():
    st.warning(f"The document text could not be read: {store.chunks_problem()} Scores that do not need page text "
               f"still work. Quote checks show \"Not checked\" until it is back.")
SCREENS[page]()
