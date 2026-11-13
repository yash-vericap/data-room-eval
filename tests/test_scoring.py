"""Checks on the parts that decide a baseline score: citations, values, the contract, matching and quotes."""
from eval import contract, scoring
from eval.matching import key_values

from helpers import CASES, F_CREDIT, F_DRAFT, F_NOISE, run


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
