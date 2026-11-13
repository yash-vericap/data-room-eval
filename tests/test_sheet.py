"""The sheet upload: preview, blocking errors, confirming, stale verdicts, pending rows and the new tabs."""
import io

import pytest
from openpyxl import load_workbook

from eval import context, library, store
from eval import reality_check as rc

from helpers import NEW_ISSUE, _REAL, CheckClient, _htc02_check, _sheet


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
    assert left["stale"] == ["HTC02-001"] and left["total"] == 0                     # the run stays complete
    assert next(r for r in rc.results(check, store.load_cases(store.DRAFT))["cases"] if r["case_id"] == "HTC02-001")["stale"]
    client = CheckClient()
    rc.run_check(check, store.load_cases(store.DRAFT), client=client, workers=1)
    assert client.asked == []                                                         # a normal run asks nothing
    rc.run_check(check, store.load_cases(store.DRAFT), client=client, workers=1, recheck=True)
    assert client.asked[0] == "HTC02-001" and rc.remaining(check, store.load_cases(store.DRAFT))["stale"] == []


def test_a_case_added_later_does_not_reopen_a_run(repo):
    check = _htc02_check()
    rc.run_check(check, store.load_cases(), client=CheckClient(), workers=1)
    wb = _sheet()
    extra = dict(next(r for r in wb["Ground Truth"] if r["Case ID"] == "HTC02-001"), **{"Case ID": "HTC02-099"})
    wb["Ground Truth"].append(extra)
    library.apply(library.stage(wb), "sheet.xlsx")
    draft = store.load_cases(store.DRAFT)
    assert rc.remaining(check, draft)["total"] == 0 and rc.added_since(check, draft) == ["HTC02-099"]
    assert "HTC02-099" not in {r["case_id"] for r in rc.results(check, draft)["cases"]}  # not part of this run's result
    client = CheckClient()
    rc.run_check(check, draft, client=client, workers=1, recheck=True)               # only when asked for
    assert client.asked == ["HTC02-099"] and rc.added_since(check, draft) == []


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
    book = load_workbook(io.BytesIO(library.template_xlsx()))
    assert set(library.TABS) == set(book.sheetnames) and [c.value for c in book["Fact Sheet"][1]] == library.FACT_COLUMNS
