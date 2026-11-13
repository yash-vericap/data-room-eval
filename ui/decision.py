"""The evaluator's decision on a candidate: accept it as a case or a non-issue, or reject it, with a reason."""
from __future__ import annotations

import streamlit as st

from eval import context, contract, library, store
from eval import reality_check as rc



def _decision(check: dict, fid: str, lines: list[dict]):
    fails = [x["check"] for x in lines if x["result"] == "Fail"]
    choice = st.radio("Decision", ["Decide later", "Accept as a case", "Accept as a non-issue case", "Reject"],
                      horizontal=True, key=f"rc_dec_{check['check_id']}_{fid}")
    if choice.startswith("Accept"):
        report_it = choice == "Accept as a case"
        pre = rc.prefill_case(check, fid, report=report_it)
        classes = sorted(contract.REPORTABLE_CLASSES) if report_it else ["Contextual difference", "Consistent"]
        with st.form(f"accept_{fid}_{report_it}"):
            a1, a2, a3, a4 = st.columns(4)
            case_id = a1.text_input("Case ID", pre["case_id"])
            cls = a2.selectbox("Classification", classes, index=classes.index(pre["classification"]) if pre["classification"] in classes else 0)
            sev = a3.selectbox("Severity", contract.SEVERITIES, index=contract.SEVERITIES.index(pre["severity"]))
            set_ = a4.selectbox("Set", ["Withheld", "Development"])
            summary = st.text_input("Summary", pre["summary"])
            claims = st.text_area("Claims compared", pre["claims_compared"])
            explanation = st.text_area("Explanation (the judge's, to be confirmed)", pre["explanation"])
            cits = st.text_area("Citations, one per line", "\n".join(c["raw"] for c in pre["citations"]))
            d1, d2, d3 = st.columns(3)
            documents_ = d1.text_input("Documents", ", ".join(pre["documents"]))
            registers = d2.text_input("Register IDs", ", ".join(pre["register_ids"]))
            check_type = d3.text_input("Check type", pre["check_type"])
            e1, e2, e3 = st.columns(3)
            tags = e1.text_input("Scenario tags (separate with ;)", "; ".join(pre["scenario_tags"]))
            fj = e2.selectbox("Fact or judgment", ["Fact", "Judgment"], index=0 if pre["fact_or_judgment"] == "Fact" else 1)
            ambiguous = e3.checkbox("Ambiguous", value=pre["ambiguous"])
            alt = st.text_input("Alternative readings", pre["alternative_readings"])
            reason = st.text_input("Reason for accepting")
            extra = st.text_input(f"The checklist fails on: {', '.join(fails)}. Say why you accept anyway") if fails else ""
            if st.form_submit_button("Accept"):
                if not reason.strip() or (fails and not extra.strip()):
                    st.error("A reason is required" + (", and one more sentence because a checklist line fails." if fails else "."))
                elif any(c["case_id"] == case_id.strip() for c in store.load_cases(store.DRAFT)):
                    st.error(f"Case {case_id} already exists.")
                elif not case_id.strip().startswith(check["data_room"] + "-"):
                    st.error(f"The case ID must start with {check['data_room']}-.")
                else:
                    split = lambda t, sep: [x.strip() for x in t.split(sep) if x.strip()]
                    case = {**pre, "case_id": case_id.strip(), "classification": cls, "severity": sev,
                            "weight": contract.WEIGHTS[sev], "set": set_, "summary": summary.strip(),
                            "claims_compared": claims.strip(), "explanation": explanation.strip(),
                            "citations": contract.parse_citations(cits), "documents": split(documents_, ","),
                            "register_ids": split(registers, ","), "check_type": check_type.strip(),
                            "scenario_tags": split(tags, ";"), "fact_or_judgment": fj, "ambiguous": ambiguous,
                            "alternative_readings": alt.strip()}
                    why = reason.strip() + (f" Accepted against a failed check ({', '.join(fails)}): {extra.strip()}" if fails else "")
                    rc.accept_candidate(check, fid, case, why)
                    st.session_state["use_draft"] = True
                    st.cache_data.clear()
                    st.rerun()
    elif choice == "Reject":
        with st.form(f"reject_{fid}"):
            kind = st.selectbox("Reason", library.REJECT_REASONS)
            rule = st.selectbox("Rule, when a rule excuses it", ["(none)"] + [r["rule_id"] for r in context.rules_on()],
                                format_func=lambda r: r if r == "(none)" else context.rule_name(r))
            sentence = st.text_input("One sentence")
            if st.form_submit_button("Reject"):
                if not sentence.strip():
                    st.error("Add a sentence saying why.")
                else:
                    rc.reject_candidate(check, fid, f"{kind}: {sentence.strip()}", None if rule == "(none)" else rule)
                    st.rerun()


# ---------------------------------------------------------------------------------------------------
