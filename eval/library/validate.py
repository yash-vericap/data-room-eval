"""The checks an upload must pass: blocking errors and warnings."""
from __future__ import annotations

from .. import context, contract, scoring, store
from ..import_sheet import _s
from .diffing import current


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
