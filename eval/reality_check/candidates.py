"""Candidate review: the closest cases, the admission checklist, and accepting or rejecting a candidate."""
from __future__ import annotations

from .. import context, contract, library, matching
from .labels import FOUND, REJECTED_EVALUATOR, REVIEW
from .state import _room_cases
from .storage import set_manual
from .verdicts import case_hash


def _as_case(finding: dict) -> dict:
    return {"case_id": finding["finding_id"], "summary": finding["summary"], "claims_compared": finding["claims_compared"],
            "explanation": finding["explanation"], "citations": finding["citations"],
            "documents": sorted({c["doc_id"] for c in finding["citations"] if c["doc_id"]})}


def closest_cases(check: dict, fid: str, cases: list[dict], n: int = 3) -> list[dict]:
    """The existing cases closest to a finding, with the matcher's score."""
    room_cases = _room_cases(check, cases)
    f = next(x for x in check["findings"] if x["finding_id"] == fid)
    index = matching.RoomIndex(room_cases)
    scored = sorted(((index.score(f, c)["score"], c["case_id"]) for c in room_cases), reverse=True)
    return [{"case_id": cid, "score": s} for s, cid in scored[:n] if s > 0]


def seen_by_baselines(check: dict, fid: str, runs: list[dict]) -> list[str]:
    """Baseline runs on the same data room that reported a similar finding."""
    f = next(x for x in check["findings"] if x["finding_id"] == fid)
    pseudo = _as_case(f)
    index = matching.RoomIndex([pseudo])
    return [r["run"]["run_id"] for r in runs
            if r["run"].get("data_room") == check["data_room"] and r["run"].get("source") == "Baseline model"
            and any(index.score(bf, pseudo)["score"] >= matching.REVIEW_AT for bf in r["findings"])]


def checklist(check: dict, fid: str, cases: list[dict], runs: list[dict] | None = None) -> list[dict]:
    """The admission checklist for one candidate: [{"check", "result", "reason"}]. Results are Pass, Fail,
    Unknown, or Info for the line that is information only."""
    v = check["new_verdicts"].get(fid) or {}
    rules = context.rules_on()
    kind = {r["rule_id"]: r["type"] for r in rules}
    line = lambda name, result, reason: {"check": name, "result": result, "reason": reason}
    out = []

    quotes = [q for q in v.get("own_quotes") or [] if q != "Not checked"]
    missing = sum(q == "Not found" for q in quotes)
    real = v.get("raw_status") == "real_issue"
    if not quotes:
        out.append(line("Real in the documents", "Unknown", "The finding quotes no passage that could be checked."))
    elif missing or not real:
        out.append(line("Real in the documents", "Fail", (f"{missing} of {len(quotes)} quotes are not in the documents. " if missing else "")
                        + ("" if real else f"The judge said: {v.get('status') or 'not judged'}.")))
    else:
        out.append(line("Real in the documents", "Pass", f"All {len(quotes)} quotes are in the documents and the judge found a real issue."))

    near = closest_cases(check, fid, cases)
    top = near[0] if near else None
    if top and top["score"] >= matching.REVIEW_AT:
        out.append(line("Not already in the ground truth", "Fail", f"{top['case_id']} is close (score {top['score']:.2f}). Compare before accepting."))
    else:
        out.append(line("Not already in the ground truth", "Pass", "No existing case is close"
                        + (f" (closest: {top['case_id']}, score {top['score']:.2f})." if top else ".")))

    pre = v.get("precheck") or {}
    named = [r for r in ([pre.get("rule_id")] if pre else []) + (v.get("rule_ids") or []) if r in kind]
    rejects = [r for r in dict.fromkeys(named) if kind[r] == "Reject"]
    flags = [r for r in dict.fromkeys(named) if kind[r] == "Flag"]
    support = f" {', '.join(context.rule_name(r, rules) for r in flags)} applies, which supports accepting." if flags else ""
    if rejects:
        out.append(line("Not excused by a rule", "Fail", f"{', '.join(context.rule_name(r, rules) for r in rejects)} applies.{support}"))
    else:
        out.append(line("Not excused by a rule", "Pass", "No rule excuses it." + support))

    sev, bar = contract._label(v.get("severity"), contract.SEVERITIES), context.min_candidate_severity()
    if not sev:
        out.append(line("A major red flag", "Unknown", "The judge gave no severity."))
    elif context.SEVERITY_ORDER[sev] >= context.SEVERITY_ORDER[bar] and (v.get("why_it_matters") or "").strip():
        out.append(line("A major red flag", "Pass", f"Judged {sev}. {v['why_it_matters']}"))
    else:
        out.append(line("A major red flag", "Fail", f"Judged {sev}" + (f", below the bar of {bar}." if context.SEVERITY_ORDER[sev] < context.SEVERITY_ORDER[bar]
                                                                 else ", but no consequence for the customer or investor is named.")))

    fj = v.get("fact_or_judgment")
    out.append(line("A fact, not an opinion", "Pass" if fj == "fact" else "Unknown",
                    "It can be checked against the documents." if fj == "fact" else
                    "The judge calls it a judgment. If accepted, the case is marked ambiguous." if fj == "judgment" else "Not judged."))
    if runs is not None:
        seen = seen_by_baselines(check, fid, runs)
        total = sum(r["run"].get("data_room") == check["data_room"] and r["run"].get("source") == "Baseline model" for r in runs)
        out.append(line("Seen by others", "Info", f"{len(seen)} of {total} baseline runs reported something similar"
                        + (f": {', '.join(seen)}." if seen else ".")))
    return out


def prefill_case(check: dict, fid: str, report: bool = True) -> dict:
    """A case with every Ground Truth column filled in from a finding and its verdict, for the evaluator
    to confirm or change before it is accepted."""
    f = next(x for x in check["findings"] if x["finding_id"] == fid)
    v = check["new_verdicts"].get(fid) or {}
    room = check["data_room"]
    sev = contract._label(v.get("severity"), contract.SEVERITIES) or f["severity"] or "Medium"
    pre = v.get("precheck") or {}
    rule_ids = list(dict.fromkeys(([pre["rule_id"]] if pre.get("rule_id") else []) + (v.get("rule_ids") or [])))
    cls = (f["classification"] if f["classification"] in contract.REPORTABLE_CLASSES else "Contradiction") if report \
        else "Contextual difference"
    docs = sorted({c["doc_id"] for c in f["citations"] if c["doc_id"]})
    judgment = v.get("fact_or_judgment") == "judgment"
    return {
        "case_id": library.next_case_id(room), "data_room": room, "classification": cls, "severity": sev,
        "weight": contract.WEIGHTS[sev], "report": report, "set": "Withheld", "summary": f["summary"],
        "claims_compared": f["claims_compared"], "citations": [dict(c) for c in f["citations"] if c["doc_id"]],
        "explanation": v.get("explanation") or f["explanation"], "check_type": "Document versus document" if len(docs) > 1 else "",
        "documents": docs, "register_ids": [x["fact_id"] for x in context.facts_for_finding(f, room)][:6],
        "fact_or_judgment": "Judgment" if judgment else "Fact", "ambiguous": judgment,
        "alternative_readings": v.get("why_it_might_not") or "" if judgment else "", "open_questions": "",
        "scenario_tags": rule_ids, "snapshot": "Working draft", "review_status": "Draft",
        "origin": f"Found by run {check['label']}, check {check['check_id']}, accepted by the evaluator",
    }


def accept_candidate(check: dict, fid: str, case: dict, reason: str) -> dict:
    """Adds an accepted candidate to the pending rows and the working draft, links the finding to the new
    case as Found by hand, and logs the decision. Returns the stored case."""
    stored = library.add_pending_case(case, check["check_id"], reason)
    set_manual(check, "case", stored["case_id"], FOUND, [fid], f"Accepted from this run: {reason}",
               case_hash(stored, context.block_for_case(stored)))
    return stored


def reject_candidate(check: dict, fid: str, reason: str, rule_id: str | None = None) -> None:
    """Rejects a candidate with a reason. Rule C13 then rejects the same finding in later checks."""
    f = next(x for x in check["findings"] if x["finding_id"] == fid)
    library.add_rejected(f, check["data_room"], reason, rule_id, check["check_id"], check.get("snapshot") or "")
    set_manual(check, "finding", fid, REJECTED_EVALUATOR, note=reason)


def restore(check: dict, fid: str, reason: str) -> None:
    """Moves a finding the rules rejected to Needs review, when the evaluator disagrees with the rule."""
    g = (check["new_verdicts"].get(fid) or {}).get("gate") or {}
    library.log("restore", "candidate", f"{check['check_id']}:{fid}", before=f"Rejected by rule {g.get('rule_id') or ''}".strip(),
                after=REVIEW, reason=reason, origin=check["check_id"])
    set_manual(check, "finding", fid, REVIEW, note=f"Restored: {reason}")
