"""Workbooks the screens hand out: the pending rows to paste into the sheet, and an empty template."""
from __future__ import annotations

import io

from .. import context, contract
from .changes import load_pending
from .columns import GT_COLUMNS, TABS


def case_row(case: dict, last_change: str = "") -> dict:
    """One case as a row of the Ground Truth tab, column for column."""
    yes = lambda v: "Yes" if v else "No"
    return {
        "Case ID": case["case_id"], "Classification": case.get("classification"), "Severity": case.get("severity"),
        "Weight": case.get("weight"), "Summary": case.get("summary"), "Claims compared": case.get("claims_compared"),
        "Citations": "\n".join(c["raw"] for c in case.get("citations") or []), "Explanation": case.get("explanation"),
        "Report": yes(case.get("report")), "Check type": case.get("check_type"), "Set": case.get("set"),
        "Data room": case.get("data_room"), "Documents": ", ".join(case.get("documents") or []),
        "Register IDs": ", ".join(case.get("register_ids") or []), "Fact or judgment": case.get("fact_or_judgment"),
        "Ambiguous": yes(case.get("ambiguous")), "Alternative readings": case.get("alternative_readings"),
        "Open questions": case.get("open_questions"), "Scenario tags": "; ".join(case.get("scenario_tags") or []),
        "Snapshot": "", "Review status": case.get("review_status") or "Draft",
        "Last change": last_change or case.get("origin") or "",
    }


def _xlsx(sheets: dict[str, tuple[list[str], list[dict]]]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for title, (columns, rows) in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(columns)
        for r in rows:
            ws.append([r.get(c) for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pending_xlsx() -> bytes:
    """The pending rows, ready to paste into the sheet: accepted cases in the Ground Truth columns, and the
    correction requests on a second tab."""
    pending = load_pending()
    cases = [case_row(p["case"]) for p in pending if p["kind"] == "case"]
    fixes = [{"Case ID": p["case_id"], "What is wrong": p["what"], "Corrected value or label": p["corrected"],
              "Reason": p["reason"], "From check": p["check_id"], "Requested at": p["at"]}
             for p in pending if p["kind"] == "correction"]
    return _xlsx({"Ground Truth": (GT_COLUMNS, cases),
                  "Corrections": (["Case ID", "What is wrong", "Corrected value or label", "Reason", "From check",
                                   "Requested at"], fixes)})


def template_xlsx() -> bytes:
    """An empty workbook with every tab and column the upload reads. The Context Rules tab carries the
    default rules, so they can be edited in the sheet."""
    rules = [{"Rule ID": r["rule_id"], "Name": r["name"], "Rule": r["text"], "Type": r["type"],
              "Expected class": r["expected_class"], "Critical": "Yes" if r["critical"] else "No", "On": "Yes",
              "Notes": ""} for r in context.DEFAULT_RULES]
    weights = [{"Severity": s, "Weight": w} for s, w in contract.WEIGHTS.items()]
    return _xlsx({tab: (cols, rules if tab == "Context Rules" else weights if tab == "Severity Weights" else [])
                  for tab, cols in TABS.items()})
