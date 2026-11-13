"""Reading a run in any JSON shape."""
import json as _json

import pytest

from eval import reality_check as rc

from helpers import ODD, ROOT


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


def test_reading_the_vericap_investigation_format():
    payload = {"schema_version": "1.0", "investigation": {"id": "inv_e178", "status": "completed", "documents": [
                   {"filename": "DOC-02_Part2.pdf", "file_type": "pdf", "findings_count": 1}]},
               "summary": {"overview": "2 documents reviewed.", "totals": {"findings": 3, "by_category": {"contradiction": 1}}},
               "findings": [{"id": "fnd_01", "category": "missing_information", "subcategory": None, "severity": "informational",
                             "title": "Cornice removed against the NPS condition", "description": "The plan removes the cornice; Part 2 requires it kept.",
                             "confidence": 0.8, "documents": ["DOC-02_Part2.pdf", "15_Phased_Plan.pdf"],
                             "evidence": [{"document": "DOC-02_Part2.pdf", "file_type": "pdf", "role": "supporting", "note": "the condition",
                                           "location": {"page": 4, "section": "Conditions", "sheet": None, "cell_range": None},
                                           "quote": "They must be retained and repaired in situ"}],
                             "open_questions": ["Was the condition waived?"]}]}
    r = rc.read_findings(payload)
    f = r["findings"][0]
    assert r["source_path"] == "$.findings" and r["run_meta"]["run_id"] == "inv_e178" and r["run_meta"]["summary"]["totals"]["findings"] == 3
    assert (f["finding_id"], f["classification"], f["severity"], f["confidence"]) == ("fnd_01", "Insufficient evidence", "Low", 0.8)
    assert f["summary"].startswith("Cornice removed") and f["claims_compared"].startswith("The plan removes")
    assert f["explanation"] == "Open questions: Was the condition waived?"
    c = f["citations"][0]
    assert (c["doc_id"], c["page"], c["location"], c["quote"]) == ("DOC-02", 4, "Conditions", "They must be retained and repaired in situ")
    assert [x["doc_id"] for x in f["citations"]] == ["DOC-02", "DOC-15"]            # the second from the file's leading number
    assert any("15_Phased_Plan.pdf read as DOC-15" in n for n in r["notes"]) and any("says 3 findings, but 1" in n for n in r["notes"])
    assert rc._classification("contextual_difference") == "Contextual difference" and rc._severity("critical") == "Critical"


def test_reading_a_contract_file():
    payload = _json.loads((ROOT / "submissions" / "baseline" / "CHATGPT-HTC02-R1.json").read_text(encoding="utf-8"))
    r = rc.read_findings(payload)
    assert r["source_path"] == "$.findings" and len(r["findings"]) == len(payload["findings"])
    assert [len(f["citations"]) for f in r["findings"]] == [len(f["citations"]) for f in payload["findings"]]
    assert all(f["classification"] and f["severity"] for f in r["findings"])
