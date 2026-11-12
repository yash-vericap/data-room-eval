"""Streamlit view of the evaluation results.   streamlit run app.py"""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import os

from eval import api, compare, contract, data_room, judge, report, scoring, store

st.set_page_config(page_title="Data room evaluation", layout="wide")

PCT = st.column_config.NumberColumn(format="percent")
BAR = st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)
STATUSES = ["Match", "Duplicate", "False positive candidate", "Needs review"]
EVIDENCE = ["Sufficient", "Partial", "Not supported"]


def _stamp() -> float:
    files = (list(store.SUBMISSIONS.rglob("*.json")) + list(store.ANSWER_KEY.glob("*.json")) + [store.REVIEWS, judge.VERDICTS]
             + list(store.DATA_ROOM.glob("*/chunks.json")))
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


@st.cache_data(show_spinner="Scoring runs...")
def load(stamp: float):
    return scoring.score_all(), store.load_cases(), store.load_documents()


if os.environ.get("EVAL_APP_PASSWORD") and not st.session_state.get("signed_in"):
    st.title("Data room evaluation")
    if st.text_input("Password", type="password") == os.environ["EVAL_APP_PASSWORD"]:
        st.session_state["signed_in"] = True
        st.rerun()
    st.stop()

results, cases, documents = load(_stamp())
case_by_id = {c["case_id"]: c for c in cases}
by_run = {r["run"]["run_id"]: r for r in results}
rooms = sorted({c["data_room"] for c in cases})

st.sidebar.title("Data room evaluation")
page = st.sidebar.radio("Screen", ["Overview", "Run detail", "Review queue", "Judge versus rules", "Reliability",
                                   "Compare", "Add a run", "Method check"])
room = st.sidebar.selectbox("Data room", ["All"] + rooms)
st.sidebar.caption(f"Answer key: {cases[0]['snapshot']}, {len(cases)} cases. {len(results)} runs stored.")
in_room = [r for r in results if room == "All" or r["run"]["data_room"] == room]


def pick_run(label="Run", key="run"):
    ids = [r["run"]["run_id"] for r in sorted(in_room, key=lambda r: -(r["metrics"]["weighted_recall"] or 0))]
    if not ids:
        st.info("No run stored for this data room.")
        st.stop()
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
if page == "Overview":
    st.header("Overview")
    st.write("Headline: severity-weighted recall on the withheld set. All runs use the same matching, metrics and "
             "answer key.")
    if not in_room:
        st.info("No run stored for this data room.")
        st.stop()
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
        st.info("No run stored for this data room.")
        st.stop()
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
