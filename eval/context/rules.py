"""The context rules: the defaults, the bundle in force, and which cases test each rule."""
from __future__ import annotations

import os
import re

from .. import contract, store


SUBJECTS = ["QRE", "federal credit amount", "state credit amount", "credit price", "credit type", "equity amount",
            "loan amount", "developer fee", "total development cost", "placed in service date", "completion date",
            "Part 2 approval date", "Part 3 approval date", "closing date", "ownership share", "scope", "other"]
VALUE_STATUSES = ["Actual", "Signed", "Approved", "Estimate", "Target", "Projected", "Draft", "Superseded"]
FORECAST = {"Estimate", "Target", "Projected"}
ACTUAL = {"Actual"}
AUTHORITY = ["Executed legal document", "Government approval", "Third-party certification",
             "Lender or investor document", "Financial model", "Presentation or summary", "Correspondence", "Draft"]
RULE_TYPES = ["Reject", "Flag", "Guide"]
TAG_RULE = {"Known change": "C1", "Stale value": "C2", "Unexplained change": "C3", "Two forecasts": "C4",
            "Forecast against actual": "C5", "Two actuals": "C6", "Different basis": "C9"}
FLAG_TAGS = {"Stale value", "Unexplained change", "Two actuals"}


def _rule(rule_id, type_, name, text, expected="", critical=True, **extra):
    return {"rule_id": rule_id, "name": name, "text": text, "type": type_, "expected_class": expected,
            "critical": critical, "on": True, "notes": "", **extra}


DEFAULT_RULES = [
    _rule("C1", "Reject", "Documented change",
          "When a value changes through a dated document that records the change and its reason (an amendment, a "
          "repricing letter, a rate reset, a signed change order), the old and new values are not a discrepancy "
          "between themselves.", "Contextual difference"),
    _rule("C2", "Flag", "Stale value after a change",
          "A document dated after a change, or presented as current (a revised deck, a snapshot sent to a buyer), that "
          "still carries the old value is a discrepancy. C1 never covers this case.", "Contradiction"),
    _rule("C3", "Flag", "Unexplained change",
          "Two values for the same subject and scope, both presented as current, with no document recording a change, "
          "are a contradiction. When a change is mentioned but the document that records it is missing, the issue is "
          "missing evidence.", "Contradiction, or Insufficient evidence"),
    _rule("C4", "Reject", "Two forecasts",
          "Estimated, target, anticipated, scheduled, projected and expected dates or figures are forecasts. Two "
          "forecasts that differ, in documents of different dates, are not a contradiction: the forecast moved. Two "
          "forecasts that differ in documents of the same date or version are a contradiction, and this rule does not "
          "reject them.", "Contextual difference"),
    _rule("C5", "Reject", "Forecast against actual",
          "A forecast that differs from a later actual value is not a contradiction. A document dated after the actual "
          "value that still presents the forecast as current falls under C2.", "Contextual difference"),
    _rule("C6", "Flag", "Two actuals",
          "Two values stated as actual for the same event (placed in service, completion, closing) that differ are a "
          "contradiction, whatever the documents are.", "Contradiction"),
    _rule("C7", "Flag", "Unexplained delay that matters",
          "An actual date later than a forecast or a deadline in a legal document is missing evidence when the delay "
          "changes something that matters (the credit year, a loan maturity, an investor installment, a compliance "
          "period) and no document explains it, even though the dates are not a contradiction.", "Insufficient evidence"),
    _rule("C8", "Reject", "Signed against draft",
          "Where a signed and a draft version differ, the signed one governs and the difference is not a discrepancy. "
          "A document that relies on the draft's figure falls under C2.", "Contextual difference"),
    _rule("C9", "Reject", "Different basis",
          "Different units, scope (one building against the project), basis (gross against net, per credit against "
          "total) or phase are not a discrepancy once converted to the same basis. Values that still differ after "
          "conversion are not rejected.", "Contextual difference"),
    _rule("C10", "Guide", "Authority",
          "When documents conflict, the more authoritative document is taken as correct when naming the stale one. "
          "The conflict is still reported.", "", critical=False),
    _rule("C11", "Reject", "Same event",
          "Two dates are compared only when they refer to the same event. \"Launched\", \"opened\" or \"began "
          "operations\" are not the same as \"placed in service\" unless the fact sheet maps them to the same subject."),
    _rule("C12", "Reject", "Immaterial difference",
          "Rounding, formatting, typing errors and naming variants that do not change the meaning are not red flags. "
          "A money difference within the threshold (the larger of $1,000 and 0.5% of the larger value) is immaterial.",
          "Consistent", min_amount=1000, min_share=0.005),
    _rule("C13", "Reject", "Decided before",
          "A finding that matches a candidate the evaluator already rejected in an earlier check, on the same data "
          "room and answer key, gets the same decision.", "(as decided)", critical=False),
    _rule("C14", "Reject", "Evidence not found",
          "Every quote the finding gives is missing from the documents, and the judge found the claim is not in the "
          "pages. The finding is made up or misread."),
    _rule("C15", "Reject", "Out of scope",
          "Advice, recommendations, best practice and general risks that are not a conflict between documents or a "
          "missing piece of evidence the deal relies on.", "", critical=False),
]
RULE_FIELDS = ["rule_id", "name", "text", "type", "expected_class", "critical", "on"]
FACT_FIELDS = ["fact_id", "data_room", "subject", "scope", "value", "unit_basis", "value_status", "as_of", "source",
               "supersedes", "change_reason", "change_source", "notes"]
SEVERITY_ORDER = {s: i for i, s in enumerate(reversed(contract.SEVERITIES))}     # Low 0 ... Critical 3


def load_rules() -> list[dict]:
    """The rule bundle: the uploaded rules, or the defaults when no Context Rules tab was ever uploaded."""
    rules = store._read(store.ANSWER_KEY / "context_rules.json")
    return rules if rules else [dict(r) for r in DEFAULT_RULES]


def rules_on(rules: list[dict] | None = None) -> list[dict]:
    return [r for r in (load_rules() if rules is None else rules) if r.get("on", True)]


def rule_name(rule_id: str | None, rules: list[dict] | None = None) -> str:
    r = next((r for r in (load_rules() if rules is None else rules) if r["rule_id"] == rule_id), None)
    return f"{rule_id} {r['name']}" if r else (rule_id or "")


def min_candidate_severity() -> str:
    return contract._label(os.environ.get("EVAL_MIN_CANDIDATE_SEVERITY"), contract.SEVERITIES) or "Medium"


def case_rules(case: dict, rules: list[dict] | None = None) -> list[str]:
    """Rule IDs a case is a test case for: those named in its scenario tags."""
    ids = {r["rule_id"].upper() for r in (load_rules() if rules is None else rules)}
    found = []
    for tag in case.get("scenario_tags") or []:
        m = re.match(r"\s*(C\d+)\b", str(tag), re.I)
        if m and m.group(1).upper() in ids and m.group(1).upper() not in found:
            found.append(m.group(1).upper())
    return found


def coverage(cases: list[dict], rules: list[dict] | None = None) -> list[dict]:
    """Test cases per rule and data room. A Reject rule needs a non-issue case, a Flag rule a reportable one."""
    rules = load_rules() if rules is None else rules
    rooms = sorted({c["data_room"] for c in cases})
    rows = []
    for r in rules:
        for room in rooms:
            mine = [c for c in cases if c["data_room"] == room and r["rule_id"] in case_rules(c, rules)]
            rep, non = sum(bool(c["report"]) for c in mine), sum(not c["report"] for c in mine)
            need = "non-issue case" if r["type"] == "Reject" else "reportable case" if r["type"] == "Flag" else ""
            gap = bool(r.get("critical")) and ((r["type"] == "Reject" and not non) or (r["type"] == "Flag" and not rep))
            rows.append({"rule_id": r["rule_id"], "name": r["name"], "type": r["type"], "critical": bool(r.get("critical")),
                         "data_room": room, "reportable": rep, "non_issue": non, "gap": gap,
                         "needs": f"at least one {need}" if gap else ""})
    return rows
