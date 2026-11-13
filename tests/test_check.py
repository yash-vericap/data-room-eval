"""The run check: verdicts, partial credit, manual verdicts, stopping and carrying on, focused messages."""
from eval import context, contract
from eval import reality_check as rc

from helpers import CASES, F_CREDIT, F_DRAFT, F_NOISE, PRICE, CheckClient, _check


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


def test_focused_check_sends_only_related_findings_and_decides_unrelated_cases_by_rule(empty, monkeypatch):
    monkeypatch.setenv("EVAL_RC_FOCUS", "1")
    check = _check([F_CREDIT, F_DRAFT, F_NOISE])
    client = CheckClient()
    seen = []
    real = client.complete
    client.complete = lambda model, system, message, schema: (seen.append(message), real(model, system, message, schema))[1]
    rc.run_check(check, CASES, client=client, workers=1)
    v = check["case_verdicts"]["T1-003"]                         # the developer fee: no finding is about it
    assert (v["status"], v["by_rule"], v["sent"]["model"]) == (rc.MISSED, True, "no model call") and "T1-003" not in client.asked
    msg = next(m for m in seen if "ID: T1-001" in m)
    assert '<finding id="F1">' in msg and "F3" not in msg and "share no document, figure or wording" in msg
    assert "C1 Documented change (Reject)" in msg and "old and new values are not a discrepancy" not in msg   # rule names only
    row = next(r for r in rc.results(check, CASES, {})["cases"] if r["case_id"] == "T1-003")
    assert row["by_rule"] and rc.models_used(check)["no model call"] == 1
    assert rc.remaining(check, CASES)["total"] == 0


def test_a_page_with_several_quotes_is_sent_once():
    text = "Intro. " + "x " * 800 + "credit of $5,120,000 here. " + "y " * 50 + "QRE of $24,600,000 there. " + "z " * 800
    cits = contract.parse_citations("DOC-05 p.2: '$5,120,000' || DOC-05 p.2: '$24,600,000'")
    block, sent = rc._pages_block(cits, {"DOC-05": {2: text}}, 300)
    assert sent == [["DOC-05", 2]] and block.count("<page ") == 1 and "$5,120,000" in block and "$24,600,000" in block
