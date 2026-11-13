"""Reads the sheet export and parses every tab into memory. Nothing is written here."""
from __future__ import annotations

import io
import json

from .. import context, contract, import_sheet, store
from ..import_sheet import _s


def read(source, name: str = "") -> dict[str, list[dict]]:
    """The workbook as {tab: [row dicts]}. `source` is a path, or the bytes of an uploaded .xlsx or .json."""
    if isinstance(source, (bytes, bytearray)):
        if name.lower().endswith(".json"):
            return json.loads(bytes(source).decode("utf-8"))
        return import_sheet.read_workbook(io.BytesIO(bytes(source)))
    return import_sheet.read_workbook(source)


def _iso(v) -> str:
    """A date cell as YYYY-MM-DD when it can be read as a date, otherwise the text as written."""
    text = _s(v)
    d = context.as_date(text)
    return d.isoformat() if d else text


def _yes(v, default: bool = False) -> bool:
    text = _s(v).lower()
    return default if not text else text in ("yes", "y", "true", "1", "on")


def _source(v):
    cits = contract.parse_citations(_s(v))
    return cits[0] if cits else ""


def build_documents(rows: list[dict]) -> list[dict]:
    return [{
        "data_room": _s(r.get("Data room")), "doc_id": _s(r.get("Document ID")).upper(), "title": _s(r.get("Title")),
        "type": _s(r.get("Document type")), "role": _s(r.get("Role")), "status": _s(r.get("Status")),
        "format": _s(r.get("Format")), "pages": r.get("Pages") if isinstance(r.get("Pages"), (int, float)) else _s(r.get("Pages")),
        "doc_date": _iso(r.get("Document date")),
        "authority": contract._label(r.get("Authority"), context.AUTHORITY) or _s(r.get("Authority")),
    } for r in rows if _s(r.get("Document ID"))]


def build_facts(rows: list[dict]) -> list[dict]:
    return [{
        "fact_id": _s(r.get("Fact ID")), "data_room": _s(r.get("Data room")),
        "subject": contract._label(r.get("Subject"), context.SUBJECTS) or _s(r.get("Subject")),
        "scope": _s(r.get("Scope")), "value": _s(r.get("Value")), "unit_basis": _s(r.get("Unit or basis")),
        "value_status": contract._label(r.get("Value status"), context.VALUE_STATUSES) or _s(r.get("Value status")),
        "as_of": _iso(r.get("As of")), "source": _source(r.get("Source")), "supersedes": _s(r.get("Supersedes")),
        "change_reason": _s(r.get("Change reason")), "change_source": _source(r.get("Change source")),
        "notes": _s(r.get("Notes")),
    } for r in rows if _s(r.get("Fact ID"))]


def build_rules(rows: list[dict]) -> list[dict]:
    defaults = {r["rule_id"]: r for r in context.DEFAULT_RULES}
    out = []
    for r in rows:
        rid = _s(r.get("Rule ID")).upper()
        if not rid:
            continue
        base = defaults.get(rid, {})
        out.append({**{k: v for k, v in base.items() if k in ("min_amount", "min_share")},
                    "rule_id": rid, "name": _s(r.get("Name")), "text": _s(r.get("Rule")),
                    "type": contract._label(r.get("Type"), context.RULE_TYPES) or _s(r.get("Type")),
                    "expected_class": _s(r.get("Expected class")),
                    "critical": _yes(r.get("Critical"), base.get("critical", False)), "on": _yes(r.get("On"), True),
                    "notes": _s(r.get("Notes"))})
    return out


def build_baselines(run_rows: list[dict], finding_rows: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """({run_id: run in the contract format}, {review key: the decision made by hand in the sheet})."""
    meta_by = {_s(r.get("Run ID")): r for r in run_rows if _s(r.get("Run ID"))}
    findings: dict[str, dict[str, dict]] = {}
    reviews: dict[str, dict] = {}
    for r in finding_rows:
        rid, fid = _s(r.get("Run ID")), _s(r.get("Finding ID"))
        if not rid or not fid:
            continue
        run_f = findings.setdefault(rid, {})
        if fid not in run_f:                     # first row of a finding carries its content
            run_f[fid] = {
                "finding_id": fid, "classification": r.get("Classification"), "severity": r.get("Severity"),
                "summary": _s(r.get("Summary")), "claims_compared": _s(r.get("Claims compared")),
                "citations": [c["raw"] for c in contract.parse_citations(_s(r.get("Citations")))],
                "explanation": _s(r.get("Explanation")), "confidence": r.get("Confidence"),
            }
        status = _s(r.get("Match status"))
        if status:                               # a hand-made decision exists for this row
            key = store.review_key(rid, fid)
            if key not in reviews:
                reasoning = r.get("Reasoning score")
                reviews[key] = {"status": status, "case_ids": [], "evidence": _s(r.get("Evidence check")) or None,
                                "reasoning": int(reasoning) if isinstance(reasoning, (int, float)) else None,
                                "note": _s(r.get("Reviewer note")), "decided_by": "sheet import", "decided_at": None}
            case = _s(r.get("Matched case ID"))
            if case and case not in reviews[key]["case_ids"]:
                reviews[key]["case_ids"].append(case)
    runs = {}
    for rid, run_f in findings.items():
        meta = meta_by.get(rid, {})
        model = _s(meta.get("Model or version")) or rid
        runs[rid] = {
            "run": {
                "run_id": rid, "data_room": _s(meta.get("Data room")) or next(iter(run_f)).split("-")[0],
                "source": _s(meta.get("Source")) or "Baseline model", "system": import_sheet._system_name(model),
                "model": model, "version": _s(meta.get("Prompt version")), "run_number": meta.get("Run number"),
                "started_at": _s(meta.get("Run date")) or None, "duration_minutes": meta.get("Time (minutes)"),
                "input_tokens": meta.get("Input tokens"), "output_tokens": meta.get("Output tokens"),
                "cost_usd": meta.get("Cost (USD)"), "access_route": _s(meta.get("Access route")) or None,
                "snapshot": _s(meta.get("Snapshot")) or None, "format_repairs": meta.get("Format repairs"),
                "notes": _s(meta.get("Notes")),
            },
            "findings": list(run_f.values()),
        }
    return runs, reviews


def stage(wb: dict[str, list[dict]]) -> dict:
    """Everything in the workbook, parsed and held in memory. A tab that is missing stays None, and what
    is stored for it is left alone."""
    tab = lambda name: wb.get(name) if name in wb else None
    runs, reviews = (build_baselines(wb.get("Baseline Runs", []), wb.get("Baseline Findings", []))
                     if "Baseline Findings" in wb else (None, None))
    return {
        "cases": import_sheet.build_cases(tab("Ground Truth")) if tab("Ground Truth") is not None else None,
        "case_rows": tab("Ground Truth"),
        "documents": build_documents(tab("Documents")) if tab("Documents") is not None else None,
        "facts": build_facts(tab("Fact Sheet")) if tab("Fact Sheet") is not None else None,
        "rules": build_rules(tab("Context Rules")) if tab("Context Rules") is not None else None,
        "runs": runs, "reviews": reviews, "tabs": sorted(wb),
    }
