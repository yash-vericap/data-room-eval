"""Candidate review: the claim, the evidence side by side, the checklist, and the case for and against."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import context, scoring, store
from eval import reality_check as rc

from .state import S
from .common import QUOTE_LABEL, RESULT_MARK, case_card, check_finding_card, page_excerpt
from .decision import _decision


def candidate_review(check: dict, fid: str, chunks: dict, by_f: dict):
    f, v = by_f[fid], check["new_verdicts"].get(fid) or {}
    docs = context.doc_info(check["data_room"])
    st.markdown(f"#### Candidate review · {fid}")
    st.markdown("**1. The claim**")
    check_finding_card(f, chunks)

    st.markdown("**2. The evidence, side by side**")
    cited = list(dict.fromkeys(c["doc_id"] for c in f["citations"] if c["doc_id"]))[:4]
    if not cited:
        st.info("The finding names no document.")
    for col, doc in zip(st.columns(max(len(cited), 1)), cited):
        with col:
            info = docs.get(doc, {})
            st.markdown(f"**{doc}** · {info.get('title') or ''}")
            st.caption(f"Date: {info.get('doc_date') or 'not recorded'} · Authority: {info.get('authority') or 'not recorded'}")
            for c in [c for c in f["citations"] if c["doc_id"] == doc]:
                page = rc._page_of(c, chunks)
                text = (chunks.get(doc) or {}).get(page) if page is not None else None
                result = scoring.quote_is_real(c["quote"], chunks.get(doc), c["page"]) if c["quote"] and chunks.get(doc) else "Not checked"
                st.caption(f"Page {page if page is not None else '?'} · {QUOTE_LABEL[result]}")
                if text:
                    st.markdown(page_excerpt(text, c["quote"]), unsafe_allow_html=True)
                elif not c["quote"]:
                    st.write("The finding quotes no passage from this document.")
                else:
                    st.write("Not found in the data room.")
    if f["classification"] == "Insufficient evidence":
        st.caption("The finding says something is missing. The pages above are where it should appear; what it asks for "
                   "was not found in the data room.")

    st.markdown("**3. Admission checklist**")
    lines = rc.checklist(check, fid, S.cases, store.load_runs())
    st.dataframe(pd.DataFrame([{"Check": x["check"], "Result": RESULT_MARK[x["result"]], "Why": x["reason"]} for x in lines]),
                 hide_index=True, width="stretch")
    near = rc.closest_cases(check, fid, S.cases)
    for n in near:
        with st.expander(f"Closest case {n['case_id']} · score {n['score']:.2f}"):
            case_card(S.case_by_id[n["case_id"]])

    st.markdown("**4. For and against (the model's view)**")
    st.write(f"For: {v.get('why_it_matters') or 'nothing given.'}")
    st.write(f"Against: {v.get('why_it_might_not') or 'nothing given.'}")
    if v.get("precheck"):
        st.caption(f"Rule pre-check: {v['precheck']['tag']} ({v['precheck']['rule_id']}). {v['precheck']['reason']}")


    st.markdown("**5. The decision**")
    _decision(check, fid, lines)
