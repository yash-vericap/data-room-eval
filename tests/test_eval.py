"""Checks on the parts that decide a score. Run with: python -m pytest -q"""
from eval import compare, contract, matching, scoring
from eval.matching import key_values


def case(cid, cls, sev, report, docs, citations, claims, summary, set_="Withheld", ambiguous=False):
    return {"case_id": cid, "data_room": "T1", "classification": cls, "severity": sev, "weight": contract.WEIGHTS[sev],
            "report": report, "set": set_, "summary": summary, "claims_compared": claims,
            "citations": contract.parse_citations(citations), "explanation": summary, "check_type": "Wrong number",
            "documents": docs, "ambiguous": ambiguous, "scenario_tags": ["Units"]}


CASES = [
    case("T1-001", "Contradiction", "Critical", True, ["DOC-05", "DOC-06"],
         'DOC-05 p.2, 2.3: "$5,120,000"\nDOC-06 p.3, 5: "$4,920,000"',
         "DOC-05 shows a federal credit of $5,120,000. DOC-06 gives the credit as $4,920,000.",
         "Federal credit in the financial model does not match the QRE"),
    case("T1-002", "Contextual difference", "Medium", False, ["DOC-12", "DOC-13"],
         'DOC-12 p.3, Section 2.1: "$0.82 per $1.00 of credit"\nDOC-13 p.3, Section 2.1: "$0.85 per $1.00 of credit"',
         "DOC-12, signed, sets the price at $0.82. DOC-13, an unsigned later draft, shows $0.85.",
         "Signed and draft purchase agreements give different prices"),
    case("T1-003", "Contradiction", "High", True, ["DOC-04", "DOC-11"],
         'DOC-04 p.2, line 40: "$2,750,000"\nDOC-11 p.18, Section 6.3: "shall not exceed $2,500,000"',
         "DOC-04 shows a developer fee of $2,750,000. DOC-11 caps the fee at $2,500,000.",
         "Developer fee in the budget is above the operating agreement cap"),
]


def finding(fid, cls, sev, summary, claims, citations):
    return {"finding_id": fid, "classification": cls, "severity": sev, "summary": summary, "claims_compared": claims,
            "citations": contract.parse_citations(citations), "explanation": summary, "confidence": 0.9}


F_CREDIT = finding("F1", "Contradiction", "High", "Model overstates the federal tax credit against the cost certification",
                   "Model credit $5.12M; certification credit $4.92M",
                   "DOC-05 p.2, 2.3: 'Federal historic tax credit: $5,120,000' || DOC-06 p.3, 5: 'credit: $4,920,000'")
F_DRAFT = finding("F2", "Contradiction", "High", "Signed agreement and draft agreement show different credit prices",
                  "DOC-12 price 0.82, DOC-13 price 0.85",
                  "DOC-12 p.3, 2.1: 'pay $0.82 per $1.00 of credit' || DOC-13 p.3, 2.1: 'pay $0.85 per $1.00 of credit'")
F_NOISE = finding("F3", "Contradiction", "Low", "Insurance premium differs between two schedules",
                  "Premium $96,000 against $104,000", "DOC-03 p.19, 2: 'insurance of roughly $104,000'")


def run(findings, rid="R1", system="S", version="v1"):
    return {"run": {"run_id": rid, "data_room": "T1", "source": "Our system", "system": system, "version": version},
            "findings": findings, "problems": []}


def test_citation_parsing():
    c = contract.parse_citations("DOC-05 p.2, 2.3: \"$5,120,000\"\nDOC-05 slide 15: 'QRE $39,800,000' || DOC-08 p.9: 'x'")
    assert [(x["doc_id"], x["page"]) for x in c] == [("DOC-05", 2), ("DOC-05", 15), ("DOC-08", 9)]
    assert c[0]["location"] == "2.3" and c[0]["quote"] == "$5,120,000"


def test_same_value_in_different_formats():
    assert key_values("$24,600,000") & key_values("$24.6M") & key_values("24,600 ($ in thousands)")
    assert key_values("July 15, 2025") & key_values("7/15/2025")
    assert key_values("85 cents") & key_values("$0.85")
    assert not (key_values("DOC-05 p.2, Section 2.3") - set())      # references are not values


def test_contract_rejects_wrong_labels_and_missing_quotes():
    _, problems = contract.normalise({"run": {"run_id": "x", "data_room": "T1"}, "findings": [
        {"finding_id": "F1", "classification": "Conflict", "severity": "Critical", "summary": "s",
         "citations": [{"doc_id": "DOC-01", "page": 1}]}]})
    assert any("classification" in p for p in problems) and any("no quoted text" in p for p in problems)
    _, ok = contract.normalise({"run": {"run_id": "x", "data_room": "T1"}, "findings": [
        {"finding_id": "F1", "classification": "contradiction", "severity": "critical", "summary": "s",
         "citations": [{"doc_id": "DOC-01", "page": 1, "quote": "q"}]}]})
    assert ok == []


def test_matching_and_metrics():
    res = scoring.score_run(run([F_CREDIT, F_DRAFT, F_NOISE]), CASES, reviews={}, chunks={})
    status = {r["finding_id"]: (r["status"], r["case_id"]) for r in res["rows"]}
    assert status["F1"] == ("Match", "T1-001")
    assert status["F2"] == ("Match", "T1-002")
    assert status["F3"][0] == "False positive candidate"
    m = res["metrics"]
    assert (m["reportable"], m["found"]) == (2, 1)
    assert m["weighted_recall"] == 8 / 12                      # Critical found, High missed
    assert m["critical_missed"] == 0 and m["missed"] == ["T1-003"]
    assert m["false_positives"] == 2                           # the stray finding and the negative case called a contradiction
    assert m["precision"] == 1 / 3
    assert m["severity_accuracy"] == 0.0 and m["class_accuracy"] == 0.5


def test_negative_case_with_the_right_label_is_not_a_false_positive():
    ok = dict(F_DRAFT, classification="Contextual difference")
    res = scoring.score_run(run([ok]), CASES, reviews={}, chunks={})
    assert res["metrics"]["false_positives"] == 0 and res["metrics"]["precision"] == 1.0


def test_duplicates_count_once_and_manual_decision_wins():
    again = dict(F_CREDIT, finding_id="F9")
    res = scoring.score_run(run([F_CREDIT, again]), CASES, reviews={}, chunks={})
    assert sorted(r["status"] for r in res["rows"]) == ["Duplicate", "Match"]
    assert res["metrics"]["findings"] == 1 and res["metrics"]["false_positives"] == 0
    reviews = {"R1::F3": {"status": "Match", "case_ids": ["T1-003"], "evidence": "Partial", "reasoning": 1, "note": "n"}}
    res = scoring.score_run(run([F_NOISE]), CASES, reviews=reviews, chunks={})
    assert res["metrics"]["found"] == 1 and res["rows"][0]["decided"] == "manual" and res["rows"][0]["evidence"] == "Partial"


def test_quote_check_needs_document_text():
    chunks = {"DOC-05": {2: "2.3 Federal historic tax credit: $5,120,000"}, "DOC-06": {3: "nothing relevant here"}}
    res = scoring.score_run(run([F_CREDIT]), CASES, reviews={}, chunks=chunks)
    assert res["rows"][0]["real"] == ["Real", "Not found"] and res["metrics"]["invented_citations"] == 1
    assert scoring.score_run(run([F_CREDIT]), CASES, reviews={}, chunks={})["metrics"]["quotes_real"] is None


def test_improved_needs_higher_recall_and_no_lost_critical():
    old = [scoring.score_run(run([F_CREDIT], "old", version="v1"), CASES, {}, {})]
    fee = finding("F4", "Contradiction", "High", "Developer fee exceeds the cap in the operating agreement",
                  "Budget fee $2,750,000; cap $2,500,000",
                  "DOC-04 p.2, line 40: '$2,750,000' || DOC-11 p.18, 6.3: 'shall not exceed $2,500,000'")
    better = [scoring.score_run(run([F_CREDIT, fee], "new", version="v2"), CASES, {}, {})]
    lost = [scoring.score_run(run([fee], "new2", version="v3"), CASES, {}, {})]
    assert compare.compare(better, old)["improved"] is True
    c = compare.compare(lost, old)
    assert c["improved"] is False and c["lost_critical"] == ["T1-001"]
    rel = compare.reliability(old + better)
    assert rel["found_every_run"] == 1 and rel["found_some_runs"] == 1


# ---- LLM judge, with a stand-in for the model ------------------------------------------------------
import json as _json

from eval import judge


class FakeClient:
    """Answers like the judge client would. `script` maps a finding ID to the verdicts to return, in order."""

    def __init__(self, script):
        self.script, self.calls = {k: list(v) for k, v in script.items()}, 0

    def complete(self, model, system, message, schema):
        self.calls += 1
        assert system == judge.SYSTEM and schema == judge.SCHEMA
        fid = message.split("ID: ")[1].split("\n")[0]
        queue = self.script[fid]
        v = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"verdict": _json.loads(_json.dumps(v)), "error": None, "input_tokens": 1000, "output_tokens": 100}


def verdict(match="yes", ids=("T1-001",), quote="$5,120,000", **kw):
    return {"match": match, "case_ids": list(ids), "class_correct": "yes", "evidence": "Sufficient",
            "reasoning_score": "2", "disagrees_with_answer_key": "no", "quote": quote, "explanation": "e", **kw}


def test_judge_verdict_becomes_a_scored_result(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "VERDICTS", tmp_path / "verdicts.json")
    r = run([F_CREDIT, F_NOISE])
    client = FakeClient({"F1": [verdict()], "F3": [verdict("no", (), quote="insurance of roughly $104,000")]})
    out = judge.judge_run(r, CASES, client=client, workers=1)
    assert out["judged"] == 2 and client.calls == 4 and out["needs_manual"] == 0      # each finding judged twice
    res = judge.score_run(r, CASES)
    assert res["metrics"]["found"] == 1 and res["metrics"]["false_positives"] == 1
    assert res["rows"][0]["reasoning"] == 2 and res["rows"][0]["evidence"] == "Sufficient"
    assert judge.judge_run(r, CASES, client=client)["judged"] == 0                    # nothing is judged twice over


def test_judge_safeguards(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "VERDICTS", tmp_path / "verdicts.json")
    invented = verdict(quote="a sentence that appears nowhere in the material")
    q = "$0.82 per $1.00 of credit"
    unstable = [verdict(ids=("T1-002",), quote=q), verdict("no", (), quote=q)]
    client = FakeClient({"F1": [invented], "F2": unstable,
                         "F3": [verdict("cannot_decide", (), quote="insurance of roughly $104,000")]})
    judge.judge_run(run([F_CREDIT, F_DRAFT, F_NOISE]), CASES, client=client, workers=1)
    v = judge.load_verdicts()
    assert v["R1::F1"]["verdict"] is None and "quote is not in the material" in v["R1::F1"]["reasons"][0]
    assert v["R1::F2"]["stable"] is False and v["R1::F2"]["needs_manual"]
    assert "could not decide" in v["R1::F3"]["reasons"][0]
    d = judge.as_decisions(run([F_CREDIT, F_DRAFT, F_NOISE]), v)
    assert d["R1::F1"]["status"] == "Needs review" and d["R1::F3"]["status"] == "Needs review"
    hidden = FakeClient({"F1": [verdict(ids=("T1-999",))]})                            # a case it was never shown
    judge.judge_run(run([F_CREDIT], "R2"), CASES, client=hidden, workers=1)
    assert judge.load_verdicts()["R2::F1"]["verdict"] is None


def test_judge_against_rules_and_manual(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "VERDICTS", tmp_path / "verdicts.json")
    r = run([F_CREDIT, F_DRAFT])
    client = FakeClient({"F1": [verdict()], "F2": [verdict("no", (), quote="$0.82 per $1.00 of credit")]})
    judge.judge_run(r, CASES, client=client, workers=1)
    reviews = {"R1::F1": {"status": "Match", "case_ids": ["T1-001"], "evidence": "Sufficient", "reasoning": 2},
               "R1::F2": {"status": "Match", "case_ids": ["T1-002"], "evidence": None, "reasoning": None}}
    cmp_ = judge.compare_run(r, CASES, reviews, judge.load_verdicts())
    rows = {x["finding_id"]: x for x in cmp_["rows"]}
    assert rows["F1"]["agree"] is True and rows["F2"]["agree"] is False
    assert rows["F2"]["rules_right"] is True and rows["F2"]["judge_right"] is False
    t = judge.trust([r], CASES, reviews, judge.load_verdicts())
    assert t["judge_matches_manual"] == (0.5, 2) and t["only_rules_right"] == 1


# ---- free-tier providers, against a local stand-in for an OpenAI-style endpoint ----------------------
import threading as _threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from eval import providers


class _Endpoint(BaseHTTPRequestHandler):
    plan, seen = [], []          # plan: what to answer, in order; the last entry repeats

    def do_POST(self):
        body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        step = self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        status, payload, headers = step(body) if callable(step) else step
        data = _json.dumps(payload).encode()
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _ok(v):
    return (200, {"choices": [{"message": {"content": "```json\n" + _json.dumps(v) + "\n```"}}],
                  "usage": {"prompt_tokens": 900, "completion_tokens": 80}}, {})


def _serve(monkeypatch, tmp_path, plan):
    _Endpoint.plan, _Endpoint.seen = list(plan), []
    server = HTTPServer(("127.0.0.1", 0), _Endpoint)
    _threading.Thread(target=server.serve_forever, daemon=True).start()
    for k in list(os.environ):
        if k.startswith("EVAL_JUDGE") or k == "GITHUB_MODELS_TOKEN":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "free-gpt")
    monkeypatch.setenv("EVAL_JUDGE_RPM", "6000")
    monkeypatch.setattr(judge, "VERDICTS", tmp_path / "verdicts.json")
    return server


import os


def test_free_provider_falls_back_when_schema_mode_is_refused(tmp_path, monkeypatch):
    refuse = lambda body: ((400, {"error": {"message": "response_format json_schema is not supported"}}, {})
                           if body.get("response_format", {}).get("type") == "json_schema" else _ok(verdict()))
    server = _serve(monkeypatch, tmp_path, [refuse])
    out = judge.judge_run(run([F_CREDIT]), CASES)
    server.shutdown()
    assert out["judged"] == 1 and out["cost"] == "free tier" and out["stopped"] is None
    assert _Endpoint.seen[0]["temperature"] == 0 and _Endpoint.seen[-1]["response_format"]["type"] == "json_object"
    v = judge.load_verdicts()["R1::F1"]
    assert v["verdict"]["case_ids"] == ["T1-001"] and v["model"] == "free-gpt" and v["stable"] is True


def test_free_provider_rejects_answers_outside_the_format(tmp_path, monkeypatch):
    server = _serve(monkeypatch, tmp_path, [_ok(verdict(evidence="Looks fine"))])
    judge.judge_run(run([F_CREDIT]), CASES)
    server.shutdown()
    v = judge.load_verdicts()["R1::F1"]
    assert v["verdict"] is None and "did not follow the format" in v["reasons"][0]


def test_daily_limit_stops_cleanly_and_the_next_run_continues(tmp_path, monkeypatch):
    limit = (429, {"error": {"message": "Rate limit reached: requests per day"}}, {"Retry-After": "40000"})
    server = _serve(monkeypatch, tmp_path, [_ok(verdict()), _ok(verdict()), limit])
    r = run([F_CREDIT, F_DRAFT])
    out = judge.judge_run(r, CASES)
    assert out["judged"] == 1 and out["left"] == 1 and "used up" in out["stopped"]
    assert list(judge.load_verdicts()) == ["R1::F1"]                       # the finished verdict was kept
    _Endpoint.plan = [_ok(verdict("no", (), quote="$0.82 per $1.00 of credit"))]
    out = judge.judge_run(r, CASES)
    server.shutdown()
    assert out["judged"] == 1 and out["skipped"] == 1 and out["stopped"] is None


def test_short_rate_limit_is_waited_out_and_bad_key_is_reported(tmp_path, monkeypatch):
    server = _serve(monkeypatch, tmp_path, [(429, {"error": {"message": "slow down"}}, {"Retry-After": "0"}), _ok(verdict())])
    assert judge.judge_run(run([F_CREDIT]), CASES)["judged"] == 1
    _Endpoint.plan = [(401, {"error": {"message": "bad token"}}, {})]
    try:
        judge.judge_run(run([F_CREDIT], "R9"), CASES)
        raise AssertionError("expected JudgeUnavailable")
    except judge.JudgeUnavailable as e:
        assert "refused" in str(e)
    server.shutdown()


def test_long_pages_are_cut_to_excerpts_for_small_models():
    chunks = {"DOC-05": {2: "filler " * 3000 + "Federal historic tax credit: $5,120,000 " + "filler " * 3000}, "DOC-06": {3: "x " * 9000}}
    full, _ = judge.build_message(F_CREDIT, CASES[:1], chunks)
    short, material = judge.build_message(F_CREDIT, CASES[:1], chunks, max_chars=6000)
    assert len(full) > 40000 and len(short) <= 6000 and "excerpt of the cited page" in short
    assert "$5,120,000" in short.split("<cited_passages>")[1]


def test_same_family_is_flagged_and_provider_is_picked_from_the_key(monkeypatch):
    assert providers.family("openai/gpt-4.1-mini") == providers.family("ChatGPT (GPT-5)") == "gpt"
    assert providers.family("gemini-2.5-flash") == "gemini" and providers.family("Grok 4.7") == "grok"
    for k in list(os.environ):
        if k.startswith("EVAL_JUDGE") or k.endswith("_API_KEY") or k.endswith("_TOKEN"):
            monkeypatch.delenv(k, raising=False)
    assert providers.settings()["problem"]
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "t")
    monkeypatch.setenv("EVAL_DATA_POLICY", "open")           # a free tier is only used when allowed on purpose
    cfg = providers.settings()
    assert cfg["provider"] == "github" and cfg["model"] == "openai/gpt-4.1-mini" and cfg["free"] and not cfg["problem"]


# ---- Vericap run check, context layer, sheet upload, data security --------------------------------------
import re as _re
import shutil

import pytest

from eval import context, data_room, doc_store, library, store
from eval import reality_check as rc

ROOT = store.ROOT


def _local_model(monkeypatch):
    """A stand-in model on this machine, and no document store: the tests never depend on outside services."""
    for k in list(os.environ):
        if k.startswith("EVAL_") or k.startswith("MONGO_") or k.endswith("_API_KEY") or k.endswith("_TOKEN"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "stand-in")
    doc_store.use_settings()


@pytest.fixture(autouse=True)
def _no_outside_store(monkeypatch):
    """Every test reads page text from files or the in-memory store, whatever .env says."""
    monkeypatch.delenv("MONGO_URI", raising=False)
    doc_store.use_settings()
    yield
    doc_store.use_settings()


EXTRA_PAGES = [("HTC02", "DOC-04", 6, "Qualified rehabilitation expenditures: $39.8M"),
               ("HTC02", "DOC-05", 7, "Qualified rehabilitation expenditures (revised): $36.45M")]


def _page_text_from_the_answer_key(folder):
    """Page text built from the quotes the answer key cites, so the tests need no data room on disk."""
    pages: dict[tuple, list[str]] = {}
    for c in _json.loads((ROOT / "answer_key" / "library_v1.json").read_text(encoding="utf-8"))["cases"]:
        for cit in c["citations"]:
            if cit["doc_id"] and cit["quote"] and not cit["quote"].startswith("["):
                pages.setdefault((c["data_room"], cit["doc_id"], cit["page"] or 1), []).append(cit["quote"])
    for room, doc, page, text in EXTRA_PAGES:
        pages.setdefault((room, doc, page), []).append(text)
    for room in sorted({k[0] for k in pages}):
        store._write(folder / room / "chunks.json", [{"doc_id": d, "page": p, "text": "\n".join(q), "read_by": "text"}
                                                     for (r, d, p), q in sorted(pages.items()) if r == room])


@pytest.fixture
def empty(tmp_path, monkeypatch):
    """No stored data at all: checks, facts, rules and the change log go to an empty folder."""
    _local_model(monkeypatch)
    monkeypatch.setattr(store, "ANSWER_KEY", tmp_path / "answer_key")
    monkeypatch.setattr(store, "DATA_ROOM", tmp_path / "data_room")
    monkeypatch.setattr(rc, "CHECKS", tmp_path / "reality_checks")
    return tmp_path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the repository data, so nothing in the real answer key is changed."""
    _local_model(monkeypatch)
    for d in ("answer_key", "submissions", "reviews"):
        shutil.copytree(ROOT / d, tmp_path / d)
    _page_text_from_the_answer_key(tmp_path / "data_room")
    for name, path in [("DATA", tmp_path), ("ANSWER_KEY", tmp_path / "answer_key"), ("SUBMISSIONS", tmp_path / "submissions"),
                       ("REVIEWS", tmp_path / "reviews" / "decisions.json"), ("DATA_ROOM", tmp_path / "data_room"),
                       ("REPORTS", tmp_path / "reports")]:
        monkeypatch.setattr(store, name, path)
    monkeypatch.setattr(rc, "CHECKS", tmp_path / "reality_checks")
    monkeypatch.setattr(judge, "VERDICTS", tmp_path / "judge" / "verdicts.json")
    return tmp_path


class CheckClient:
    """Stands in for the model in the run check. By default: partially_found with the first listed finding
    for a reportable case, not_flagged for a non-issue, not_in_documents for a leftover finding."""

    def __init__(self, case=None, leftover=None, limit=None):
        self.case, self.leftover, self.limit, self.calls, self.asked, self.bodies = case, leftover, limit, 0, [], []

    def complete(self, model, system, message, schema):
        self.calls += 1
        if self.limit and self.calls > self.limit:
            raise providers.JudgeQuotaReached("the free allowance is used up")
        statuses = schema["properties"]["status"]["enum"]
        tokens_ = {"error": None, "input_tokens": 100, "output_tokens": 10}
        if "real_issue" in statuses:
            fid = message.split('<finding id="')[1].split('"')[0]
            self.asked.append(fid)
            v = {"status": "not_in_documents", "rule_ids": [], "fact_or_judgment": "fact", "why_it_matters": "",
                 "why_it_might_not": "", "severity": "not_applicable", "quote": "", "explanation": "e"}
            return {"verdict": {**v, **(self.leftover(fid) if self.leftover else {})}, **tokens_}
        cid = message.split("ID: ")[1].split("\n")[0]
        self.asked.append(cid)
        summary = message.split("Summary: ")[1].split("\n")[0]
        first = _re.search(r'<finding id="([^"]+)">|^- (\S+) \|', message.split("<run_findings")[1], _re.M)
        fid = (first.group(1) or first.group(2)) if first else None
        if "found" in statuses:
            v = {"status": "partially_found", "finding_ids": [fid], "covered": "c", "missing": "m", "quote": summary, "explanation": "e"}
        else:
            v = {"status": "not_flagged", "finding_ids": [], "covered": "", "missing": "", "quote": "", "explanation": "e"}
        return {"verdict": {**v, **(self.case(cid, fid, message) if self.case else {})}, **tokens_}


def _check(findings=(F_CREDIT, F_DRAFT, F_NOISE), room="T1"):
    read = rc.read_findings({"findings": [dict(f, citations=[c["raw"] for c in f["citations"]]) for f in findings]})
    return rc.open_check(room, "Vericap run", read)


ODD = {"data_room_id": "HTC02", "result": {"discrepancies": [
    {"id": "d1", "title": "Cornice removed against NPS condition", "type": "conflict", "priority": "High",
     "evidence": [{"document": "DOC-02", "page": 4, "text": "They must be retained and repaired in situ"}]},
    {"id": "d2", "description": "Budget total differs from model", "risk_level": 2, "documents": ["DOC-10", "DOC-09"]}]}}


def test_reading_an_odd_shape():
    r = rc.read_findings(ODD)
    d1, d2 = r["findings"]
    assert r["source_path"] == "$.result.discrepancies" and r["run_meta"]["data_room"] == "HTC02"
    assert (d1["finding_id"], d2["finding_id"]) == ("d1", "d2")
    assert (d1["classification"], d1["severity"]) == ("Contradiction", "High") and d2["severity"] == "High"
    assert d1["citations"][0]["page"] == 4 and d1["citations"][0]["quote"].startswith("They must be retained")
    assert {c["doc_id"] for c in d2["citations"]} == {"DOC-09", "DOC-10"}
    assert any("quotes no passage" in n for n in r["notes"])
    assert rc._classification("Inconsistent figures") == "Contradiction" and rc._classification("no issue") == "Consistent"
    with pytest.raises(ValueError, match="No list of findings"):
        rc.read_findings({"status": "ok", "numbers": [1, 2, 3]})


def test_reading_a_contract_file():
    payload = _json.loads((ROOT / "submissions" / "baseline" / "CHATGPT-HTC02-R1.json").read_text(encoding="utf-8"))
    r = rc.read_findings(payload)
    assert r["source_path"] == "$.findings" and len(r["findings"]) == len(payload["findings"])
    assert [len(f["citations"]) for f in r["findings"]] == [len(f["citations"]) for f in payload["findings"]]
    assert all(f["classification"] and f["severity"] for f in r["findings"])


def test_partial_credit_manual_override_and_bad_finding_ids(empty):
    check = _check()
    out = rc.run_check(check, CASES, client=CheckClient(), workers=1)
    assert out["left"] == 0 and out["stopped"] is None
    res = rc.results(check, CASES, {})
    assert res["metrics"]["all"]["accuracy"] == 0.5 and res["metrics"]["all"]["partial"] == 2
    assert all(n["status"] == rc.NOT_IN_DOCS for n in res["new"])
    rc.set_manual(check, "case", "T1-001", rc.FOUND, ["F1"], "The finding has both figures.")
    after = rc.results(check, CASES, {})
    assert after["metrics"]["all"]["points"] > res["metrics"]["all"]["points"]
    assert next(r for r in after["cases"] if r["case_id"] == "T1-001")["manual"] is True
    rc.clear_manual(check, "case", "T1-001")
    assert rc.results(check, CASES, {})["metrics"]["all"]["accuracy"] == 0.5

    other = _check([F_CREDIT])
    unknown = CheckClient(case=lambda cid, fid, msg: {"status": "found", "finding_ids": ["F99"]} if cid == "T1-001" else {})
    rc.run_check(other, CASES, client=unknown, workers=1)
    v = other["case_verdicts"]["T1-001"]
    assert v["status"] == rc.REVIEW and "names no finding" in v["explanation"]


def test_a_stopped_check_carries_on(empty):
    check = _check()
    first = CheckClient(limit=3)
    out = rc.run_check(check, CASES, client=first, workers=1)
    assert out["stopped"] and out["left"] > 0 and len(rc.load_check(check["check_id"])["case_verdicts"]) == 3
    second = CheckClient()
    out = rc.run_check(check, CASES, client=second, workers=1)
    assert out["left"] == 0 and not set(second.asked) & set(first.asked[:3])
    assert rc.list_checks()[0]["check_id"] == check["check_id"]


def test_made_up_verdict_is_asked_again_then_needs_review(empty):
    check = _check([F_CREDIT])
    liar = CheckClient(case=lambda cid, fid, msg: {"status": "found", "quote": "a sentence that was never shown"})
    rc.run_check(check, CASES, client=liar, workers=1)
    v = check["case_verdicts"]["T1-001"]
    assert v["status"] == rc.REVIEW and "quotes text that was not shown" in v["explanation"]
    assert liar.asked.count("T1-001") == 2


PRICE = [
    {"fact_id": "R-a", "data_room": "T1", "subject": "credit price", "scope": "", "value": "$25", "unit_basis": "",
     "value_status": "Signed", "as_of": "2024-03-01", "source": {"doc_id": "DOC-17", "page": 3, "quote": "$25"},
     "supersedes": "", "change_reason": "", "change_source": "", "notes": ""},
    {"fact_id": "R-b", "data_room": "T1", "subject": "credit price", "scope": "", "value": "$20", "unit_basis": "",
     "value_status": "Signed", "as_of": "2025-01-15", "source": {"doc_id": "DOC-18", "page": 1, "quote": "$20"},
     "supersedes": "R-a", "change_reason": "rate reset", "change_source": {"doc_id": "DOC-18", "page": 1, "quote": "reset to $20"},
     "notes": ""}]
DOCS = {"DOC-17": {"doc_date": "2024-03-01"}, "DOC-18": {"doc_date": "2025-01-15"}, "DOC-05": {"doc_date": "2025-03-01"},
        "DOC-11": {"doc_date": "2024-02-01"}, "DOC-19": {"doc_date": "2025-07-01"}}
F_REPRICED = finding("P1", "Contradiction", "High", "Credit price differs between the agreement and the repricing letter",
                     "$25 against $20", "DOC-17 p.3: 'a price of $25' || DOC-18 p.1: 'reset to $20'")
F_STALE = finding("P2", "Contradiction", "High", "The deck still shows the old credit price",
                  "$25 in the deck against $20", "DOC-05 p.6: 'credit price $25' || DOC-18 p.1: 'reset to $20'")


def test_precheck_price(empty):
    assert context.precheck(F_REPRICED, "T1", PRICE, DOCS)["tag"] == "Known change"
    stale = context.precheck(F_STALE, "T1", PRICE, DOCS)
    assert (stale["tag"], stale["rule_id"], stale["facts"]) == ("Stale value", "C2", ["R-a", "R-b"])
    no_source = [PRICE[0], {**PRICE[1], "change_source": ""}]
    assert context.precheck(F_REPRICED, "T1", no_source, DOCS)["tag"] == "Unexplained change"
    assert context.precheck(F_NOISE, "T1", PRICE, DOCS) is None
    assert "R-a $25 Signed 2024-03-01 → R-b $20 Signed 2025-01-15 (rate reset; DOC-18 p.1)" == context.chain_text(PRICE[1], PRICE)


def test_precheck_dates(empty):
    def dates(first, second):
        f = lambda i, value, status, doc: {"fact_id": i, "data_room": "T1", "subject": "placed in service date", "scope": "",
                                           "value": value, "unit_basis": "", "value_status": status, "as_of": "",
                                           "source": {"doc_id": doc, "page": 1, "quote": value}, "supersedes": "",
                                           "change_reason": "", "change_source": "", "notes": ""}
        return [f("R-1", "November 3, 2024", first, "DOC-11"), f("R-2", "June 4, 2025", second, "DOC-19")]
    f = finding("D1", "Contradiction", "High", "Placed in service date differs", "November 3, 2024 against June 4, 2025",
                "DOC-11 p.1: 'November 3, 2024' || DOC-19 p.1: 'June 4, 2025'")
    assert context.precheck(f, "T1", dates("Estimate", "Target"), DOCS)["tag"] == "Two forecasts"
    assert context.precheck(f, "T1", dates("Actual", "Actual"), DOCS)["tag"] == "Two actuals"
    assert context.precheck(f, "T1", dates("Estimate", "Actual"), DOCS)["tag"] == "Forecast against actual"
    assert context.precheck(f, "T1", dates("Estimate", "Target"), {}) is None           # no document dates: cannot decide


def test_context_is_in_the_message_at_every_size(empty):
    c = dict(CASES[0], data_room="T1", register_ids=["R-b"])
    ctx = context.block_for_case(c, PRICE)
    assert "R-a" in ctx and "R-b" in ctx and "rate reset" in ctx and "C1 [Reject] Documented change" in ctx
    chunks = {"DOC-05": {2: "Federal historic tax credit: $5,120,000. " + "filler words. " * 4000}}
    findings = [dict(F_CREDIT, raw_classification="", raw_severity="", finding_id=f"F{i}") for i in range(60)]
    for limit in (10 ** 7, 30000, 9000, 100):
        message, sent = rc.case_message(c, findings, findings, chunks, ctx, limit)
        assert ctx in message
    assert "more findings of the run are left out" in message and sent == [["DOC-05", 2]]


def _gate(status, pre=None, rule_ids=(), severity="High", quotes=True, rejected=None, f=F_REPRICED):
    v = {"raw_status": status, "rule_ids": list(rule_ids), "severity": severity, "explanation": "e", "own_quotes_found": quotes}
    return context.gate(f, pre, v, "T1", None, rejected)


def test_rule_gate(empty):
    known = context.precheck(F_REPRICED, "T1", PRICE, DOCS)
    stale = context.precheck(F_STALE, "T1", PRICE, DOCS)
    g = _gate("known_change", known)
    assert (g["outcome"], g["rule_id"]) == ("Rejected by rule", "C1")
    assert _gate("real_issue", stale, f=F_STALE)["outcome"] == "Candidate"
    assert _gate("not_a_discrepancy", stale, f=F_STALE)["outcome"] == "Needs review"       # a Flag rule: never rejected
    assert _gate("real_issue", known)["outcome"] == "Needs review"                         # rule and judge disagree
    before = [{"data_room": "T1", "finding": F_NOISE, "reason": "Not material.", "rule_id": None, "check_id": "old"}]
    g = _gate("real_issue", rejected=before, f=dict(F_NOISE, finding_id="F8"))
    assert (g["outcome"], g["rule_id"]) == ("Rejected by rule", "C13") and "Not material." in g["reason"]
    g = _gate("real_issue", severity="Low", f=F_NOISE)
    assert (g["outcome"], g["rule_id"]) == ("Rejected by rule", "C12")
    assert _gate("real_issue", f=F_NOISE) == {"outcome": "Candidate", "rule_id": None, "reason": "e"}
    assert _gate("not_in_documents", quotes=False, f=F_NOISE)["rule_id"] == "C14"
    assert _gate("cannot_decide", f=F_NOISE)["outcome"] == "Needs review"


def test_admission_checklist(empty):
    chunks = {"DOC-03": {19: "Schedule B shows insurance of roughly $104,000 per year."}}
    store._write(store.DATA_ROOM / "T1" / "chunks.json", [{"doc_id": "DOC-03", "page": 19, "text": chunks["DOC-03"][19]}])
    real = lambda fid: {"status": "real_issue", "severity": "High", "fact_or_judgment": "judgment",
                        "why_it_matters": "The operating budget understates insurance.", "rule_ids": ["C9"]}
    check = _check([F_CREDIT, F_NOISE])
    rc.run_check(check, CASES, client=CheckClient(leftover=real), workers=1)
    assert check["new_verdicts"]["F3"]["gate"]["outcome"] == "Needs review"                # the judge named a Reject rule
    lines = {x["check"]: x["result"] for x in rc.checklist(check, "F3", CASES, [])}
    assert lines == {"Real in the documents": "Pass", "Not already in the ground truth": "Pass",
                     "Not excused by a rule": "Fail", "A major red flag": "Pass", "A fact, not an opinion": "Unknown",
                     "Seen by others": "Info"}
    case_ = rc.prefill_case(check, "F3")
    assert case_["case_id"] == "T1-001" and case_["ambiguous"] and case_["scenario_tags"] == ["C9"] and case_["weight"] == 4


def test_data_policy_and_no_tools(monkeypatch):
    _local_model(monkeypatch)
    assert providers.settings()["problem"] is None                         # a model on this machine is allowed
    monkeypatch.delenv("EVAL_JUDGE_PROVIDER")
    monkeypatch.delenv("EVAL_JUDGE_BASE_URL")
    monkeypatch.setenv("GITHUB_MODELS_TOKEN", "t")
    cfg = providers.settings()
    assert cfg["provider"] == "github" and "strict" in cfg["problem"] and "free tier" in cfg["problem"]
    with pytest.raises(providers.JudgeUnavailable, match="strict"):
        judge._client()
    monkeypatch.setenv("EVAL_TRUSTED_PROVIDERS", "github")
    assert providers.settings()["problem"] is None
    monkeypatch.delenv("EVAL_TRUSTED_PROVIDERS")
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "custom")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "https://api.example.com/v1")
    assert "strict" in providers.settings()["problem"]
    monkeypatch.setenv("EVAL_JUDGE_PROVIDER", "local")
    assert "not this machine" in providers.settings()["problem"]

    with pytest.raises(providers.JudgeUnavailable, match="never given tools"):
        providers.check_request("http://127.0.0.1:9/chat/completions", {"model": "m", "tools": []}, ["127.0.0.1"])
    with pytest.raises(providers.JudgeUnavailable, match="not an allowed host"):
        providers.check_request("https://elsewhere.example/chat/completions", {"model": "m"}, ["127.0.0.1"])


def test_requests_carry_no_tools_and_stay_on_the_allowed_host(tmp_path, monkeypatch, empty):
    server = _serve(monkeypatch, tmp_path, [_ok({"status": "missed", "finding_ids": [], "covered": "", "missing": "",
                                                 "quote": "", "explanation": "e"})])
    _Endpoint.seen.clear()
    check = _check([F_CREDIT])
    try:
        rc.run_check(check, [CASES[0]], workers=1)
    except providers.JudgeUnavailable:
        pass                                                    # the stand-in answers every call with a case verdict
    server.shutdown()
    assert _Endpoint.seen and all(not (providers.FORBIDDEN_KEYS & set(b)) and len(b["messages"]) == 2 for b in _Endpoint.seen)
    assert check["case_verdicts"]["T1-001"]["sent"]["provider"] == "custom"
    monkeypatch.setenv("EVAL_ALLOWED_HOSTS", "models.example.com")
    with pytest.raises(providers.JudgeUnavailable, match="not an allowed host"):
        providers.ChatClient(providers.settings()).complete("m", "s", "u", rc.SCHEMA_LEFTOVER)


# ---- the answer key: candidates, freeze, sheet upload ----------------------------------------------------

def _htc02_check(extra=()):
    payload = _json.loads((ROOT / "submissions" / "baseline" / "CHATGPT-HTC02-R1.json").read_text(encoding="utf-8"))
    payload["findings"] = payload["findings"][:3] + list(extra)
    return rc.open_check("HTC02", "Vericap HTC02", rc.read_findings(payload))


NEW_ISSUE = {"finding_id": "N1", "classification": "Contradiction", "severity": "High",
             "summary": "The masonry change directive is priced above the contingency left in the budget",
             "claims_compared": "Directive against budget contingency",
             "citations": ["DOC-04 p.6: 'Qualified rehabilitation expenditures: $39.8M'"], "explanation": "x"}
_REAL = lambda fid: ({"status": "real_issue", "severity": "High", "why_it_matters": "The budget cannot absorb the cost."}
                     if fid == "N1" else {})


def test_accepting_a_candidate_and_freezing(repo):
    v1 = (repo / "answer_key" / "library_v1.json").read_bytes()
    check = _htc02_check([NEW_ISSUE])
    rc.run_check(check, store.load_cases(), client=CheckClient(leftover=_REAL), workers=1)
    before = rc.results(check, store.load_cases())
    assert [n["finding_id"] for n in before["new"] if n["band"] == rc.CANDIDATE] == ["N1"]

    case_ = rc.accept_candidate(check, "N1", rc.prefill_case(check, "N1"), "Real and material.")
    assert case_["case_id"] == "HTC02-043"
    pending = library.load_pending()
    assert [(p["case_id"], p["status"], p["check_id"]) for p in pending] == [("HTC02-043", library.ACCEPTED, check["check_id"])]
    log = library.load_changelog()
    assert log[-1]["action"] == "accept" and log[-1]["origin"] == check["check_id"] and log[-1]["reason"] == "Real and material."
    draft = store.load_cases(store.DRAFT)
    assert len(draft) == len(store.load_cases()) + 1 and (repo / "answer_key" / "library_v1.json").read_bytes() == v1
    after = rc.results(check, draft)
    new_row = next(r for r in after["cases"] if r["case_id"] == "HTC02-043")
    assert new_row["status"] == rc.FOUND and new_row["manual"] and new_row["finding_ids"] == ["N1"]
    m = after["metrics"]
    assert m["from_this_run"] == 1 and m["all_before"]["cases"] == m["all"]["cases"] - 1
    assert m["all_before"]["points"] == before["metrics"]["all"]["points"]
    assert rc.remaining(check, draft)["total"] == 0                     # the accepted case is not asked again
    assert "HTC02-043" in rc.markdown(check, after, rc.baseline_comparison(check, [], draft))

    res = library.freeze("First additions from a Vericap run.")
    v2 = _json.loads((repo / "answer_key" / "library_v2.json").read_text(encoding="utf-8"))
    assert res["name"] == "library_v2" and store.snapshots() == ["library_v1", "library_v2"]
    assert len(v2["cases"]) == len(draft) and "facts" in v2 and [r["rule_id"] for r in v2["rules"]][:2] == ["C1", "C2"]
    assert library.load_changelog()[-1]["action"] == "freeze" and (repo / "answer_key" / "library_v1.json").read_bytes() == v1
    assert len(store.load_cases()) == len(draft)                        # the newest frozen snapshot is the default


def test_rejected_candidate_is_not_reviewed_twice(repo):
    check = _htc02_check([NEW_ISSUE])
    rc.run_check(check, store.load_cases(), client=CheckClient(leftover=_REAL), workers=1)
    rc.reject_candidate(check, "N1", "Not a major red flag: within contingency.")
    assert rc.results(check, store.load_cases())["metrics"]["rejected_by_evaluator"] == 1
    again = _htc02_check([dict(NEW_ISSUE, finding_id="N1", explanation="worded again")])
    assert again["check_id"] == check["check_id"]
    later = rc.open_check("HTC02", "Later run", rc.read_findings({"findings": [dict(NEW_ISSUE, finding_id="Z9")]}))
    nothing = lambda cid, fid, msg: {"status": "missed", "finding_ids": []} if "reported as a problem: yes" in msg else {}
    rc.run_check(later, store.load_cases(), client=CheckClient(case=nothing, leftover=lambda fid: _REAL("N1")), workers=1)
    row = rc.results(later, store.load_cases())["new"][0]
    assert (row["band"], row["rule_id"]) == (rc.REJECTED_RULE, "C13") and "within contingency" in row["reason"]
    rc.restore(later, "Z9", "This one is larger.")
    assert rc.results(later, store.load_cases())["new"][0]["band"] == rc.REVIEW
    assert library.load_changelog()[-1]["action"] == "restore"


def _sheet():
    return _json.loads((ROOT / "answer_key" / "sheet_export_2026-11-11.json").read_text(encoding="utf-8"))


def test_sheet_upload_preview_then_confirm(repo):
    wb = _sheet()
    row = next(r for r in wb["Ground Truth"] if r["Case ID"] == "HTC01-001")
    good = row["Citations"]
    row["Summary"] = "Federal credit in the model is overstated against the QRE"
    row["Citations"] = good.replace("$5,120,000", "$9,999,999 which is nowhere")
    staged = library.stage(wb)
    pv, problems = library.preview(staged), library.validate(staged)
    truth = next(t for t in pv["tabs"] if t["tab"] == "Ground Truth")
    assert (truth["new"], truth["changed"], truth["removed"]) == (0, 1, 0)
    assert set(pv["changes"]["Ground Truth"]["changed"][0]["fields"]) == {"summary", "citations"}
    assert len(problems["errors"]) == 1 and "HTC01-001" in problems["errors"][0] and "quote is not in" in problems["errors"][0]
    with pytest.raises(ValueError):
        library.apply(staged, "sheet.xlsx")
    assert not store.has_draft() and not library.load_changelog()                     # nothing was written

    row["Citations"] = good
    staged = library.stage(wb)
    assert library.validate(staged)["errors"] == []
    out = library.apply(staged, "sheet.xlsx", "Clearer summary.")
    assert out["logged"] >= 1 and store.has_draft()
    changed = next(c for c in store.load_cases(store.DRAFT) if c["case_id"] == "HTC01-001")
    assert changed["summary"].startswith("Federal credit in the model is overstated")
    entry = next(e for e in library.load_changelog() if e["object"] == "case")
    assert (entry["id"], entry["action"], entry["origin"], entry["reason"]) == ("HTC01-001", "upload", "sheet.xlsx", "Clearer summary.")
    assert entry["before"]["summary"] != entry["after"]["summary"]
    assert next(c for c in store.load_cases() if c["case_id"] == "HTC01-001")["summary"] != changed["summary"]   # v1 is as it was
    assert library.preview(library.stage(wb))["tabs"][0]["changed"] == 0               # the same upload again changes nothing


def test_stale_verdict_after_an_upload(repo):
    check = _htc02_check()
    rc.run_check(check, store.load_cases(), client=CheckClient(), workers=1)
    assert rc.remaining(check, store.load_cases())["total"] == 0
    wb = _sheet()
    next(r for r in wb["Ground Truth"] if r["Case ID"] == "HTC02-001")["Explanation"] = "Rewritten after review."
    library.apply(library.stage(wb), "sheet.xlsx")
    left = rc.remaining(check, store.load_cases(store.DRAFT))
    assert left["stale"] == ["HTC02-001"] and left["cases"] == ["HTC02-001"]
    assert next(r for r in rc.results(check, store.load_cases(store.DRAFT))["cases"] if r["case_id"] == "HTC02-001")["stale"]
    client = CheckClient()
    rc.run_check(check, store.load_cases(store.DRAFT), client=client, workers=1)
    assert client.asked[0] == "HTC02-001" and rc.remaining(check, store.load_cases(store.DRAFT))["cases"] == []


def test_pending_rows_clear_when_the_sheet_has_the_case(repo):
    check = _htc02_check([NEW_ISSUE])
    rc.run_check(check, store.load_cases(), client=CheckClient(leftover=_REAL), workers=1)
    case_ = rc.accept_candidate(check, "N1", rc.prefill_case(check, "N1"), "Real.")
    wb = _sheet()
    pv = library.preview(library.stage(wb))
    assert [p["case_id"] for p in pv["pending_kept"]] == ["HTC02-043"] and pv["pending_cleared"] == []
    library.apply(library.stage(wb), "sheet.xlsx")
    assert [p["case_id"] for p in library.load_pending()] == ["HTC02-043"]
    assert any(c["case_id"] == "HTC02-043" for c in store.load_cases(store.DRAFT))    # still in the draft
    from openpyxl import load_workbook
    import io
    rows = list(load_workbook(io.BytesIO(library.pending_xlsx()))["Ground Truth"].iter_rows(values_only=True))
    assert list(rows[0]) == library.GT_COLUMNS and rows[1][0] == "HTC02-043"

    wb["Ground Truth"].append(library.case_row(case_))
    staged = library.stage(wb)
    assert library.validate(staged)["errors"] == []
    assert [p["case_id"] for p in library.preview(staged)["pending_cleared"]] == ["HTC02-043"]
    library.apply(staged, "sheet2.xlsx")
    assert library.load_pending() == []
    kept = next(c for c in store.load_cases(store.DRAFT) if c["case_id"] == "HTC02-043")
    assert kept["origin_check"] == check["check_id"]                                  # still counted apart for this run


def test_new_tabs_are_read_and_checked(repo):
    wb = _sheet()
    wb["Fact Sheet"] = [
        {"Fact ID": "R-900", "Data room": "HTC02", "Subject": "QRE", "Value": "$39.8M", "Value status": "Estimate",
         "As of": "2024-02-01", "Source": "DOC-04 p.6: 'Qualified rehabilitation expenditures: $39.8M'"},
        {"Fact ID": "R-901", "Data room": "HTC02", "Subject": "QRE", "Value": "$36.45M", "Value status": "Approved",
         "Supersedes": "R-999", "Source": "DOC-05 p.7: '(revised): $36.45M'"}]
    wb["Context Rules"] = [{"Rule ID": "C1", "Name": "Documented change", "Rule": "text", "Type": "Reject", "Critical": "Yes", "On": "No"}]
    errors = library.validate(library.stage(wb))["errors"]
    assert any("R-901" in e and "does not exist" in e for e in errors) and any("C1 is critical and switched off" in e for e in errors)
    wb["Fact Sheet"][1]["Supersedes"] = "R-900"
    wb["Context Rules"][0]["Notes"] = "Switched off for one trial."
    staged = library.stage(wb)
    assert library.validate(staged)["errors"] == []
    library.apply(staged, "sheet.xlsx")
    assert [f["fact_id"] for f in context.load_facts("HTC02")] == ["R-900", "R-901"] and context.rules_on() == []
    assert context.chain_text(context.load_facts("HTC02")[1], context.load_facts()).endswith("(no document records this change)")
    from openpyxl import load_workbook
    import io
    book = load_workbook(io.BytesIO(library.template_xlsx()))
    assert set(library.TABS) == set(book.sheetnames) and [c.value for c in book["Fact Sheet"][1]] == library.FACT_COLUMNS


# ---- document store ---------------------------------------------------------------------------------------------

MONGO_URI_TEST = os.environ.get("MONGO_URI_TEST")       # read here: the fixtures clear every MONGO_ setting
ROWS = [{"doc_id": "DOC-01", "page": 1, "text": "Part 1 approved on March 3, 2024.", "read_by": "ocr"},
        {"doc_id": "DOC-01", "page": 2, "text": "Building A only.", "read_by": "text"},
        {"doc_id": "DOC-02", "page": 1, "text": "QRE of $24,600,000.", "read_by": "text"}]


def _local_room(folder, room="T9"):
    store._write(folder / room / "chunks.json", ROWS)
    (folder / room / "documents").mkdir(parents=True)
    for doc in ("DOC-01_Part1.pdf", "DOC-02_Budget.pdf"):
        (folder / room / "documents" / doc).write_bytes(b"%PDF-1.4 " + doc.encode())
    return folder / room


def test_document_store_holds_a_room_and_the_local_copy_goes(empty):
    folder = _local_room(store.DATA_ROOM)
    from_files = store.load_chunks("T9")
    mem = doc_store.use_memory()
    out = data_room.move_to_mongo(with_pdfs=True, verbose=False)
    assert [(r["room"], r["pages"], r["documents"], r["pdfs"], r["verified"], r["local_deleted"]) for r in out] == [("T9", 3, 2, 2, True, True)]
    assert not folder.exists() and store.load_chunks("T9") == from_files           # the same shape from the store as from the files
    assert doc_store.list_rooms() == [{"room": "T9", "documents": 2, "pages": 3, "pdfs": 2}]
    assert doc_store.get_pdf("T9", "doc-02") == b"%PDF-1.4 DOC-02_Budget.pdf"
    stored = next(c for c in mem.room_chunks("T9") if (c["doc_id"], c["page"]) == ("DOC-01", 1))
    assert stored["method"] == "ocr" and len(stored["sha256"]) == 64 and stored["created_at"]
    assert scoring.quote_is_real("QRE of $24,600,000", store.load_chunks("T9")["DOC-02"], 1) == "Real"
    doc_store.delete_room("T9")
    assert doc_store.list_rooms() == [] and store.load_chunks("T9") == {}


def test_failed_verification_keeps_the_local_files(empty, monkeypatch):
    folder = _local_room(store.DATA_ROOM)
    mem = doc_store.use_memory()
    real_replace = mem.replace_room
    monkeypatch.setattr(mem, "replace_room", lambda room, chunks, docs, pdfs: real_replace(room, chunks[:-1], docs, pdfs))
    out = data_room.move_to_mongo(verbose=False)
    assert out[0]["verified"] is False and out[0]["local_deleted"] is False and folder.exists()
    assert any("missing" in p or "expected" in p for p in out[0]["problems"])
    doc_store.use_settings()
    with pytest.raises(doc_store.StoreUnavailable, match="MONGO_URI is not set"):
        data_room.move_to_mongo(verbose=False)


def test_store_that_cannot_be_reached_leaves_scoring_working(empty, monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://db.example.com:27017/")          # not local, and no TLS
    assert store.load_chunks("T1") == {} and "TLS is required" in store.chunks_problem()
    res = scoring.score_run(run([F_CREDIT]), CASES, reviews={})
    assert res["metrics"]["found"] == 1 and res["rows"][0]["real"] == ["Not checked", "Not checked"]
    monkeypatch.setenv("MONGO_URI", "mongodb+srv://u:p@cluster0.example.mongodb.net/")
    with pytest.raises(doc_store.StoreUnavailable, match="EVAL_ALLOWED_HOSTS"):
        doc_store.check_uri(doc_store.uri())
    monkeypatch.setenv("EVAL_ALLOWED_HOSTS", "generativelanguage.googleapis.com, example.mongodb.net")
    doc_store.check_uri(doc_store.uri())
    doc_store.check_uri("mongodb://admin:secret@localhost:27017/?authSource=admin")


@pytest.mark.skipif(not MONGO_URI_TEST, reason="set MONGO_URI_TEST to run against a real MongoDB")
def test_document_store_against_a_real_mongodb(empty, monkeypatch):
    monkeypatch.setenv("MONGO_URI", MONGO_URI_TEST)
    monkeypatch.setenv("MONGO_DB", "dataroom_eval_test")
    doc_store.use_settings()
    try:
        doc_store.save_room("T9", ROWS, {"DOC-01_Part1.pdf": b"%PDF one"})
        assert doc_store.verify_room("T9", ROWS, {"DOC-01_Part1.pdf": b"%PDF one"}) == {"ok": True, "problems": []}
        assert store.load_chunks("T9")["DOC-01"][2].strip() == "Building A only." and doc_store.get_pdf("T9", "DOC-01") == b"%PDF one"
        assert doc_store.verify_room("T9", ROWS + [{"doc_id": "DOC-03", "page": 1, "text": "x"}])["ok"] is False
    finally:
        doc_store.delete_room("T9")
        doc_store.backend().client.drop_database("dataroom_eval_test")


# ---- the app, once through ------------------------------------------------------------------------------------

def test_app_runs_end_to_end(repo, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(judge, "_client", lambda: CheckClient(leftover=_REAL))
    payload = _json.loads((ROOT / "submissions" / "baseline" / "CHATGPT-HTC02-R1.json").read_text(encoding="utf-8"))
    payload = {"result": {"discrepancies": payload["findings"][:4] + [NEW_ISSUE]}}
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not at.exception and at.header[0].value == "Vericap run check"

    def press(label):
        next(b for b in at.button if b.label.startswith(label)).click().run()
        assert not at.exception, at.exception

    at.selectbox(key="rc_room").set_value("HTC02").run()
    at.text_area(key="rc_text").set_value("{not json").run()
    press("Read the run")
    assert "Not valid JSON" in at.error[0].value
    at.text_area(key="rc_text").set_value(_json.dumps(payload)).run()
    press("Read the run")
    press("Run the check")
    labels = [m.label for m in at.metric]
    assert labels == ["Accuracy", "Found", "Partially found", "Missed", "Backed by documents", "Newly found"]
    assert any("Rank" in m.value for m in at.markdown) and any(r.label == "Decision" for r in at.radio)
    for box in (True, False):
        for screen in ("Overview", "Run detail", "Compare"):
            at.sidebar.checkbox[0].set_value(box)
            at.sidebar.radio[0].set_value(screen).run()
            assert not at.exception, (screen, box, at.exception)
    for screen in ("Upload evaluation sheet", "Rules and facts"):
        at.sidebar.radio[0].set_value(screen).run()
        assert not at.exception, (screen, at.exception)
    assert (ROOT / "answer_key" / "library_v1.json").read_bytes() == (repo / "answer_key" / "library_v1.json").read_bytes()
