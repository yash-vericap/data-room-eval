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
    cfg = providers.settings()
    assert cfg["provider"] == "github" and cfg["model"] == "openai/gpt-4.1-mini" and cfg["free"] and not cfg["problem"]
