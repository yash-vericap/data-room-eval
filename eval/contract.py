"""The output contract: what one submitted run must look like, and the check that enforces it.

One run is one JSON file:

{
  "run": {
    "run_id": "v0.01-HTC01-R1",          required, unique
    "data_room": "HTC01",                required
    "source": "Our system",              "Our system" or "Baseline model"
    "system": "Discrepancy checker",     name used to group repeated runs
    "version": "v0.01",                  system version or baseline prompt version
    "model": "...", "run_number": 1, "started_at": "...", "ended_at": "...",
    "duration_minutes": 4.2, "input_tokens": 0, "output_tokens": 0,
    "cost_usd": 0.0, "steps": 0, "temperature": 0, "access_route": "API", "notes": ""
  },
  "findings": [
    {
      "finding_id": "F01",               required, unique in the run
      "classification": "Contradiction", one of CLASSES, word for word
      "severity": "Critical",            one of SEVERITIES, word for word
      "summary": "...",                  required
      "claims_compared": "...",
      "citations": [                     at least one, each with a quote
        {"doc_id": "DOC-05", "page": 2, "location": "2.3", "quote": "$5,120,000"}
      ],
      "explanation": "...",
      "confidence": 0.97
    }
  ]
}

Citations may also arrive as one string, "DOC-05 p.2, 2.3: 'quote' || DOC-06 p.3, 4: 'quote'",
which is how the baseline replies were stored. Both forms are accepted.
"""
from __future__ import annotations

import re

CLASSES = ["Contradiction", "Contextual difference", "Insufficient evidence", "Consistent"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
WEIGHTS = {"Critical": 8, "High": 4, "Medium": 2, "Low": 1}
REPORTABLE_CLASSES = {"Contradiction", "Insufficient evidence"}
SOURCES = ["Our system", "Baseline model"]

_CIT_HEAD = re.compile(
    r"^\s*(DOC-\d+)\s*,?\s*(?:(pp?\.?|pages?|slides?)\s*(\d+)(?:\s*(?:-|to)\s*\d+)?)?\s*,?\s*(.*)$",
    re.I | re.S,
)
_SLIDE_IN_LOC = re.compile(r"\bslide\s*(\d+)", re.I)


def parse_citation(text: str) -> dict | None:
    """'DOC-05 p.2, 2.3: "$5,120,000"' -> {doc_id, page, location, quote, raw}."""
    text = (text or "").strip()
    if not text:
        return None
    head, sep, quote = text.partition(": ")
    if not sep:
        head, quote = text, ""
    m = _CIT_HEAD.match(head)
    if not m:
        return {"doc_id": None, "page": None, "location": "", "quote": text, "raw": text}
    doc, kind, page, loc = m.group(1).upper(), (m.group(2) or "").lower(), m.group(3), m.group(4).strip(" ,")
    page = int(page) if page else None
    slide = _SLIDE_IN_LOC.search(loc)
    if slide and not kind.startswith("slide"):
        page = int(slide.group(1))
    quote = quote.strip().strip("'\"‘’“”").strip()
    return {"doc_id": doc, "page": page, "location": loc, "quote": quote, "raw": text}


def parse_citations(value) -> list[dict]:
    """Accepts a list of dicts, a list of strings, or one '||' / newline separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p for p in re.split(r"\s*\|\|\s*|\n+", value) if p.strip()]
        return [c for c in (parse_citation(p) for p in parts) if c]
    out = []
    for item in value:
        if isinstance(item, str):
            c = parse_citation(item)
            if c:
                out.append(c)
        elif isinstance(item, dict):
            doc = item.get("doc_id") or item.get("document_id") or item.get("document") or item.get("doc")
            page = item.get("page", item.get("slide"))
            try:
                page = int(page) if page not in (None, "") else None
            except (TypeError, ValueError):
                page = None
            loc = str(item.get("location") or item.get("paragraph") or item.get("line") or item.get("section") or "")
            quote = str(item.get("quote") or item.get("quoted_text") or item.get("text") or "")
            out.append({
                "doc_id": str(doc).upper() if doc else None, "page": page, "location": loc, "quote": quote,
                "raw": f"{doc} p.{page}, {loc}: {quote}",
            })
    return out


def _label(value, allowed):
    if not isinstance(value, str):
        return None
    for a in allowed:
        if a.lower() == value.strip().lower():
            return a
    return None


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def normalise(payload: dict) -> tuple[dict, list[str]]:
    """Returns (run in the standard shape, list of contract problems).

    Problems are things the contract does not allow: missing fields, labels that are not ours word
    for word, citations without a quote. Nothing about the content is changed here.
    """
    problems: list[str] = []
    if not isinstance(payload, dict):
        return {"run": {}, "findings": []}, ["The file is not a JSON object."]
    run_in = payload.get("run") or payload.get("run_details") or {}
    if not isinstance(run_in, dict):
        run_in, _ = {}, problems.append("'run' must be an object.")
    run = {
        "run_id": str(run_in.get("run_id") or "").strip(),
        "data_room": str(run_in.get("data_room") or run_in.get("data_room_id") or "").strip().upper(),
        "source": _label(run_in.get("source"), SOURCES) or "Our system",
        "system": str(run_in.get("system") or run_in.get("model") or "").strip(),
        "version": str(run_in.get("version") or run_in.get("system_version") or run_in.get("prompt_version") or "").strip(),
        "model": str(run_in.get("model") or "").strip(),
        "run_number": run_in.get("run_number"),
        "started_at": run_in.get("started_at") or run_in.get("run_date"),
        "ended_at": run_in.get("ended_at"),
        "duration_minutes": _num(run_in.get("duration_minutes")),
        "input_tokens": _num(run_in.get("input_tokens")),
        "output_tokens": _num(run_in.get("output_tokens")),
        "cost_usd": _num(run_in.get("cost_usd")),
        "steps": _num(run_in.get("steps")),
        "temperature": _num(run_in.get("temperature")),
        "access_route": run_in.get("access_route"),
        "snapshot": run_in.get("snapshot"),
        "format_repairs": run_in.get("format_repairs"),
        "notes": run_in.get("notes") or "",
    }
    if not run["run_id"]:
        problems.append("run.run_id is missing.")
    if not run["data_room"]:
        problems.append("run.data_room is missing.")
    if not run["system"]:
        run["system"] = run["run_id"]

    findings_in = payload.get("findings")
    if not isinstance(findings_in, list):
        problems.append("'findings' must be a list.")
        findings_in = []
    findings, seen = [], set()
    for i, f in enumerate(findings_in):
        if not isinstance(f, dict):
            problems.append(f"findings[{i}] is not an object.")
            continue
        fid = str(f.get("finding_id") or f.get("id") or "").strip()
        tag = fid or f"findings[{i}]"
        if not fid:
            problems.append(f"findings[{i}]: finding_id is missing.")
            fid = f"_missing_{i + 1}"
        if fid in seen:
            problems.append(f"{tag}: finding_id is used more than once.")
            continue
        seen.add(fid)
        cls = _label(f.get("classification"), CLASSES)
        sev = _label(f.get("severity"), SEVERITIES)
        if cls is None:
            problems.append(f"{tag}: classification {f.get('classification')!r} is not one of {CLASSES}.")
        if sev is None:
            problems.append(f"{tag}: severity {f.get('severity')!r} is not one of {SEVERITIES}.")
        cits = parse_citations(f.get("citations"))
        if not cits:
            problems.append(f"{tag}: no citations.")
        for c in cits:
            if not c["doc_id"]:
                problems.append(f"{tag}: citation without a document ID: {c['raw'][:60]!r}.")
            elif not c["quote"]:
                problems.append(f"{tag}: citation {c['doc_id']} has no quoted text.")
        summary = str(f.get("summary") or "").strip()
        if not summary:
            problems.append(f"{tag}: summary is missing.")
        findings.append({
            "finding_id": fid, "classification": cls, "severity": sev, "summary": summary,
            "claims_compared": str(f.get("claims_compared") or f.get("claims") or "").strip(),
            "citations": cits,
            "explanation": str(f.get("explanation") or f.get("reasoning") or "").strip(),
            "confidence": _num(f.get("confidence")),
        })
    return {"run": run, "findings": findings}, problems
