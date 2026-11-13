"""Checks one run against the output contract and puts it in the standard shape."""
from __future__ import annotations

from .contract import CLASSES, SEVERITIES, SOURCES, _label, _num, parse_citations


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
