"""Brings the evaluation sheet into the tool.

Input: the .xlsx download of the sheet (sheets "Ground Truth", "Documents", "Baseline Runs",
"Baseline Findings"), or a JSON export with the same sheet names and one dict per row.

Optional tabs "Fact Sheet" and "Context Rules", and the optional Documents columns "Document date" and
"Authority", are read too. The staging, the checks, the preview and the writing live in eval/library.py;
this module keeps the workbook reader and the Ground Truth parser.

Output (only after confirmation):
  answer_key/library_draft.json        the working draft of the answer key
  answer_key/documents.json            the document list of every data room
  answer_key/facts.json                the fact sheet
  answer_key/context_rules.json        the context rules
  submissions/baseline/<run>.json      one contract file per baseline run
  reviews/decisions.json               the matches, evidence checks and reasoning scores made by hand
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import contract


def read_workbook(path) -> dict[str, list[dict]]:
    """{tab: [one dict per row]} from an .xlsx path, an open .xlsx file, or a .json export."""
    if not hasattr(path, "read"):
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
            "origin": _s(r.get("Last change")) if "found by run" in _s(r.get("Last change")).lower() else "",
        })
    return cases


def run_import(path: str | Path, verbose: bool = True, write: bool = False, note: str = "") -> dict:
    """Shows what the sheet export would change and, with write=True, writes it. The parsing, the
    checks and the writing are the same code the Upload evaluation sheet screen uses (eval/library.py)."""
    from . import library
    staged = library.stage(read_workbook(path))
    problems, pv = library.validate(staged), library.preview(staged)
    say = print if verbose else (lambda *a: None)
    for t in pv["tabs"]:
        say(f"{t['tab']}: {t['new']} new, {t['changed']} changed, {t['removed']} removed")
    for c in pv["changes"].get("Ground Truth", {}).get("changed", []):
        say(f"  {c['id']}: " + ", ".join(c["fields"]))
    for w in problems["warnings"]:
        say(f"warning: {w}")
    for e in problems["errors"]:
        say(f"error: {e}")
    out = {"preview": pv, "errors": problems["errors"], "warnings": problems["warnings"], "written": False}
    if problems["errors"]:
        say("Nothing was written: fix the errors in the sheet first.")
    elif not write:
        say("Nothing was written. Run again with --yes to write these changes.")
    else:
        res = library.apply(staged, Path(str(path)).name, note)
        out["written"] = True
        say(f"Written. {res['logged']} change-log entries. Cases went to the working draft; freeze it to score against it.")
    return out
