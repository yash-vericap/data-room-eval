"""Finds the findings in a run of any JSON shape and reads each one leniently."""
from __future__ import annotations

import json

from .. import contract
from .fields import (_DOC, _GROUPS, ALIASES, _citations, _classification, _doc_id, _get, _numbered_files,
                     _severity, _text)


def _lists(node, path: str = "$"):
    """Every list of objects in the JSON, with its path."""
    if isinstance(node, list):
        rows = [x for x in node if isinstance(x, dict)]
        if rows:
            yield path, rows
        for i, x in enumerate(node):
            if isinstance(x, (dict, list)):
                yield from _lists(x, f"{path}[{i}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                yield from _lists(v, f"{path}.{k}")


def _groups(rows: list[dict]) -> int:
    return sum(any(_get(r, ALIASES[g]) is not None for r in rows) for g in _GROUPS)


def read_findings(payload) -> dict:
    """Finds the findings in any JSON shape and reads each one leniently.

    Returns {"findings", "source_path", "notes", "run_meta"}. Raises ValueError when the JSON holds no
    list that looks like findings."""
    if isinstance(payload, list) and payload and all(isinstance(x, dict) for x in payload):
        path, rows = "$", payload
    else:
        best = max(((_groups(rows) + min(len(rows), 999) / 1000, path, rows) for path, rows in _lists(payload)
                    if _groups(rows) > 0), key=lambda t: t[0], default=None)
        if best is None:
            raise ValueError("No list of findings was found in the JSON.")
        _, path, rows = best
    meta = {}
    _numbered_files.clear()
    if isinstance(payload, dict):
        meta = next((payload[k] for k in ("run", "run_details", "metadata", "investigation") if isinstance(payload.get(k), dict)), {})
        meta = {k: v for k, v in meta.items() if not isinstance(v, (list, dict))}
        if not meta.get("run_id") and meta.get("id"):
            meta["run_id"] = str(meta["id"])
        if isinstance(payload.get("summary"), dict):          # the run's own summary, kept to compare with what was read
            meta["summary"] = payload["summary"]
        if payload.get("schema_version"):
            meta["schema_version"] = str(payload["schema_version"])
        room = meta.get("data_room") or meta.get("data_room_id") or payload.get("data_room") or payload.get("data_room_id")
        if room:
            meta["data_room"] = str(room).strip().upper()

    findings, notes = [], []
    for i, item in enumerate(rows, start=1):
        claims, explanation = _text(_get(item, ALIASES["claims_compared"])), _text(_get(item, ALIASES["explanation"]))
        raw = json.dumps(item, ensure_ascii=False, default=str)
        summary = _text(_get(item, ALIASES["summary"])) or (claims or explanation or raw)[:240]
        low = {str(k).lower(): v for k, v in item.items()}
        if not claims:            # a title with a longer description: the description says what was compared
            claims = next((_text(low[k]) for k in ("description", "detail", "details", "discrepancy", "issue")
                           if low.get(k) not in (None, "") and _text(low[k]) != summary), "")
        questions = low.get("open_questions")
        if questions and not explanation:
            explanation = "Open questions: " + "; ".join(_text(q) for q in (questions if isinstance(questions, list) else [questions]))
        cits = _citations(_get(item, ALIASES["citations"]))
        cited = {c["doc_id"] for c in cits if c["doc_id"]}
        for name in low.get("documents") if isinstance(low.get("documents"), list) else []:      # documents listed next to the evidence
            doc = _doc_id(name, by_number=True) if isinstance(name, str) else None
            if doc and doc not in cited:
                cited.add(doc)
                cits.append({"doc_id": doc, "page": None, "location": "", "quote": "", "raw": doc})
        for doc in dict.fromkeys(f"DOC-{int(n):02d}" for n in _DOC.findall(raw)):     # documents named anywhere in the item
            if doc not in cited:
                cited.add(doc)
                cits.append({"doc_id": doc, "page": None, "location": "", "quote": "", "raw": doc})
        raw_cls, raw_sev = _get(item, ALIASES["classification"]), _get(item, ALIASES["severity"])
        conf = _get(item, ALIASES["confidence"])
        findings.append({
            "finding_id": _text(_get(item, ALIASES["finding_id"])) or f"F{i:02d}",
            "classification": _classification(raw_cls), "severity": _severity(raw_sev), "summary": summary,
            "claims_compared": claims, "citations": cits, "explanation": explanation,
            "confidence": contract._num(conf) if not isinstance(conf, (dict, list)) else None,
            "raw_classification": _text(raw_cls), "raw_severity": _text(raw_sev), "raw": raw[:3000],
        })
    ids = [f["finding_id"] for f in findings]
    if len(set(ids)) != len(ids):
        for i, f in enumerate(findings, start=1):
            f["finding_id"] = f"F{i:02d}"
        notes.append("Finding IDs repeat in the file, so the findings were renumbered F01, F02, ...")

    def note(n: int, one: str, many: str):
        if n:
            notes.append(f"1 finding {one}" if n == 1 else f"{n} findings {many}")

    if _numbered_files:
        shown = sorted(_numbered_files)[:3]
        notes.append("Document IDs were taken from the number at the start of the file name ("
                     + ", ".join(f"{n} read as {_doc_id(n, by_number=True)}" for n in shown) + "). Check that these are the right documents.")
    totals = (meta.get("summary") or {}).get("totals") if isinstance(meta.get("summary"), dict) else None
    if isinstance(totals, dict) and isinstance(totals.get("findings"), int) and totals["findings"] != len(findings):
        notes.append(f"The run's summary says {totals['findings']} findings, but {len(findings)} are in the file.")
    note(sum(not any(c["doc_id"] for c in f["citations"]) for f in findings), "names no document.", "name no document.")
    note(sum(not any(c["quote"] for c in f["citations"]) for f in findings), "quotes no passage.", "quote no passage.")
    note(sum(f["classification"] is None for f in findings), "has no class that could be read.", "have no class that could be read.")
    note(sum(f["severity"] is None for f in findings), "has no severity that could be read.", "have no severity that could be read.")
    return {"findings": findings, "source_path": path, "notes": notes, "run_meta": meta}
