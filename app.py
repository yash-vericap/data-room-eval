"""Streamlit view of the evaluation results.   streamlit run app.py"""
from __future__ import annotations

import html
import json
import os

import pandas as pd
import streamlit as st

from eval import api, compare, context, contract, data_room, doc_store, judge, library, providers, report, scoring, store
from eval import reality_check as rc

st.set_page_config(page_title="Data room evaluation", layout="wide")

PCT = st.column_config.NumberColumn(format="percent")
BAR = st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)
STATUSES = ["Match", "Duplicate", "False positive candidate", "Needs review"]
EVIDENCE = ["Sufficient", "Partial", "Not supported"]
SCREENS = ["Vericap run check", "Overview", "Run detail", "Review queue", "Judge versus rules", "Reliability", "Compare",
           "Add a run", "Upload evaluation sheet", "Rules and facts", "Method check"]
BASELINE_HINT = "Baseline runs are hidden. Tick \"Show baseline runs on the other screens\" in the sidebar to see them."


def _stamp() -> float:
    files = (list(store.SUBMISSIONS.rglob("*.json")) + list(store.ANSWER_KEY.glob("*.json")) + [store.REVIEWS, judge.VERDICTS]
             + list(store.DATA_ROOM.glob("*/chunks.json")))
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0) + doc_store.generation


@st.cache_data(show_spinner="Scoring runs...")
def load(stamp: float, snapshot: str):
    cases = store.load_cases(snapshot)
    return scoring.score_all(cases=cases), cases, store.load_documents()


if os.environ.get("EVAL_APP_PASSWORD") and not st.session_state.get("signed_in"):
    st.title("Data room evaluation")
    if st.text_input("Password", type="password") == os.environ["EVAL_APP_PASSWORD"]:
        st.session_state["signed_in"] = True
        st.rerun()
    st.stop()

st.sidebar.title("Data room evaluation")
page = st.sidebar.radio("Screen", SCREENS)
keys = list(reversed(store.snapshots())) + ([store.DRAFT] if store.has_draft() else [])
if not keys:
    st.error(f"No answer key found in {store.ANSWER_KEY}. Run: python -m eval import-sheet <file> --yes")
    st.stop()
if st.session_state.pop("use_draft", False) and store.DRAFT in keys:      # set after a candidate is accepted
    st.session_state["answer_key"] = store.DRAFT
if st.session_state.get("answer_key") not in keys:
    st.session_state["answer_key"] = keys[0]
snapshot = st.sidebar.selectbox("Answer key", keys, key="answer_key", format_func=store.snapshot_label,
                                help="Frozen snapshots never change. The working draft holds uploads and accepted "
                                     "candidates that are not frozen yet.")
results, cases, documents = load(_stamp(), snapshot)
case_by_id = {c["case_id"]: c for c in cases}
by_run = {r["run"]["run_id"]: r for r in results}
rooms = sorted({c["data_room"] for c in cases})
room = st.sidebar.selectbox("Data room", ["All"] + rooms)
show_baselines = st.sidebar.checkbox("Show baseline runs on the other screens", value=False)
st.sidebar.caption(f"Answer key: {store.snapshot_label(snapshot)}, {len(cases)} cases. {len(results)} runs stored.")
in_room = [r for r in results if (room == "All" or r["run"]["data_room"] == room)
           and (show_baselines or r["run"]["source"] != "Baseline model")]
if providers.data_policy() != "strict":
    st.warning("The data policy is open (EVAL_DATA_POLICY=open): document pages may be sent to a free-tier model whose "
               "terms may keep or train on them. Set it to strict for confidential documents.")


if store.chunks_problem():
    st.warning(f"The document text could not be read: {store.chunks_problem()} Scores that do not need page text "
               f"still work. Quote checks show \"Not checked\" until it is back.")
st.sidebar.caption(f"Document text: {doc_store.describe()}.")


def no_runs():
    st.info("No run stored for this data room." + ("" if show_baselines else " " + BASELINE_HINT))
    st.stop()


def pick_run(label="Run", key="run"):
    ids = [r["run"]["run_id"] for r in sorted(in_room, key=lambda r: -(r["metrics"]["weighted_recall"] or 0))]
    if not ids:
        no_runs()
    return by_run[st.selectbox(label, ids, key=key)]


def case_card(c: dict):
    st.markdown(f"**{c['case_id']}** · {c['classification']} · {c['severity']} · "
                f"{'report' if c['report'] else 'do not report'} · {c['set']}"
                + (" · ambiguous" if c["ambiguous"] else ""))
    st.write(c["summary"])
    st.caption("Claims compared")
    st.write(c["claims_compared"])
    st.caption("Citations")
    st.write("\n".join(f"- {x['raw']}" for x in c["citations"]))
    st.caption("Explanation")
    st.write(c["explanation"])
    if c["alternative_readings"]:
        st.caption("Alternative readings")
        st.write(c["alternative_readings"])


def finding_card(f: dict):
    st.markdown(f"**{f['finding_id']}** · {f['classification'] or '(no class)'} · {f['severity'] or '(no severity)'}"
                + (f" · confidence {f['confidence']}" if f["confidence"] is not None else ""))
    st.write(f["summary"])
    st.caption("Claims compared")
    st.write(f["claims_compared"])
    st.caption("Citations")
    st.write("\n".join(f"- {x['raw']}" for x in f["citations"]))
    st.caption("Explanation")
    st.write(f["explanation"])


def review_panel(res: dict, f: dict, row: dict, verdict: dict | None = None):
    """The finding, the closest cases, the judge's verdict if there is one, and the decision form."""
    rid, fid = res["run"]["run_id"], f["finding_id"]
    room_cases = [c for c in cases if c["data_room"] == res["run"]["data_room"]]
    left, right = st.columns(2)
    with left:
        st.subheader("Finding")
        finding_card(f)
    with right:
        if verdict:
            st.subheader("Judge")
            v = verdict["verdict"]
            if v:
                st.markdown(f"Match: **{v['match']}** {', '.join(v['case_ids'])} · class correct: **{v['class_correct']}** · "
                            f"evidence: **{v['evidence']}** · reasoning: **{v['reasoning_score']}** · "
                            f"stable: **{ {True: 'yes', False: 'no', None: '-'}[verdict['stable']] }**")
                st.write(v["explanation"])
                st.caption("Passage the judge relies on")
                st.write(f"\u201c{v['quote']}\u201d")
            if verdict["reasons"]:
                st.warning("Sent to manual review: " + "; ".join(verdict["reasons"]))
        st.subheader("Closest cases")
        if not row["candidates"]:
            st.info("No case shares a document with this finding.")
        for cand in row["candidates"]:
            with st.expander(f"{cand['case_id']} · score {cand['score']:.2f} (location {cand['location']}, "
                             f"values {cand['values']}, wording {cand['text']})", expanded=cand is row["candidates"][0]):
                case_card(case_by_id[cand["case_id"]])
    st.subheader("Decision")
    current = [r["case_id"] for r in res["rows"] if r["finding_id"] == fid and r["case_id"]]
    with st.form("decision"):
        status = st.selectbox("Status", STATUSES, index=STATUSES.index(row["status"]))
        ids = st.multiselect("Case (two for a finding that merges two cases)", [c["case_id"] for c in room_cases],
                             default=current, format_func=lambda c: f"{c} · {case_by_id[c]['summary'][:70]}")
        e1, e2 = st.columns(2)
        evidence = e1.selectbox("Evidence check", ["(rule)"] + EVIDENCE,
                                index=(EVIDENCE.index(row["evidence_manual"]) + 1) if row["evidence_manual"] in EVIDENCE else 0)
        reasoning = e2.selectbox("Reasoning score", ["(none)", 0, 1, 2],
                                 index=0 if row["reasoning"] is None else int(row["reasoning"]) + 1)
        note = st.text_input("Reason", value=row["note"])
        if st.form_submit_button("Save decision"):
            if status in ("Match", "Duplicate") and not ids:
                st.error("Pick the case this finding belongs to.")
            else:
                store.save_review(rid, fid, status=status, case_ids=ids if status in ("Match", "Duplicate") else [],
                                  evidence=None if evidence == "(rule)" else evidence,
                                  reasoning=None if reasoning == "(none)" else int(reasoning), note=note)
                st.cache_data.clear()
                st.rerun()
    if row["decided"] == "manual" and st.button("Remove the manual decision and go back to the rules"):
        store.delete_review(rid, fid)
        st.cache_data.clear()
        st.rerun()


# ---------------------------------------------------------------------------------------------------
# Vericap run check
MARK = {rc.FOUND: "🟢", rc.PARTIAL: "🟠", rc.MISSED: "🔴", rc.WRONG: "🔴", rc.REVIEW: "⚪", "Not checked": "⚪",
        rc.LABELLED: "🟢", rc.NOT_FLAGGED: "🟢"}
QUOTE_LABEL = {"Real": "Found on the page", "Partly found": "Partly found", "Wrong page": "Wrong page",
               "Not found": "Not found", "Not checked": "Not checked"}
RESULT_MARK = {"Pass": "✅ Pass", "Fail": "❌ Fail", "Unknown": "❔ Unknown", "Info": "ℹ️ Info"}


def _safe(text: str) -> str:
    return html.escape(text or "").replace("$", "&#36;")


def page_excerpt(text: str, quote: str, radius: int = 700) -> str:
    """A page as HTML, cut around the quoted words, with the quote in bold when it is there word for word."""
    text = text or ""
    at = text.lower().find((quote or "").lower()) if quote else -1
    if at < 0:
        body = _safe(judge._excerpt(text, quote or "", radius) if quote else text[:2 * radius] + (" ..." if len(text) > 2 * radius else ""))
    else:
        start, end = max(0, at - radius), min(len(text), at + len(quote) + radius)
        body = (("... " if start else "") + _safe(text[start:at]) + "<b>" + _safe(text[at:at + len(quote)]) + "</b>"
                + _safe(text[at + len(quote):end]) + (" ..." if end < len(text) else ""))
    return f'<div style="white-space:pre-wrap;font-size:0.85rem;border-left:3px solid #bbb;padding-left:0.6rem">{body}</div>'


def check_finding_card(f: dict, chunks: dict):
    st.markdown(f"**{f['finding_id']}** · {f['classification'] or f['raw_classification'] or '(no class)'} · "
                f"{f['severity'] or f['raw_severity'] or '(no severity)'}")
    st.write(f["summary"])
    if f["claims_compared"]:
        st.caption("Claims compared")
        st.write(f["claims_compared"])
    st.caption("Citations, each with its quote check")
    for c, q in zip(f["citations"], rc.own_quotes(f, chunks)):
        st.write(f"- {c['raw']} — {QUOTE_LABEL[q]}")
    if not f["citations"]:
        st.write("- (none)")
    if f["explanation"]:
        st.caption("Explanation")
        st.write(f["explanation"])


def case_facts(c: dict):
    facts = context.load_facts(c["data_room"])
    mine = [f for f in facts if f["fact_id"] in (c.get("register_ids") or [])]
    st.caption("Linked facts")
    if not mine:
        st.write(f"{', '.join(c.get('register_ids') or []) or 'None'}. "
                 + ("The fact sheet is not uploaded yet." if not facts else ""))
    for f in mine:
        st.write(f"- {f['fact_id']} · {f.get('subject')} · {f.get('value')} · {f.get('value_status')}. "
                 f"Change history: {context.chain_text(f, facts)}")


def screen_run_check():
    st.header("Vericap run check")
    st.write("Paste or upload one run of our system. The tool reads it, checks every ground-truth case against it, "
             "checks every other finding against the documents, and ranks the run against the baselines.")
    c1, c2 = st.columns(2)
    check_room = c1.selectbox("Data room", rooms, index=rooms.index(room) if room in rooms else 0, key="rc_room")
    name = c2.text_input("Name for this run (optional)", key="rc_name")
    mode = st.radio("How to give the run", ["Paste JSON", "Upload a file", "Open an earlier check"], horizontal=True)
    if mode == "Open an earlier check":
        earlier = rc.list_checks()
        if not earlier:
            st.info("No earlier check is stored.")
        else:
            pick = st.selectbox("Earlier check", earlier, format_func=lambda c: f"{c['label']} · {c['data_room']} · "
                                f"{(c['created_at'] or '')[:10]} · {c['findings']} findings")
            if st.button("Open the check"):
                st.session_state["rc_check"] = pick["check_id"]
    else:
        text = st.text_area("Run JSON", height=180, key="rc_text") if mode == "Paste JSON" else None
        up = st.file_uploader("Run file (.json)", type="json", key="rc_file") if mode == "Upload a file" else None
        if st.button("Read the run"):
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
    check = rc.load_check(st.session_state["rc_check"]) if st.session_state.get("rc_check") else None
    if check is None:
        return
    if check["data_room"] not in rooms:
        st.error(f"This check is for data room {check['data_room']}, which the selected answer key does not have.")
        return

    st.subheader(f"{check['label']} · {check['data_room']}")
    st.write(f"{len(check['findings'])} findings read from `{check['source_path']}`.")
    file_room = (check.get("run_meta") or {}).get("data_room")
    if file_room and file_room != check["data_room"]:
        st.warning(f"The file names data room {file_room}. The selected data room, {check['data_room']}, is used.")
    for n in check["read_notes"]:
        st.caption(f"Reading note: {n}")
    with st.expander("Every finding as read"):
        st.dataframe(pd.DataFrame([{"ID": f["finding_id"], "Class": f["classification"] or f"(not read: {f['raw_classification']})",
                                    "Severity": f["severity"] or f"(not read: {f['raw_severity']})", "Summary": f["summary"],
                                    "Documents": ", ".join(sorted({c['doc_id'] for c in f['citations'] if c['doc_id']}))}
                                   for f in check["findings"]]), hide_index=True, width="stretch")

    left = rc.remaining(check, cases)
    used = check.get("snapshot")
    if used and used != snapshot and left["cases"]:
        st.info(f"Checked against {store.snapshot_label(used)}. Run again to include the {len(left['cases'])} new or "
                f"changed cases.")
    elif left["stale"]:
        st.info(f"{len(left['stale'])} cases or their facts changed since they were checked. Run again to check them.")
    if left["total"]:
        if not judge.credentials_present():
            st.error(f"No model is set up, so the check cannot run. {judge.judge_label()}")
        elif st.button(f"Run the check ({left['total']} verdicts)", type="primary"):
            bar = st.progress(0.0, text="Starting")
            try:
                out = rc.run_check(check, cases, snapshot=snapshot,
                                   progress=lambda step, i, n: bar.progress(i / n, text=f"{step}: {i} of {n}"))
            except judge.JudgeUnavailable as e:
                st.error(f"The check could not run: {e}")
            else:
                if out["stopped"]:
                    st.warning(f"Stopped with {out['left']} verdicts left: {out['stopped']} Everything done so far is "
                               f"saved. Press the button again later to carry on.")
                else:
                    st.rerun()
        st.caption(f"Model: {judge.judge_label()}. One call per case, then one per finding that maps to no case.")
    check = rc.load_check(check["check_id"])
    if not check["case_verdicts"] and not check["manual"]:
        return
    show_results(check)


def show_results(check: dict):
    chunks = store.load_chunks(check["data_room"])
    res = rc.results(check, cases, chunks)
    cmp = rc.baseline_comparison(check, results, cases)
    m, a = res["metrics"], res["metrics"]["all"]
    by_f = {f["finding_id"]: f for f in check["findings"]}

    if m["candidates"]:
        st.info(f"This run found {m['candidates']} issue{'s' if m['candidates'] != 1 else ''} that are not in the ground "
                f"truth. Review them under Newly mapped.")
    if m["stale"]:
        st.info(f"{m['stale']} verdicts are stale: their case changed after it was checked.")

    k = st.columns(6)
    k[0].metric("Accuracy", report.pct(a["accuracy"]), f"{a['points']:g} of {a['possible']:g} points", delta_color="off")
    k[1].metric("Found", a["found"], f"of {a['cases']} cases", delta_color="off")
    k[2].metric("Partially found", a["partial"])
    k[3].metric("Missed", a["missed"], f"{a['critical_missed']} Critical", delta_color="off")
    k[4].metric("Backed by documents", report.pct(m["grounded_share"]), f"{m['grounded']} of {m['findings']} findings", delta_color="off")
    k[5].metric("Newly found", m["new_real"], f"{m['candidates']} candidates, {m['rejected_by_rules']} rejected by rules", delta_color="off")
    st.write(rc.verdict_sentence(res))
    st.caption(f"Accuracy is points over possible points: a found case earns its weight (Critical 8, High 4, Medium 2, "
               f"Low 1), a partially found case half. Withheld set {report.pct(m['withheld']['accuracy'])}, development set "
               f"{report.pct(m['development']['accuracy'])}. Quote check: {report.pct(m['quotes_found'])} of "
               f"{m['quotes_checked']} quoted passages are in their document. Open verdicts: {a['open'] + m['needs_review'] + m['not_checked']}.")
    if m["from_this_run"]:
        b = m["all_before"]
        st.caption(f"{m['from_this_run']} cases in this answer key came from this run. Without them the accuracy is "
                   f"{report.pct(b['accuracy'])} ({b['points']:g} of {b['possible']:g} points).")

    st.subheader("Against the baselines")
    st.write(f"Rank {cmp['rank']} of {cmp['runs']} runs on {check['data_room']} ({cmp['baselines']} baselines).")
    st.caption("This table uses the same fixed rules for every run, with no manual decisions for our run, so it can "
               "differ from the accuracy above, which comes from the model's verdicts.")
    st.dataframe(pd.DataFrame(cmp["table"]).drop(columns="ours"), hide_index=True, width="stretch",
                 column_config={"Weighted recall, all cases (rules)": BAR, "Precision": PCT})

    st.subheader("Coverage map")
    rows = res["cases"] + res["non_issues"]
    f1, f2, f3 = st.columns(3)
    present = [s for s in rc.STATUS_ORDER if any(r["status"] == s for r in rows)]
    pick_status = f1.multiselect("Status", present, default=present)
    pick_sev = f2.multiselect("Severity", contract.SEVERITIES, default=contract.SEVERITIES)
    pick_set = f3.multiselect("Set", sorted({r["set"] for r in rows}), default=sorted({r["set"] for r in rows}))
    shown = sorted([r for r in rows if r["status"] in pick_status and r["severity"] in pick_sev and r["set"] in pick_set],
                   key=lambda r: (rc.STATUS_ORDER.index(r["status"]), -r["weight"]))
    table = pd.DataFrame([{
        "Status": f"{MARK[r['status']]} {r['status']}" + (" (by hand)" if r["manual"] else "") + (" · stale" if r["stale"] else ""),
        "Case": r["case_id"], "Severity": r["severity"], "Set": r["set"],
        "Kind": "Reportable" if r["report"] else "Non-issue", "Summary": r["summary"],
        "Mapped findings": ", ".join(r["finding_ids"]),
        "Found by baselines": f"{len(cmp['found_by'].get(r['case_id'], []))} of {cmp['baselines']}" if r["report"] else ""}
        for r in shown])
    st.caption("Select a row to open the case.")
    event = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key=f"rc_map_{check['check_id']}")
    picked = event.selection.rows if event is not None and hasattr(event, "selection") else []
    if picked and picked[0] < len(shown):
        case_detail(check, shown[picked[0]], cmp, chunks, by_f)

    newly_mapped(check, res, chunks, by_f)

    st.subheader("Finding map")
    links = rc.linked(check, {r["case_id"] for r in rows})
    band_of = {n["finding_id"]: n for n in res["new"]}
    st.dataframe(pd.DataFrame([{
        "Finding": f["finding_id"], "Summary": f["summary"],
        "Went to": ", ".join(links[f["finding_id"]]) if f["finding_id"] in links else band_of[f["finding_id"]]["band"],
        "Verdict": "Mapped to a case" if f["finding_id"] in links else band_of[f["finding_id"]]["status"],
        "Rule": "" if f["finding_id"] in links else context.rule_name(band_of[f["finding_id"]]["rule_id"])}
        for f in check["findings"]]), hide_index=True, width="stretch")

    with st.expander("What was sent to the model"):
        sent = rc.pages_sent(check)
        st.caption("Only these pages left the machine, to the one model endpoint named here. The text itself is not stored "
                   "in this list.")
        st.dataframe(pd.DataFrame(sent) if sent else pd.DataFrame(columns=["doc_id", "page", "provider", "model"]),
                     hide_index=True, width="stretch")

    b1, b2, b3 = st.columns(3)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in check["label"])
    b1.download_button("Download the report (.md)", rc.markdown(check, res, cmp, store.snapshot_label(snapshot)), f"{safe}_check.md")
    b2.download_button("Download the results (.json)",
                       json.dumps({"check": check, "results": res, "baselines": cmp}, indent=1, ensure_ascii=False, default=str),
                       f"{safe}_check.json")
    if b3.button("Keep this run with the other runs"):
        if any(r["run"]["run_id"] == check["label"] and r["run"]["source"] == "Baseline model" for r in results):
            st.error(f"A baseline run is already called {check['label']}. Read the run again under another name first.")
        else:
            path, _ = store.save_submission(rc.as_contract_run(check), folder="system", allow_problems=True)
            st.cache_data.clear()
            st.success(f"Stored as {path.relative_to(store.DATA)}. It now shows on the other screens.")


def case_detail(check: dict, row: dict, cmp: dict, chunks: dict, by_f: dict):
    c = case_by_id[row["case_id"]]
    st.markdown(f"#### {MARK[row['status']]} {c['case_id']} · {row['status']}" + (" (set by hand)" if row["manual"] else ""))
    if row["manual"] and row["stale"]:
        st.warning("The case changed since you decided.")
    left, right = st.columns(2)
    with left:
        st.caption("Ground truth")
        case_card(c)
        case_facts(c)
    with right:
        st.caption("Findings mapped to it")
        if not row["finding_ids"]:
            st.info("No finding of the run is mapped to this case.")
        for fid in row["finding_ids"]:
            check_finding_card(by_f[fid], chunks)
            st.divider()
    if row["covered"]:
        st.write(f"**What the run got right.** {row['covered']}")
    if row["missing"]:
        st.write(f"**What is missing or wrong.** {row['missing']}")
    if row["explanation"]:
        st.write(f"**Judge.** {row['explanation']}")
    if row["quote"]:
        st.caption(f"Passage the verdict relies on: “{row['quote']}”")
    if row["manual"] and row["note"]:
        st.write(f"**Reason given by hand.** {row['note']}")
    if c["report"]:
        who = cmp["found_by"].get(c["case_id"], [])
        st.write(f"**Baselines.** Found by {len(who)} of {cmp['baselines']}" + (f": {', '.join(who)}." if who else "."))
    options = [rc.FOUND, rc.PARTIAL, rc.MISSED, rc.REVIEW] if c["report"] else [rc.NOT_FLAGGED, rc.LABELLED, rc.WRONG, rc.REVIEW]
    with st.form(f"verdict_{c['case_id']}"):
        st.caption("Change the verdict")
        status = st.selectbox("Status", options, index=options.index(row["status"]) if row["status"] in options else len(options) - 1)
        ids = st.multiselect("Findings", list(by_f), default=row["finding_ids"],
                             format_func=lambda i: f"{i} · {by_f[i]['summary'][:60]}")
        note = st.text_input("Reason")
        if st.form_submit_button("Save the verdict"):
            if status in rc.LINKING and not ids:
                st.error("Pick the finding this verdict rests on.")
            elif not note.strip():
                st.error("Give a reason.")
            else:
                rc.set_manual(check, "case", c["case_id"], status, ids if status in rc.LINKING else [], note.strip(),
                              rc.case_hash(c, context.block_for_case(c)))
                st.rerun()
    if row["manual"] and st.button("Go back to the model's verdict", key=f"back_{c['case_id']}"):
        rc.clear_manual(check, "case", c["case_id"])
        st.rerun()
    with st.expander("The ground truth is wrong here"):
        with st.form(f"fix_{c['case_id']}"):
            what = st.text_input("What is wrong")
            corrected = st.text_input("The corrected value or label")
            why = st.text_input("Reason")
            if st.form_submit_button("Store the correction request"):
                if not (what.strip() and corrected.strip() and why.strip()):
                    st.error("Fill in all three fields.")
                else:
                    library.add_correction(c["case_id"], c["data_room"], what.strip(), corrected.strip(), why.strip(), check["check_id"])
                    st.success("Stored with the pending rows. The case changes only when the corrected sheet is uploaded.")


def newly_mapped(check: dict, res: dict, chunks: dict, by_f: dict):
    st.subheader("Newly mapped")
    new = res["new"]
    st.write("Findings that map to no ground-truth case.")
    cols = ["finding_id", "summary", "severity_given", "severity_judged", "documents", "precheck", "status", "explanation"]
    frame = lambda rows: pd.DataFrame([{**{k: r[k] for k in cols}, "documents": ", ".join(r["documents"])} for r in rows])
    cands = [n for n in new if n["band"] == rc.CANDIDATE]
    review = [n for n in new if n["band"] in (rc.REVIEW, "Not checked")]
    rejected = [n for n in new if n["band"] == rc.REJECTED_RULE]
    by_hand = [n for n in new if n["band"] == rc.REJECTED_EVALUATOR]

    st.markdown(f"**Candidates for the ground truth ({len(cands)})**")
    if cands:
        st.dataframe(frame(cands), hide_index=True, width="stretch")
    st.markdown(f"**Needs review ({len(review)})**")
    if review:
        st.caption("The rule and the judge disagree, or the judge could not decide.")
        st.dataframe(frame(review).assign(why=[n["reason"] for n in review]), hide_index=True, width="stretch")
    if cands or review:
        fid = st.selectbox("Open a finding for review", [n["finding_id"] for n in cands + review],
                           format_func=lambda i: f"{i} · {by_f[i]['summary'][:80]}", key=f"rc_cand_{check['check_id']}")
        candidate_review(check, fid, chunks, by_f)
    with st.expander(f"Rejected by rules ({len(rejected)})"):
        if rejected:
            st.dataframe(pd.DataFrame([{"Finding": n["finding_id"], "Summary": n["summary"],
                                        "Rule": context.rule_name(n["rule_id"]), "Reason": n["reason"]} for n in rejected]),
                         hide_index=True, width="stretch")
            with st.form(f"restore_{check['check_id']}"):
                fid = st.selectbox("Restore a finding to Needs review", [n["finding_id"] for n in rejected])
                why = st.text_input("Why the rule is wrong here")
                if st.form_submit_button("Restore"):
                    if not why.strip():
                        st.error("Give a reason.")
                    else:
                        rc.restore(check, fid, why.strip())
                        st.rerun()
        else:
            st.write("Nothing was rejected by a rule.")
    if by_hand:
        with st.expander(f"Rejected by the evaluator ({len(by_hand)})"):
            st.dataframe(pd.DataFrame([{"Finding": n["finding_id"], "Summary": n["summary"], "Reason": n["note"]} for n in by_hand]),
                         hide_index=True, width="stretch")
            fid = st.selectbox("Undo a rejection", [n["finding_id"] for n in by_hand], key=f"rc_undo_{check['check_id']}")
            if st.button("Undo"):
                rc.clear_manual(check, "finding", fid)
                st.rerun()


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
    lines = rc.checklist(check, fid, cases, store.load_runs())
    st.dataframe(pd.DataFrame([{"Check": x["check"], "Result": RESULT_MARK[x["result"]], "Why": x["reason"]} for x in lines]),
                 hide_index=True, width="stretch")
    near = rc.closest_cases(check, fid, cases)
    for n in near:
        with st.expander(f"Closest case {n['case_id']} · score {n['score']:.2f}"):
            case_card(case_by_id[n["case_id"]])

    st.markdown("**4. For and against (the model's view)**")
    st.write(f"For: {v.get('why_it_matters') or 'nothing given.'}")
    st.write(f"Against: {v.get('why_it_might_not') or 'nothing given.'}")
    if v.get("precheck"):
        st.caption(f"Rule pre-check: {v['precheck']['tag']} ({v['precheck']['rule_id']}). {v['precheck']['reason']}")

    st.markdown("**5. The decision**")
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
# Upload evaluation sheet
def screen_upload():
    st.header("Upload evaluation sheet")
    st.write("The Google Sheet stays the place where cases, facts, documents, rules and baseline runs are written. "
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


# ---------------------------------------------------------------------------------------------------
# Rules and facts
def screen_rules():
    st.header("Rules and facts")
    st.write("What the tool knows about a data room besides its documents. Rules and facts are changed in the sheet "
             "and uploaded; this screen only shows them.")
    rules = context.load_rules()
    counts: dict[str, int] = {}
    for meta in rc.list_checks():
        chk = rc.load_check(meta["check_id"]) or {}
        for fid, v in (chk.get("new_verdicts") or {}).items():
            g = v.get("gate") or {}
            if g.get("outcome") == rc.REJECTED_RULE and f"finding::{fid}" not in chk.get("manual", {}):
                counts[g.get("rule_id")] = counts.get(g.get("rule_id"), 0) + 1
    st.subheader("The rule bundle")
    st.caption("Reject: a finding outside the ground truth that the rule excuses is rejected. Flag: the rule makes "
               "something a real issue, and such a finding is never rejected automatically. Guide: helps the model "
               "read, decides nothing alone.")
    st.dataframe(pd.DataFrame([{"Rule": r["rule_id"], "Name": r["name"], "Type": r["type"], "Critical": "Yes" if r.get("critical") else "No",
                                "On": "Yes" if r.get("on", True) else "No", "Expected class": r.get("expected_class"),
                                "Findings rejected": counts.get(r["rule_id"], 0), "Rule text": r["text"]} for r in rules]),
                 hide_index=True, width="stretch")

    st.subheader("Coverage by test cases")
    st.caption("A case is a test case for a rule when its scenario tags name the rule ID. A critical Reject rule needs "
               "a non-issue case in every data room, a critical Flag rule a reportable one.")
    cov = [r for r in context.coverage(cases, rules) if room == "All" or r["data_room"] == room]
    st.dataframe(pd.DataFrame([{"Rule": f"{r['rule_id']} {r['name']}", "Type": r["type"], "Data room": r["data_room"],
                                "Reportable cases": r["reportable"], "Non-issue cases": r["non_issue"],
                                "Gap": f"⚠️ needs {r['needs']}" if r["gap"] else ""} for r in cov]), hide_index=True, width="stretch")

    st.subheader("The fact sheet")
    facts = [f for f in context.load_facts() if room == "All" or f["data_room"] == room]
    if not facts:
        st.info("No fact is stored yet. Add the Fact Sheet tab to the evaluation sheet (the template on the Upload "
                "evaluation sheet screen has its columns) and upload it.")
        return
    st.dataframe(pd.DataFrame([{"Fact": f["fact_id"], "Data room": f["data_room"], "Subject": f["subject"], "Scope": f["scope"],
                                "Value": f["value"], "Unit or basis": f["unit_basis"], "Status": f["value_status"],
                                "As of": f["as_of"], "Source": context._src_text(f["source"]), "Supersedes": f["supersedes"]}
                               for f in facts]), hide_index=True, width="stretch")
    pick = st.selectbox("Change chain of a fact", facts, format_func=lambda f: f"{f['data_room']} {f['fact_id']} · {f['subject']} · {f['value']}")
    st.write(context.chain_text(pick, context.load_facts(pick["data_room"])))


# ---------------------------------------------------------------------------------------------------
if page == "Vericap run check":
    screen_run_check()
elif page == "Upload evaluation sheet":
    screen_upload()
elif page == "Rules and facts":
    screen_rules()
elif page == "Overview":
    st.header("Overview")
    st.write("Headline: severity-weighted recall on the withheld set. All runs use the same matching, metrics and "
             "answer key.")
    if not in_room:
        no_runs()
    df = pd.DataFrame(report.score_row(r) for r in in_room).sort_values(
        ["Data room", "Weighted recall"], ascending=[True, False])
    st.subheader("Every run")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "Weighted recall": BAR, "Recall": PCT, "Precision": PCT, "Class accuracy": PCT, "Severity accuracy": PCT,
        "Evidence sufficient": PCT, "Reasoning (0-2)": st.column_config.NumberColumn(format="%.2f"),
        "Cost (USD)": st.column_config.NumberColumn(format="$%.2f")})

    st.subheader("Systems, averaged over repeated runs")
    rows = []
    for key, g in compare.groups(in_room).items():
        a, rel = compare.averaged(g), compare.reliability(g)
        rows.append({"System": compare.group_label(key), "Source": g[0]["run"]["source"], "Runs": len(g),
                     "Weighted recall": a["weighted_recall"], "Lowest run": rel["weighted_recall_min"],
                     "Highest run": rel["weighted_recall_max"], "Precision": a["precision"],
                     "Class accuracy": a["class_accuracy"], "Critical missed (avg)": a["critical_missed"],
                     "False positives (avg)": a["false_positives"], "Minutes (avg)": a["duration_minutes"],
                     "Cost per valid finding": a["cost_per_valid_finding"]})
    st.dataframe(pd.DataFrame(rows).sort_values("Weighted recall", ascending=False), hide_index=True,
                 width="stretch", column_config={"Weighted recall": BAR, "Lowest run": PCT, "Highest run": PCT,
                                                          "Precision": PCT, "Class accuracy": PCT})

    st.subheader("Coverage of the answer key")
    lib = [c for c in cases if room == "All" or c["data_room"] == room]
    grid = pd.crosstab(pd.Series([c["classification"] for c in lib], name="Class"),
                       pd.Series([c["severity"] for c in lib], name="Severity")).reindex(
        index=contract.CLASSES, columns=contract.SEVERITIES, fill_value=0)
    c1, c2 = st.columns(2)
    c1.caption("Cases by class and severity. A zero is a gap in the map.")
    c1.dataframe(grid, width="stretch")
    sets = pd.crosstab(pd.Series([c["set"] for c in lib], name="Set"),
                       pd.Series(["Report" if c["report"] else "Do not report" for c in lib], name=""))
    c2.caption("Cases by set")
    c2.dataframe(sets, width="stretch")
    with open(store.REPORTS / "report.md", "rb") if (store.REPORTS / "report.md").exists() else open(report.write(results)[0], "rb") as fh:
        st.download_button("Download the written report", fh.read(), "report.md")

# ---------------------------------------------------------------------------------------------------
elif page == "Run detail":
    res = pick_run()
    m, info = res["metrics"], res["run"]
    st.header(info["run_id"])
    st.caption(f"{info['source']} · {info['system']} {info['version']} · {info['data_room']} · model {info['model'] or '-'}")
    if info.get("notes"):
        st.caption(info["notes"])
    k = st.columns(6)
    k[0].metric("Weighted recall", report.pct(m["weighted_recall"]), f"{m['weighted_found']} of {m['weighted_possible']} points", delta_color="off")
    k[1].metric("Recall", report.pct(m["recall"]), f"{m['found']} of {m['reportable']} cases", delta_color="off")
    k[2].metric("Critical missed", m["critical_missed"])
    k[3].metric("Precision", report.pct(m["precision"]), f"{m['findings']} findings", delta_color="off")
    k[4].metric("False positives", m["false_positives"])
    k[5].metric("Class accuracy", report.pct(m["class_accuracy"]))
    st.caption(f"Development set: weighted recall {report.pct(m['development']['weighted_recall'])}. "
               f"Withheld without ambiguous cases: {report.pct(m['withheld_clear_cases']['weighted_recall'])}. "
               f"{m['needs_review']} findings wait for a manual decision; until decided they count as findings but "
               f"not as valid ones.")
    if res["problems"]:
        with st.expander(f"Contract problems ({len(res['problems'])})"):
            st.write("\n".join(f"- {p}" for p in res["problems"]))

    t_det, t_find, t_cls, t_ev, t_cov = st.tabs(["Detection", "Findings", "Classification", "Evidence", "Coverage"])
    with t_det:
        cdf = pd.DataFrame(res["cases"])
        show = st.multiselect("Outcome", ["Missed", "False alarm", "Found", "Correct"], default=["Missed", "False alarm"])
        cdf = cdf[cdf["outcome"].isin(show)].sort_values(["outcome", "weight"], ascending=[True, False])
        st.dataframe(cdf[["case_id", "outcome", "expected_class", "expected_severity", "set", "summary", "finding_id",
                          "class", "severity", "evidence", "reasoning", "points"]], hide_index=True,
                     width="stretch")
        fp = [r for r in res["rows"] if r["status"] in ("False positive candidate", "Needs review")]
        st.subheader("Findings with no confirmed case")
        st.dataframe(pd.DataFrame(fp)[["finding_id", "status", "classification", "severity", "summary"]] if fp
                     else pd.DataFrame(columns=["finding_id"]), hide_index=True, width="stretch")
    with t_find:
        fdf = pd.DataFrame(res["rows"])
        st.dataframe(fdf[["finding_id", "status", "decided", "case_id", "score", "classification", "expected_class",
                          "severity", "expected_severity", "evidence", "reasoning", "summary", "note"]],
                     hide_index=True, width="stretch")
        fid = st.selectbox("Open a finding", [f["finding_id"] for f in next(
            r for r in store.load_runs() if r["run"]["run_id"] == info["run_id"])["findings"]])
        f = next(x for x in next(r for r in store.load_runs() if r["run"]["run_id"] == info["run_id"])["findings"]
                 if x["finding_id"] == fid)
        a, b = st.columns(2)
        with a:
            finding_card(f)
        with b:
            linked = [r["case_id"] for r in res["rows"] if r["finding_id"] == fid and r["case_id"]]
            for cid in linked:
                case_card(case_by_id[cid])
            if not linked:
                st.info("No case linked.")
    with t_cls:
        st.caption("Rows: expected class. Columns: class the run reported. Matched findings only.")
        st.dataframe(pd.DataFrame(scoring.confusion(res)).T, width="stretch")
        wrong = [r for r in res["rows"] if r["status"] == "Match" and r["class_correct"] is False]
        if wrong:
            st.dataframe(pd.DataFrame(wrong)[["finding_id", "case_id", "expected_class", "classification", "summary"]],
                         hide_index=True, width="stretch")
    with t_ev:
        st.caption("Relevant: share of the finding's citations that point at pages the answer key cites. "
                   "Sufficient (rule): every document the case rests on is cited. A manual check replaces the rule. "
                   "Real: needs the document text in data_room/.")
        ev = pd.DataFrame([r for r in res["rows"] if r["case_id"]])
        if len(ev):
            st.dataframe(ev[["finding_id", "case_id", "evidence", "evidence_rule", "relevant_share", "real_share",
                             "invented", "reasoning"]].rename(columns={"invented": "quotes_not_found"}), hide_index=True, width="stretch",
                         column_config={"relevant_share": PCT, "real_share": PCT})
        if m["quotes_real"] is None:
            st.info(f"No document text is stored for {info['data_room']}, so quotes were not checked against the "
                    f"documents.")
    with t_cov:
        dim = st.selectbox("Break down by", ["severity", "class", "check_type", "scenario", "set", "doc_type", "doc_format"])
        st.dataframe(pd.DataFrame(scoring.breakdown(res, dim, documents)), hide_index=True, width="stretch",
                     column_config={"recall": BAR, "weighted_recall": PCT, "class_accuracy": PCT})

# ---------------------------------------------------------------------------------------------------
elif page == "Review queue":
    st.header("Review queue")
    st.write("Findings the rules could not place with confidence. A decision saved here overrides the automatic "
             "match and is kept in reviews/decisions.json.")
    res = pick_run()
    rid = res["run"]["run_id"]
    run = next(r for r in store.load_runs() if r["run"]["run_id"] == rid)
    only_open = st.checkbox("Only findings that need a decision", value=True)
    first = {}
    for r in res["rows"]:
        first.setdefault(r["finding_id"], r)
    queue = [f for f in run["findings"] if not only_open or first[f["finding_id"]]["status"] in
             ("Needs review", "False positive candidate")]
    if not queue:
        st.success("Nothing waiting for this run.")
        st.stop()
    fid = st.selectbox("Finding", [f["finding_id"] for f in queue],
                       format_func=lambda x: f"{x} · {first[x]['status']} · {first[x]['decided']}")
    f = next(x for x in queue if x["finding_id"] == fid)
    row = first[fid]
    review_panel(res, f, row)

# ---------------------------------------------------------------------------------------------------
elif page == "Judge versus rules":
    st.header("Judge versus rules")
    st.write("Every finding is placed twice: by the fixed rules and by the LLM judge. The judge also gives the evidence "
             "check and the reasoning score. Where the two differ, or the judge's own safeguards trip, you decide, and "
             "your decision is what the headline score uses.")
    res = pick_run()
    rid = res["run"]["run_id"]
    run = next(r for r in store.load_runs() if r["run"]["run_id"] == rid)
    verdicts, reviews = judge.load_verdicts(), store.load_reviews()
    cmp_ = judge.compare_run(run, cases, reviews, verdicts)
    st.caption(f"Judge: {judge.judge_label()}. Judged {cmp_['judged']} of {cmp_['findings']} findings in this run.")
    if cmp_["judged"] < cmp_["findings"]:
        if st.button(f"Run the judge on the {cmp_['findings'] - cmp_['judged']} findings not judged yet"):
            bar = st.progress(0.0)
            try:
                out = judge.judge_run(run, cases, progress=lambda i, n: bar.progress(i / n))
                st.cache_data.clear()
                if out["stopped"]:
                    st.warning(f"Stopped with {out['left']} findings left: {out['stopped']} What was judged is saved; press the button again later.")
                else:
                    st.rerun()
            except judge.JudgeUnavailable as e:
                st.error(f"The judge could not run: {e}")
    if not cmp_["judged"]:
        st.info("No verdicts for this run yet.")
        st.stop()
    b = judge.score_run(run, cases, verdicts)
    pure = scoring.score_run({**run, "run": {**run["run"], "problems": []}}, cases, {})
    keys = [("Weighted recall", "weighted_recall", True), ("Recall", "recall", True), ("Precision", "precision", True),
            ("False positives", "false_positives", False), ("Class accuracy", "class_accuracy", True),
            ("Evidence sufficient", "evidence_sufficient", True), ("Reasoning (0-2)", "reasoning_avg", False),
            ("Waiting for a decision", "needs_review", False)]
    fmt = lambda v, p: report.pct(v) if p else report.num(v)
    st.dataframe(pd.DataFrame([{"Metric": n, "Headline (rules + manual)": fmt(res["metrics"][k], p),
                                "Rules alone": fmt(pure["metrics"][k], p), "Judge alone": fmt(b["metrics"][k], p)}
                               for n, k, p in keys]), hide_index=True, width="stretch")
    rows = pd.DataFrame(cmp_["rows"])
    view = st.radio("Show", ["Disagreements and findings sent to manual review", "All findings"], horizontal=True)
    if view.startswith("Dis"):
        rows = rows[(rows["agree"] == False) | rows["needs_manual"]]  # noqa: E712
    st.dataframe(rows[["finding_id", "rules_status", "rules_cases", "judge_status", "judge_cases", "manual_status",
                       "manual_cases", "judge_evidence", "judge_reasoning", "stable", "reasons", "summary"]],
                 hide_index=True, width="stretch")
    if len(rows):
        fid = st.selectbox("Open a finding and decide", list(rows["finding_id"]))
        f = next(x for x in run["findings"] if x["finding_id"] == fid)
        row = next(r for r in res["rows"] if r["finding_id"] == fid)
        review_panel(res, f, row, verdicts.get(store.review_key(rid, fid)))
    else:
        st.success("Rules and judge agree on every judged finding of this run.")

# ---------------------------------------------------------------------------------------------------
elif page == "Reliability":
    st.header("Reliability")
    st.write("Repeated runs of the same system, version and data room. A case found in only some runs is unstable.")
    grp = compare.groups(in_room)
    if not grp:
        no_runs()
    keys = sorted(grp, key=lambda k: -len(grp[k]))
    key = st.selectbox("System", keys, format_func=lambda k: f"{compare.group_label(k)} · {len(grp[k])} run(s)")
    rel = compare.reliability(grp[key])
    if rel["runs"] < 2:
        st.warning("Only one run for this system. Reliability needs at least two runs with nothing changed between them.")
    k = st.columns(5)
    k[0].metric("Runs", rel["runs"])
    k[1].metric("Found in every run", rel["found_every_run"])
    k[2].metric("Found in some runs", rel["found_some_runs"])
    k[3].metric("Found in no run", rel["found_no_run"])
    k[4].metric("Weighted recall, low to high", f"{report.pct(rel['weighted_recall_min'])} to {report.pct(rel['weighted_recall_max'])}")
    st.caption("Runs: " + ", ".join(rel["run_ids"]) + ". Counts are for the withheld set.")
    st.dataframe(pd.DataFrame(rel["cases"]).sort_values(["stability", "severity"]), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------------------------------
elif page == "Compare":
    st.header("Compare two systems")
    st.write("Same data room, same answer key. A system counts as having found a case when it finds it in more than "
             "half of its runs. \"Better\" means weighted recall rises and no Critical case found before is now missed.")
    if not show_baselines:
        st.caption(BASELINE_HINT)
    grp = compare.groups(in_room)
    keys = sorted(grp, key=lambda k: (grp[k][0]["run"]["source"] != "Our system", k))
    if len(keys) < 2:
        st.info("Two systems are needed.")
        st.stop()
    c1, c2 = st.columns(2)
    a = c1.selectbox("New or our system", keys, format_func=compare.group_label)
    others = [k for k in keys if k != a and k[2] == a[2]]
    if not others:
        st.info("No other system has runs on this data room.")
        st.stop()
    b = c2.selectbox("Compared with", others, format_func=compare.group_label)
    cmp = compare.compare(grp[a], grp[b])
    (st.success if cmp["improved"] else st.warning)(
        f"{compare.group_label(a)} is {'better' if cmp['improved'] else 'not better'} than {compare.group_label(b)}: "
        f"weighted recall {report.pct(cmp['new']['weighted_recall'])} against {report.pct(cmp['old']['weighted_recall'])}, "
        f"{len(cmp['gained'])} cases gained, {len(cmp['lost'])} lost"
        + (f", Critical lost: {', '.join(cmp['lost_critical'])}." if cmp["lost_critical"] else "."))
    side = pd.DataFrame({compare.group_label(a): cmp["new"], compare.group_label(b): cmp["old"]})
    st.dataframe(side, width="stretch")
    cdf = pd.DataFrame(cmp["cases"])
    show = st.multiselect("Show", ["Gained", "Lost", "Both missed", "Both found"], default=["Gained", "Lost", "Both missed"])
    st.dataframe(cdf[cdf["change"].isin(show)].rename(columns={"new": compare.group_label(a), "old": compare.group_label(b)}),
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------------------------------------------
elif page == "Add a run":
    st.header("Add a run")
    st.write("Upload the JSON file produced by the discrepancy checker or converted from a baseline model's reply. "
             "The file is checked against the output contract, stored in submissions/ and scored.")
    up = st.file_uploader("Run file (.json)", type="json")
    allow = st.checkbox("Store the run even if it breaks the contract (baseline replies only)")
    if up is not None and st.button("Check, store and score"):
        try:
            payload = json.loads(up.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            st.error(f"Not valid JSON: {e}")
            st.stop()
        status, body = api.submit(payload, allow_problems=allow)
        if body.get("accepted"):
            st.cache_data.clear()
            st.success(f"Stored as {body['stored_as']}. Weighted recall "
                       f"{report.pct(body['scores_withheld_set']['weighted_recall'])}. Open it under Run detail.")
        else:
            st.error(body.get("message") or "Rejected.")
        if body.get("contract_problems"):
            st.write("\n".join(f"- {p}" for p in body["contract_problems"]))
    st.subheader("File format")
    st.code(contract.__doc__.split("One run is one JSON file:")[1].strip(), language="json")
    example = store.ROOT / "examples" / "example_run.json"
    if example.exists():
        st.download_button("Download an example file", example.read_bytes(), "example_run.json")
    st.subheader("Sending runs without the app")
    st.code("python -m eval submit path/to/run.json\n\n"
            "python -m eval serve --port 8000\n"
            "curl -X POST http://127.0.0.1:8000/runs -H 'Content-Type: application/json' -d @path/to/run.json", language="bash")

# ---------------------------------------------------------------------------------------------------
elif page == "Method check":
    st.header("How far the automatic matching can be trusted")
    agree = compare.matcher_agreement(store.load_runs(), cases, store.load_reviews())
    if not agree["decided_by_hand"]:
        st.info("No manual decisions are stored yet.")
    k = st.columns(3)
    k[0].metric("Findings with a case chosen by hand", agree["decided_by_hand"])
    k[1].metric("Rules chose the same case", agree["same_case"])
    k[2].metric("Agreement", report.pct(agree["agreement"]))
    st.write("The matcher is run here with every manual decision switched off, then compared with those decisions. "
             "The thresholds were set on these same findings, so read this as agreement on known data.")
    st.dataframe(pd.DataFrame([{"Outcome": o, "Findings": n} for o, n in sorted(agree["outcomes"].items())]),
                 hide_index=True, width="stretch")
    if agree["disagreements"]:
        st.subheader("Where rules and manual decision differ")
        st.dataframe(pd.DataFrame(agree["disagreements"]), hide_index=True, width="stretch")

    st.header("How far the judge can be trusted")
    verdicts = judge.load_verdicts()
    if not verdicts:
        st.info("The judge has not been run yet. Use the Judge versus rules screen, or: python -m eval judge")
    else:
        t = judge.trust(store.load_runs(), cases, store.load_reviews(), verdicts)
        st.dataframe(pd.DataFrame([
            {"Check": "Rules and judge pick the same case", "Rate": report.pct(t["rules_and_judge_agree"][0]), "Findings": t["rules_and_judge_agree"][1]},
            {"Check": "Judge picks the case chosen by hand", "Rate": report.pct(t["judge_matches_manual"][0]), "Findings": t["judge_matches_manual"][1]},
            {"Check": "Rules pick the case chosen by hand, same findings", "Rate": report.pct(t["rules_match_manual_same_findings"][0]), "Findings": t["rules_match_manual_same_findings"][1]},
            {"Check": "Judge gives the evidence check given by hand", "Rate": report.pct(t["evidence_matches_manual"][0]), "Findings": t["evidence_matches_manual"][1]},
            {"Check": "Judge gives the reasoning score given by hand", "Rate": report.pct(t["reasoning_matches_manual"][0]), "Findings": t["reasoning_matches_manual"][1]},
        ]), hide_index=True, width="stretch")
        st.caption(f"{t['judged']} findings judged. {t['unstable']} verdicts changed between the two passes. "
                   f"{t['needs_manual']} sent to manual review. Where rules and judge differed and a manual decision "
                   f"exists, the judge alone was right {t['only_judge_right']} times, the rules alone {t['only_rules_right']} times.")

    st.header("Answer key quotes against the documents")
    for rm in rooms:
        k = data_room.check_answer_key(rm)
        if not k["checked"]:
            st.write(f"{rm}: no document text stored.")
            continue
        st.write(f"{rm}: {k['real']} of {k['checked']} quoted passages found in the documents.")
        bad = k["not_found"] + k["wrong_page"]
        if bad:
            st.dataframe(pd.DataFrame(bad), hide_index=True, width="stretch")
