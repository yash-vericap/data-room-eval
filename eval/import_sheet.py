"""Brings the evaluation sheet into the tool.

Input: the .xlsx download of the sheet (sheets "Ground Truth", "Documents", "Baseline Runs",
"Baseline Findings"), or a JSON export with the same sheet names and one dict per row.

Output:
  answer_key/library_<snapshot>.json   the answer key, development and withheld cases together
  answer_key/documents.json            the document list of every data room
  submissions/baseline/<run>.json      one contract file per baseline run
  reviews/decisions.json               the matches, evidence checks and reasoning scores made by hand
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import contract, store


def read_workbook(path: str | Path) -> dict[str, list[dict]]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        recs = []
        for r in rows[1:]:
            rec = {h: (v.isoformat() if hasattr(v, "isoformat") else v) for h, v in zip(header, r) if h}
            if any(v not in (None, "") for v in rec.values()):
                recs.append(rec)
        out[ws.title] = recs
    return out


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _list(v, sep=",") -> list[str]:
    return [p.strip() for p in re.split(rf"\s*[{sep}]\s*", _s(v)) if p.strip()]


_SYSTEM_NAMES: dict[str, str] = {}


def _system_name(model: str) -> str:
    """Different spellings of one model ('models/gemini-3.8-flash', 'Gemini 3.8 Flash') -> one name."""
    cleaned = model.replace("models/", "").strip()
    key = re.sub(r"[^a-z0-9.]+", " ", cleaned.lower()).strip()
    if key not in _SYSTEM_NAMES:
        _SYSTEM_NAMES[key] = cleaned if any(ch.isupper() for ch in cleaned) else key.title()
    return _SYSTEM_NAMES[key]


def build_cases(rows: list[dict]) -> list[dict]:
    cases = []
    for r in rows:
        if not _s(r.get("Case ID")):
            continue
        sev = contract._label(r.get("Severity"), contract.SEVERITIES)
        cases.append({
            "case_id": _s(r["Case ID"]),
            "data_room": _s(r.get("Data room")) or _s(r["Case ID"]).split("-")[0],
            "classification": contract._label(r.get("Classification"), contract.CLASSES),
            "severity": sev,
            "weight": contract.WEIGHTS.get(sev, 0),
            "report": _s(r.get("Report")).lower() == "yes",
            "set": _s(r.get("Set")) or "Withheld",
            "summary": _s(r.get("Summary")),
            "claims_compared": _s(r.get("Claims compared")),
            "citations": contract.parse_citations(_s(r.get("Citations"))),
            "explanation": _s(r.get("Explanation")),
            "check_type": _s(r.get("Check type")),
            "documents": _list(r.get("Documents")),
            "register_ids": _list(r.get("Register IDs")),
            "fact_or_judgment": _s(r.get("Fact or judgment")),
            "ambiguous": _s(r.get("Ambiguous")).lower() == "yes",
            "alternative_readings": _s(r.get("Alternative readings")),
            "open_questions": _s(r.get("Open questions")),
            "scenario_tags": _list(r.get("Scenario tags"), sep=";"),
            "snapshot": _s(r.get("Snapshot")) or "Library v1",
            "review_status": _s(r.get("Review status")),
        })
    return cases


def run_import(path: str | Path, verbose: bool = True) -> dict:
    wb = read_workbook(path)
    summary = {}

    cases = build_cases(wb.get("Ground Truth", []))
    by_snapshot: dict[str, list[dict]] = {}
    for c in cases:
        by_snapshot.setdefault(c["snapshot"], []).append(c)
    for snap, group in by_snapshot.items():
        name = "library_" + re.sub(r"[^a-z0-9]+", "", snap.lower().replace("library", ""))
        store._write(store.ANSWER_KEY / f"{name}.json", {"snapshot": snap, "cases": group})
        summary[name] = len(group)

    docs = [{
        "data_room": _s(r.get("Data room")), "doc_id": _s(r.get("Document ID")), "title": _s(r.get("Title")),
        "type": _s(r.get("Document type")), "role": _s(r.get("Role")), "status": _s(r.get("Status")),
        "format": _s(r.get("Format")),
    } for r in wb.get("Documents", []) if _s(r.get("Document ID"))]
    if docs:
        store._write(store.ANSWER_KEY / "documents.json", docs)
        summary["documents"] = len(docs)

    run_rows = {_s(r.get("Run ID")): r for r in wb.get("Baseline Runs", []) if _s(r.get("Run ID"))}
    findings: dict[str, dict[str, dict]] = {}
    reviews = store.load_reviews()
    for r in wb.get("Baseline Findings", []):
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
            case = _s(r.get("Matched case ID"))
            rv = reviews.get(key) if reviews.get(key, {}).get("decided_by") == "sheet import" and key in _seen else None
            if rv is None:
                reasoning = r.get("Reasoning score")
                rv = {"status": status, "case_ids": [], "evidence": _s(r.get("Evidence check")) or None,
                      "reasoning": int(reasoning) if isinstance(reasoning, (int, float)) else None,
                      "note": _s(r.get("Reviewer note")), "decided_by": "sheet import", "decided_at": None}
                reviews[key] = rv
                _seen.add(key)
            if case and case not in rv["case_ids"]:
                rv["case_ids"].append(case)
    for rid, run_f in findings.items():
        meta = run_rows.get(rid, {})
        model = _s(meta.get("Model or version")) or rid
        payload = {
            "run": {
                "run_id": rid, "data_room": _s(meta.get("Data room")) or next(iter(run_f)).split("-")[0],
                "source": _s(meta.get("Source")) or "Baseline model", "system": _system_name(model), "model": model,
                "version": _s(meta.get("Prompt version")), "run_number": meta.get("Run number"),
                "started_at": _s(meta.get("Run date")) or None, "duration_minutes": meta.get("Time (minutes)"),
                "input_tokens": meta.get("Input tokens"), "output_tokens": meta.get("Output tokens"),
                "cost_usd": meta.get("Cost (USD)"), "access_route": _s(meta.get("Access route")) or None,
                "snapshot": _s(meta.get("Snapshot")) or None, "format_repairs": meta.get("Format repairs"),
                "notes": _s(meta.get("Notes")),
            },
            "findings": list(run_f.values()),
        }
        folder = "baseline" if payload["run"]["source"] == "Baseline model" else "system"
        store.save_submission(payload, folder=folder, allow_problems=True)
    store._write(store.REVIEWS, reviews)
    summary["runs"] = len(findings)
    summary["findings"] = sum(len(v) for v in findings.values())
    summary["manual decisions"] = len(_seen)
    if verbose:
        for k, v in summary.items():
            print(f"{k}: {v}")
    return summary


_seen: set[str] = set()
