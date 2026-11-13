"""The output contract: the labels a run may use, and how citations are read.

A run in the contract format is one JSON object: {"run": {run_id, data_room, source, system, version, model, ...},
"findings": [{finding_id, classification, severity, summary, claims_compared, citations, explanation,
confidence}]}. A citation is {doc_id, page, location, quote}, or one string such as
"DOC-05 p.2, 2.3: '$5,120,000' || DOC-06 p.3, 4: '$4,920,000'". contract_run.normalise() checks a run."""
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

from .contract_run import normalise  # noqa: E402,F401  (kept here so callers need one import)
