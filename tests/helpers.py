"""Test data shared by the test files: a small answer key, findings, runs and stand-ins for the model."""
import json as _json
import re as _re

from eval import contract, providers, store
from eval import reality_check as rc


ROOT = store.ROOT


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


def _sheet():
    return _json.loads((ROOT / "answer_key" / "sheet_export_2026-11-11.json").read_text(encoding="utf-8"))
