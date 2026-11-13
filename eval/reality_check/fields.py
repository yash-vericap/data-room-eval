"""Reading one finding's fields under any of their common names: class, severity, documents and citations."""
from __future__ import annotations

import json
import re

from .. import contract


ALIASES = {
    "summary": ["summary", "title", "issue", "discrepancy", "description", "finding", "headline", "name", "message"],
    "claims_compared": ["claims_compared", "claims", "comparison", "details", "detail", "conflict", "values", "observed"],
    "explanation": ["explanation", "reasoning", "rationale", "analysis", "why", "impact", "recommendation", "notes"],
    "citations": ["citations", "citation", "evidence", "sources", "source", "references", "reference", "documents",
                  "document_refs", "locations", "quotes"],
    "classification": ["classification", "class", "type", "category", "discrepancy_type", "finding_type", "kind"],
    "severity": ["severity", "priority", "risk", "risk_level", "level", "impact_level"],
    "finding_id": ["finding_id", "id", "discrepancy_id", "key", "ref"],
    "confidence": ["confidence", "score", "probability"],
}
_GROUPS = ["summary", "citations", "severity", "classification", "explanation"]
_CLASS_WORDS = [("Insufficient evidence", ["insufficient", "missing", "unverif", "not provided", "absent", "gap"]),
                ("Contextual difference", ["context", "explain", "different basis", "phase", "timing"]),
                ("Contradiction", ["inconsisten", "mismatch"]),       # before "consistent" and "match", which they contain
                ("Consistent", ["consistent", "no issue", "match", "agree"]),
                ("Contradiction", ["contradict", "conflict", "mismatch", "inconsisten", "discrepan", "differ", "error"])]
_SEVERITY_WORDS = [("Critical", ["critical", "blocker", "p0", "severe"]), ("High", ["high", "major", "p1"]),
                   ("Medium", ["medium", "moderate", "med", "p2"]), ("Low", ["low", "minor", "info", "p3"])]
_DOC = re.compile(r"\bDOC[-_ ]?0*(\d+)(?!\d)", re.I)       # also inside a file name: DOC-02_Part2.pdf
_CIT_KEYS = {"doc_id": ["doc_id", "document_id", "document", "doc", "document_name", "doc_name", "file", "file_name",
                        "filename", "source", "title", "name"],
             "page": ["page", "slide", "page_number", "page_no", "pg", "page_num"],
             "location": ["location", "paragraph", "line", "section", "clause"],
             "quote": ["quote", "quoted_text", "text", "excerpt", "snippet", "passage", "content", "value"]}


def _get(item: dict, keys: list[str]):
    low = {str(k).lower(): v for k, v in item.items()}
    for k in keys:
        if low.get(k) not in (None, "", [], {}):
            return low[k]
    return None


def _text(v) -> str:
    if v is None:
        return ""
    return v.strip() if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)


_LEADING_NUMBER = re.compile(r"^\s*0*(\d{1,3})[_\-. ]")
_numbered_files: set[str] = set()          # file names whose document ID was taken from their leading number


def _doc_id(text, by_number: bool = False) -> str | None:
    """'DOC-07', 'doc_7' or 'DOC-07_Scope.pdf' -> DOC-07. With by_number, a file name that starts with a
    number and carries no DOC id ('01_Permit.pdf') -> DOC-01."""
    text = str(text or "")
    m = _DOC.search(text)
    if m:
        return f"DOC-{int(m.group(1)):02d}"
    m = _LEADING_NUMBER.match(text.replace("\\", "/").rsplit("/", 1)[-1]) if by_number else None
    if m:
        _numbered_files.add(text.strip())
        return f"DOC-{int(m.group(1)):02d}"
    return None


def _flat(item: dict) -> dict:
    """A citation with a nested location ({page, section, sheet, cell_range}) as one flat dict."""
    loc = next((v for k, v in item.items() if str(k).lower() == "location" and isinstance(v, dict)), None)
    if loc is None:
        return item
    low = {str(k).lower(): v for k, v in loc.items()}
    where = " ".join(str(x) for x in [low.get("section"), f"sheet {low['sheet']}" if low.get("sheet") else None,
                                      low.get("cell_range")] if x not in (None, ""))
    rest = {k: v for k, v in item.items() if str(k).lower() != "location"}
    return {**rest, "page": low.get("page", low.get("slide")), "location": where}


def _fix_docs(text: str) -> str:
    return _DOC.sub(lambda m: f"DOC-{int(m.group(1)):02d}", text)


def _classification(value) -> str | None:
    exact = contract._label(value, contract.CLASSES)
    if exact or value in (None, ""):
        return exact
    low = str(value).lower()
    return next((cls for cls, words in _CLASS_WORDS if any(w in low for w in words)), None)


def _severity(value) -> str | None:
    exact = contract._label(value, contract.SEVERITIES)
    if exact or value in (None, ""):
        return exact
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        return {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}.get(int(float(value)))
    low = str(value).lower()
    return next((sev for sev, words in _SEVERITY_WORDS if any(w in low for w in words)), None)


def _citations(value) -> list[dict]:
    """Citations from a string, a dict, a list of strings, a list of dicts or a bare list of document IDs."""
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, str):
        cits = contract.parse_citations(_fix_docs(value))
    else:
        items = []
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                item = _flat(item)
                items.append({"doc_id": _doc_id(_get(item, _CIT_KEYS["doc_id"]), by_number=True) or _doc_id(json.dumps(item, default=str)),
                              "page": _get(item, _CIT_KEYS["page"]), "location": _text(_get(item, _CIT_KEYS["location"])),
                              "quote": _text(_get(item, _CIT_KEYS["quote"]))})
            elif item not in (None, ""):
                named = _doc_id(item, by_number=True) if not _DOC.search(str(item)) else None
                items.append(named if named else _fix_docs(str(item)))
        cits = contract.parse_citations(items)
    for c in cits:
        c["doc_id"] = _doc_id(c["doc_id"]) if c.get("doc_id") else None
        if c["doc_id"] and not c["quote"]:
            c["raw"] = c["doc_id"] + (f" p.{c['page']}" if c["page"] is not None else "")
        elif c["doc_id"]:
            c["raw"] = (f"{c['doc_id']}" + (f" p.{c['page']}" if c["page"] is not None else "")
                        + (f", {c['location']}" if c["location"] else "") + f": '{c['quote']}'")
    return cits
