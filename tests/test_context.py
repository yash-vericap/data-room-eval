"""The context layer: the rule pre-check on the two worked examples, the rule gate and the admission checklist."""
from eval import context, store
from eval import reality_check as rc

from helpers import CASES, DOCS, F_CREDIT, F_NOISE, F_REPRICED, F_STALE, PRICE, CheckClient, _check, finding


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
