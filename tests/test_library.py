"""Keeping the answer key up to date: candidates, freezing, rejections, and the sheet upload."""
import json as _json

from eval import library, store
from eval import reality_check as rc

from helpers import NEW_ISSUE, _REAL, CheckClient, _htc02_check


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
