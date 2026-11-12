"""Keeping the answer key up to date: the sheet upload, the working draft, snapshots and the change log.

The evaluation sheet stays the place where cases, facts, documents, rules and baseline runs are written.
This module loads its export in three steps, so nothing is written by accident:

    staged = stage(read(file))          parse every tab into memory
    problems = validate(staged)         blocking errors and warnings
    changes = preview(staged)           what is new, changed and removed, field by field
    apply(staged, file_name, note)      write, and log every changed object

It also holds what lives between two uploads:
- answer_key/library_draft.json       the working draft (uploads and accepted candidates write here)
- answer_key/library_vN.json          frozen snapshots, never changed after freeze()
- answer_key/pending.json             accepted candidates and correction requests not yet in the sheet
- answer_key/rejected_candidates.json findings the evaluator rejected, so they are not reviewed twice
- answer_key/changelog.json           one entry per change, with its reason
"""
from __future__ import annotations

import copy
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import context, contract, import_sheet, scoring, store
from .import_sheet import _list, _s

GT_COLUMNS = ["Case ID", "Classification", "Severity", "Weight", "Summary", "Claims compared", "Citations", "Explanation",
              "Report", "Check type", "Set", "Data room", "Documents", "Register IDs", "Fact or judgment", "Ambiguous",
              "Alternative readings", "Open questions", "Scenario tags", "Snapshot", "Review status", "Last change"]
DOC_COLUMNS = ["Document ID", "Data room", "Title", "Document type", "Role", "Status", "Format", "Pages", "Document date",
               "Authority"]
FACT_COLUMNS = ["Fact ID", "Data room", "Subject", "Scope", "Value", "Unit or basis", "Value status", "As of", "Source",
                "Supersedes", "Change reason", "Change source", "Notes"]
RULE_COLUMNS = ["Rule ID", "Name", "Rule", "Type", "Expected class", "Critical", "On", "Notes"]
RUN_COLUMNS = ["Run ID", "Model or version", "Data room", "Prompt version", "Run number", "Run date", "Access route",
               "Time (minutes)", "Format repairs", "Source"]
FINDING_COLUMNS = ["Finding ID", "Classification", "Severity", "Weight", "Summary", "Claims compared", "Citations",
                   "Explanation", "Run ID", "Confidence", "Matched case ID", "Match status", "Format repaired",
                   "Reviewer note", "Expected classification", "Case reportable", "Case weight", "Case severity",
                   "Case set", "Evidence check", "Reasoning score"]
TABS = {"Ground Truth": GT_COLUMNS, "Documents": DOC_COLUMNS, "Fact Sheet": FACT_COLUMNS, "Context Rules": RULE_COLUMNS,
        "Baseline Runs": RUN_COLUMNS, "Baseline Findings": FINDING_COLUMNS, "Severity Weights": ["Severity", "Weight"]}
CASE_SKIP = {"snapshot", "origin", "origin_check"}       # not compared between two versions of a case
ACCEPTED = "Accepted, not yet in the sheet"
CORRECTION = "Correction requested, not yet in the sheet"
REJECT_REASONS = ["Already in the ground truth", "Excused by a rule", "Not a major red flag",
                  "Not supported by the documents", "Out of scope", "Other"]


def _file(name: str) -> Path:
    return store.ANSWER_KEY / name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- change log ---------------------------------------------------------------------------------------------

def load_changelog() -> list[dict]:
    return store._read(_file("changelog.json"), []) or []


def log_many(entries: list[dict]) -> None:
    if not entries:
        return
    at = _now()
    rows = load_changelog()
    rows += [{"at": at, "by": "evaluator", "action": e["action"], "object": e["object"], "id": e["id"],
              "before": e.get("before"), "after": e.get("after"), "reason": e.get("reason") or "",
              "origin": e.get("origin") or ""} for e in entries]
    store._write(_file("changelog.json"), rows)


def log(action: str, obj: str, id_: str, before=None, after=None, reason: str = "", origin: str = "") -> None:
    log_many([{"action": action, "object": obj, "id": id_, "before": before, "after": after, "reason": reason,
               "origin": origin}])


# ---- working draft and snapshots ------------------------------------------------------------------------------

def ensure_draft() -> dict:
    """The working draft, created from the newest frozen snapshot the first time it is needed."""
    draft = store._read(_file("library_draft.json"))
    if draft is None:
        names = store.snapshots()
        cases = copy.deepcopy(store.load_cases(names[-1])) if names else []
        draft = {"snapshot": "Working draft", "base": names[-1] if names else None, "cases": cases}
        store._write(_file("library_draft.json"), draft)
    return draft


def draft_differs() -> int:
    """How many cases differ between the working draft and the newest frozen snapshot."""
    if not store.has_draft() or not store.snapshots():
        return 0
    d = diff(store.load_cases(), store.load_cases(store.DRAFT), "case_id", CASE_SKIP)
    return len(d["new"]) + len(d["changed"]) + len(d["removed"])


def freeze(reason: str = "") -> dict:
    """Writes the working draft as the next library_vN.json, with a copy of the facts and rules so an old
    score can be reproduced, logs it, and starts a fresh draft. Returns {"name", "cases", "pending"}."""
    draft = ensure_draft()
    names = store.snapshots()
    n = int(names[-1].split("_v")[1]) + 1 if names else 1
    name, label = f"library_v{n}", f"Library v{n}"
    cases = [{**c, "snapshot": label} for c in draft["cases"]]
    store._write(_file(f"{name}.json"), {"snapshot": label, "frozen_at": _now(), "cases": cases,
                                         "facts": context.load_facts(), "rules": context.load_rules()})
    store._write(_file("library_draft.json"), {"snapshot": "Working draft", "base": name, "cases": copy.deepcopy(cases)})
    pending = [p for p in load_pending() if p["kind"] == "case"]
    log("freeze", "case", name, before=names[-1] if names else None, after=f"{len(cases)} cases",
        reason=reason or f"Froze the working draft as {label}.", origin=name)
    return {"name": name, "cases": len(cases), "pending": len(pending)}


# ---- pending rows, rejected candidates, corrections -------------------------------------------------------------

def load_pending() -> list[dict]:
    return store._read(_file("pending.json"), []) or []


def load_rejected() -> list[dict]:
    return store._read(_file("rejected_candidates.json"), []) or []


def next_case_id(room: str) -> str:
    """The next free case ID for a data room, over every snapshot, the draft and the pending rows."""
    ids = [c["case_id"] for c in store.load_cases(store.DRAFT)] if (store.has_draft() or store.snapshots()) else []
    ids += [c["case_id"] for name in store.snapshots() for c in store.load_cases(name)]
    ids += [p["case_id"] for p in load_pending()]
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(rf"{re.escape(room)}-(\d+)", i))]
    return f"{room}-{max(nums, default=0) + 1:03d}"


def add_pending_case(case: dict, check_id: str, reason: str) -> dict:
    """An accepted candidate: stored as a pending row, added to the working draft at once, and logged."""
    draft = ensure_draft()
    if any(c["case_id"] == case["case_id"] for c in draft["cases"]):
        raise ValueError(f"Case {case['case_id']} already exists.")
    case = {**case, "snapshot": "Working draft", "origin_check": check_id}
    draft["cases"].append(case)
    store._write(_file("library_draft.json"), draft)
    store._write(_file("pending.json"), load_pending() + [{
        "kind": "case", "case_id": case["case_id"], "data_room": case["data_room"], "case": case, "status": ACCEPTED,
        "check_id": check_id, "reason": reason, "at": _now()}])
    log("accept", "candidate", case["case_id"], after=case["summary"], reason=reason, origin=check_id)
    return case


def add_rejected(finding: dict, room: str, reason: str, rule_id: str | None, check_id: str, snapshot: str = "") -> None:
    keep = {k: finding.get(k) for k in ("finding_id", "summary", "claims_compared", "explanation", "citations",
                                        "classification", "severity")}
    store._write(_file("rejected_candidates.json"), load_rejected() + [{
        "data_room": room, "finding": keep, "reason": reason, "rule_id": rule_id, "check_id": check_id,
        "snapshot": snapshot, "at": _now()}])
    log("reject", "candidate", f"{check_id}:{finding.get('finding_id')}", after=finding.get("summary"), reason=reason,
        origin=check_id)


def add_correction(case_id: str, room: str, what: str, corrected: str, reason: str, check_id: str) -> None:
    """'The ground truth is wrong here': a request, applied only when the corrected sheet is uploaded."""
    store._write(_file("pending.json"), load_pending() + [{
        "kind": "correction", "case_id": case_id, "data_room": room, "what": what, "corrected": corrected,
        "status": CORRECTION, "check_id": check_id, "reason": reason, "at": _now()}])
    log("correction", "case", case_id, before=what, after=corrected, reason=reason, origin=check_id)


# ---- cases as sheet rows, and the downloads -----------------------------------------------------------------------

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


# ---- reading and staging the sheet ---------------------------------------------------------------------------------

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


# ---- what is stored now, and the difference -----------------------------------------------------------------------

def current() -> dict:
    """What the tool holds today, in the same shape as stage()."""
    try:
        cases = store.load_cases(store.DRAFT)
    except FileNotFoundError:
        cases = []
    runs = {}
    for path in sorted((store.SUBMISSIONS / "baseline").glob("*.json")) if (store.SUBMISSIONS / "baseline").exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            runs[str((payload.get("run") or {}).get("run_id") or path.stem)] = payload
        except json.JSONDecodeError:
            continue
    return {"cases": cases, "documents": store._read(_file("documents.json"), []) or [], "facts": context.load_facts(),
            "rules": context.load_rules(), "runs": runs, "reviews": store.load_reviews()}


def _plain(v):
    """A value in the form two versions are compared in: citations by their text as written."""
    if isinstance(v, list) and v and all(isinstance(x, dict) and "raw" in x for x in v):
        return [x["raw"] for x in v]
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    return "" if v is None else v


def diff(old: list[dict], new: list[dict], key, skip: set[str] = frozenset()) -> dict:
    """{"new": [ids], "removed": [ids], "changed": [{"id", "fields": {field: [before, after]}}]}."""
    ident = (lambda r: tuple(r.get(k) for k in key)) if isinstance(key, tuple) else (lambda r: r.get(key))
    show = lambda i: " ".join(str(x) for x in i) if isinstance(i, tuple) else i
    a, b = {ident(r): r for r in old}, {ident(r): r for r in new}
    changed = []
    for i in b:
        if i in a:
            fields = {f: [a[i].get(f), b[i].get(f)] for f in sorted((set(a[i]) | set(b[i])) - set(skip))
                      if _plain(a[i].get(f)) != _plain(b[i].get(f))}
            if fields:
                changed.append({"id": show(i), "fields": fields})
    return {"new": [show(i) for i in b if i not in a], "removed": [show(i) for i in a if i not in b], "changed": changed}


def _differences(staged: dict, now: dict) -> dict:
    out = {}
    if staged["cases"] is not None:
        out["Ground Truth"] = diff(now["cases"], staged["cases"], "case_id", CASE_SKIP)
    if staged["documents"] is not None:
        out["Documents"] = diff(now["documents"], staged["documents"], ("data_room", "doc_id"))
    if staged["facts"] is not None:
        out["Fact Sheet"] = diff(now["facts"], staged["facts"], ("data_room", "fact_id"))
    if staged["rules"] is not None:
        out["Context Rules"] = diff(now["rules"], staged["rules"], "rule_id")
    if staged["runs"] is not None:
        a, b = now["runs"], staged["runs"]
        norm = lambda p: json.dumps(contract.normalise(p)[0], sort_keys=True, default=str)
        out["Baseline Runs"] = {"new": [r for r in b if r not in a], "removed": [],
                                "changed": [{"id": r, "fields": {}} for r in b if r in a and norm(a[r]) != norm(b[r])]}
        keep = lambda rv: {k: rv.get(k) for k in ("status", "case_ids", "evidence", "reasoning", "note")}
        mine = {k: rv for k, rv in staged["reviews"].items()
                if now["reviews"].get(k, {}).get("decided_by", "sheet import") == "sheet import"}
        out["Baseline decisions"] = {
            "new": [k for k in mine if k not in now["reviews"]], "removed": [],
            "changed": [{"id": k, "fields": {}} for k, rv in mine.items()
                        if k in now["reviews"] and keep(rv) != keep(now["reviews"][k])]}
    return out


def preview(staged: dict) -> dict:
    """What an upload would change. Nothing is written.

    {"tabs": [{"tab", "new", "changed", "removed"}], "changes": {tab: diff}, "pending_cleared": [...],
     "pending_kept": [...]}"""
    changes = _differences(staged, current())
    uploaded = {c["case_id"] for c in staged["cases"] or []}
    touched = {c["id"] for c in changes.get("Ground Truth", {}).get("changed", [])}
    cleared, kept = [], []
    for p in load_pending():
        done = p["case_id"] in uploaded if p["kind"] == "case" else p["case_id"] in touched
        (cleared if staged["cases"] is not None and done else kept).append(p)
    return {"tabs": [{"tab": t, "new": len(d["new"]), "changed": len(d["changed"]), "removed": len(d["removed"])}
                     for t, d in changes.items()],
            "changes": changes, "pending_cleared": cleared, "pending_kept": kept}


# ---- validation ---------------------------------------------------------------------------------------------------

def _dupes(ids: list) -> list:
    seen, out = set(), []
    for i in ids:
        if i in seen and i not in out:
            out.append(i)
        seen.add(i)
    return out


def _quote_result(room: str, cit: dict, chunk_cache: dict) -> str:
    if not cit or not cit.get("doc_id") or not cit.get("quote") or cit["quote"].startswith("["):
        return "Not checked"
    if room not in chunk_cache:
        chunk_cache[room] = store.load_chunks(room)
    pages = chunk_cache[room].get(cit["doc_id"])
    return scoring.quote_is_real(cit["quote"], pages, cit.get("page")) if pages else "Not checked"


def validate(staged: dict) -> dict:
    """{"errors": [...], "warnings": [...]}. Errors block the upload; warnings do not.

    A quote that is nowhere in its document is an error when its row is new or changed in this upload,
    and a warning when the row is as it was."""
    errors, warnings = [], []
    now = current()
    cases = staged["cases"] if staged["cases"] is not None else now["cases"]
    docs = staged["documents"] if staged["documents"] is not None else now["documents"]
    facts = staged["facts"] if staged["facts"] is not None else now["facts"]
    rules = staged["rules"] if staged["rules"] is not None else now["rules"]
    doc_ids = {(d["data_room"], d["doc_id"]) for d in docs}
    chunk_cache: dict = {}

    if staged["cases"] is not None:
        raw = {_s(r.get("Case ID")): r for r in staged["case_rows"] or []}
        old = {c["case_id"]: c for c in now["cases"]}
        errors += [f"Ground Truth: case ID {i} is used more than once." for i in _dupes([c["case_id"] for c in cases])]
        for c in cases:
            cid = c["case_id"]
            if not cid.startswith(c["data_room"] + "-"):
                errors.append(f"{cid}: the case ID does not start with its data room ({c['data_room']}).")
            if c["classification"] is None:
                errors.append(f"{cid}: classification {raw.get(cid, {}).get('Classification')!r} is not one of {contract.CLASSES}.")
            if c["severity"] is None:
                errors.append(f"{cid}: severity {raw.get(cid, {}).get('Severity')!r} is not one of {contract.SEVERITIES}.")
            before = {x["raw"] for x in old.get(cid, {}).get("citations", [])}
            for cit in c["citations"]:
                if cit["doc_id"] and (c["data_room"], cit["doc_id"]) not in doc_ids:
                    errors.append(f"{cid}: cites {cit['doc_id']}, which is not in the Documents tab for {c['data_room']}.")
                elif _quote_result(c["data_room"], cit, chunk_cache) == "Not found":
                    text = f"{cid}: the quote is not in {cit['doc_id']}: {cit['quote'][:80]!r}"
                    (warnings if cit["raw"] in before else errors).append(text)
            for d in c["documents"]:
                if (c["data_room"], d.upper()) not in doc_ids:
                    errors.append(f"{cid}: lists {d}, which is not in the Documents tab for {c['data_room']}.")

    if staged["documents"] is not None:
        errors += [f"Documents: {r} {d} is listed more than once." for r, d in _dupes([(d["data_room"], d["doc_id"]) for d in docs])]
        for room in sorted({d["data_room"] for d in docs}):
            for field, label in (("doc_date", "date"), ("authority", "authority")):
                missing = [d["doc_id"] for d in docs if d["data_room"] == room and not d.get(field)]
                if missing:
                    warnings.append(f"{room}: {len(missing)} documents have no {label} ({', '.join(missing[:8])}"
                                    f"{', ...' if len(missing) > 8 else ''}). Rules that need it will answer cannot decide.")
            bad = [f"{d['doc_id']} ({d['authority']})" for d in docs
                   if d["data_room"] == room and d.get("authority") and d["authority"] not in context.AUTHORITY]
            if bad:
                errors.append(f"{room}: authority is not one of the list for {', '.join(bad)}.")

    if staged["facts"] is not None:
        old = {(f["data_room"], f["fact_id"]): f for f in now["facts"]}
        ids = {(f["data_room"], f["fact_id"]) for f in facts}
        errors += [f"Fact Sheet: {r} {i} is used more than once." for r, i in _dupes([(f["data_room"], f["fact_id"]) for f in facts])]
        for f in facts:
            tag = f"{f['data_room']} {f['fact_id']}"
            if f["supersedes"] and (f["data_room"], f["supersedes"]) not in ids:
                errors.append(f"{tag}: supersedes {f['supersedes']}, which does not exist.")
            if f["value_status"] and f["value_status"] not in context.VALUE_STATUSES:
                errors.append(f"{tag}: value status {f['value_status']!r} is not one of {context.VALUE_STATUSES}.")
            for field in ("source", "change_source"):
                cit = f[field] or {}
                if cit and cit.get("doc_id") and (f["data_room"], cit["doc_id"]) not in doc_ids:
                    errors.append(f"{tag}: its {field.replace('_', ' ')} cites {cit['doc_id']}, which is not in the Documents tab.")
                elif cit and _quote_result(f["data_room"], cit, chunk_cache) == "Not found":
                    text = f"{tag}: the {field.replace('_', ' ')} quote is not in {cit['doc_id']}: {cit['quote'][:80]!r}"
                    (warnings if old.get((f["data_room"], f["fact_id"]), {}).get(field) == cit else errors).append(text)

    if staged["rules"] is not None:
        errors += [f"Context Rules: rule ID {i} is used more than once." for i in _dupes([r["rule_id"] for r in rules])]
        for r in rules:
            missing = [k for k in ("name", "text", "type") if not r.get(k)]
            if missing:
                errors.append(f"Rule {r['rule_id']}: {', '.join(missing)} is missing.")
            elif r["type"] not in context.RULE_TYPES:
                errors.append(f"Rule {r['rule_id']}: type {r['type']!r} is not one of {context.RULE_TYPES}.")
            if r.get("critical") and not r.get("on") and not r.get("notes"):
                errors.append(f"Rule {r['rule_id']} is critical and switched off with no reason. Give the reason in its Notes.")

    fact_by = {(f["data_room"], f["fact_id"]): f for f in facts}
    for c in cases:
        if not c["report"]:
            loose = [i for i in c.get("register_ids") or []
                     if (f := fact_by.get((c["data_room"], i))) and f.get("supersedes") and not f.get("change_source")]
            if loose:
                warnings.append(f"{c['case_id']}: this case is marked do not report because of a change, but no document "
                                f"records the change ({', '.join(loose)}).")
    for room in sorted({c["data_room"] for c in cases}):
        gaps = [g["rule_id"] for g in context.coverage(cases, rules) if g["data_room"] == room and g["gap"]]
        if gaps:
            warnings.append(f"{room}: no test case yet for critical rules {', '.join(gaps)}. Tag a case with the rule ID "
                            f"in Scenario tags.")
    return {"errors": errors, "warnings": warnings}


# ---- writing ---------------------------------------------------------------------------------------------------------

def apply(staged: dict, file_name: str = "", note: str = "") -> dict:
    """Writes a validated upload: cases to the working draft, the rest to their files, and one change-log
    entry per changed object. Raises ValueError when blocking errors remain."""
    problems = validate(staged)
    if problems["errors"]:
        raise ValueError("The upload has blocking errors: " + "; ".join(problems["errors"][:5]))
    now, pv = current(), preview(staged)
    changes, entries = pv["changes"], []

    def record(tab: str, obj: str, old: dict, new: dict, summary):
        d = changes.get(tab) or {"new": [], "changed": [], "removed": []}
        for i in d["new"]:
            entries.append({"action": "upload", "object": obj, "id": i, "after": summary(new[i]), "reason": note or "Added in the sheet.", "origin": file_name})
        for c in d["changed"]:
            entries.append({"action": "upload", "object": obj, "id": c["id"], "before": {f: v[0] for f, v in c["fields"].items()},
                            "after": {f: v[1] for f, v in c["fields"].items()}, "reason": note or "Changed in the sheet.", "origin": file_name})
        for i in d["removed"]:
            entries.append({"action": "upload", "object": obj, "id": i, "before": summary(old[i]), "reason": note or "Removed from the sheet.", "origin": file_name})

    if staged["cases"] is not None:
        draft = ensure_draft()
        old = {c["case_id"]: c for c in draft["cases"]}
        pend = {p["case_id"]: p["case"] for p in load_pending() if p["kind"] == "case"}
        new_cases = []
        for c in staged["cases"]:
            origin = old.get(c["case_id"]) or pend.get(c["case_id"]) or {}
            new_cases.append({**c, **{k: origin[k] for k in ("origin", "origin_check") if origin.get(k)}})
        uploaded = {c["case_id"] for c in new_cases}
        new_cases += [p["case"] for p in pv["pending_kept"] if p["kind"] == "case" and p["case_id"] not in uploaded]
        d = changes["Ground Truth"]
        d["removed"] = [i for i in d["removed"] if i not in {c["case_id"] for c in new_cases}]
        store._write(_file("library_draft.json"), {**draft, "cases": new_cases})
        store._write(_file("pending.json"), pv["pending_kept"])
        record("Ground Truth", "case", old, {c["case_id"]: c for c in new_cases}, lambda c: c.get("summary"))
    if staged["documents"] is not None:
        key = lambda d: f"{d['data_room']} {d['doc_id']}"
        store._write(_file("documents.json"), staged["documents"])
        record("Documents", "document", {key(d): d for d in now["documents"]}, {key(d): d for d in staged["documents"]},
               lambda d: d.get("title"))
    if staged["facts"] is not None:
        key = lambda f: f"{f['data_room']} {f['fact_id']}"
        store._write(_file("facts.json"), staged["facts"])
        record("Fact Sheet", "fact", {key(f): f for f in now["facts"]}, {key(f): f for f in staged["facts"]},
               lambda f: f"{f.get('subject')}: {f.get('value')}")
    if staged["rules"] is not None:
        store._write(_file("context_rules.json"), staged["rules"])
        record("Context Rules", "rule", {r["rule_id"]: r for r in now["rules"]}, {r["rule_id"]: r for r in staged["rules"]},
               lambda r: r.get("name"))
    if staged["runs"] is not None:
        d = changes["Baseline Runs"]
        for rid in d["new"] + [c["id"] for c in d["changed"]]:
            payload = staged["runs"][rid]
            folder = "baseline" if payload["run"]["source"] == "Baseline model" else "system"
            store.save_submission(payload, folder=folder, allow_problems=True)
        record("Baseline Runs", "baseline", now["runs"], staged["runs"], lambda p: f"{len(p['findings'])} findings")
        reviews = store.load_reviews()
        d = changes["Baseline decisions"]
        for k in d["new"] + [c["id"] for c in d["changed"]]:
            reviews[k] = staged["reviews"][k]
        if d["new"] or d["changed"]:
            store._write(store.REVIEWS, reviews)
            entries.append({"action": "upload", "object": "baseline", "id": "manual decisions",
                            "after": f"{len(d['new'])} new, {len(d['changed'])} changed",
                            "reason": note or "Decisions made by hand in the sheet.", "origin": file_name})
    log_many(entries)
    return {"written": {t["tab"]: t for t in pv["tabs"]}, "logged": len(entries), "warnings": problems["warnings"],
            "pending_cleared": len(pv["pending_cleared"]), "pending_kept": len(pv["pending_kept"])}
