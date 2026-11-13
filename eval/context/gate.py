"""The rule gate: what happens to a finding that maps to no case, after the model has looked at it."""
from __future__ import annotations

from .. import contract, matching
from .rules import FLAG_TAGS, SEVERITY_ORDER, min_candidate_severity, rule_name, rules_on


def _candidate_case(entry: dict) -> dict:
    """A rejected candidate in the shape the matcher expects for a case."""
    f = entry["finding"]
    return {"case_id": entry.get("key") or f.get("finding_id") or "rejected", "summary": f.get("summary") or "",
            "claims_compared": f.get("claims_compared") or "", "explanation": f.get("explanation") or "",
            "citations": f.get("citations") or [],
            "documents": sorted({c["doc_id"] for c in f.get("citations") or [] if c.get("doc_id")})}


def decided_before(finding: dict, room: str, rejected: list[dict]) -> dict | None:
    """The stored rejected candidate this finding repeats (rule C13), or None."""
    pool = [e for e in rejected or [] if e.get("data_room") == room]
    if not pool:
        return None
    pseudo = [_candidate_case({**e, "key": f"rej{i}"}) for i, e in enumerate(pool)]
    index = matching.RoomIndex(pseudo)
    best = max(((index.score(finding, c)["score"], i) for i, c in enumerate(pseudo)), default=(0.0, 0))
    return pool[best[1]] if best[0] >= matching.MATCH_AT else None


def gate(finding: dict, precheck: dict | None, verdict: dict, room: str, rules: list[dict] | None = None,
         rejected: list[dict] | None = None) -> dict:
    """Decides what happens to a finding that maps to no case, after the judge has looked at it.

    Returns {"outcome", "rule_id", "reason"}; outcome is 'Rejected by rule', 'Needs review' or 'Candidate'.
    `verdict` needs "raw_status" (real_issue, known_change, not_a_discrepancy, not_in_documents,
    cannot_decide), "rule_ids", "severity", "explanation" and "own_quotes_found". The gate never touches
    a case verdict."""
    rules = rules_on(rules)
    kind = {r["rule_id"]: r["type"] for r in rules}
    status = verdict.get("raw_status") or "cannot_decide"
    named = [r for r in verdict.get("rule_ids") or [] if r in kind]
    pre_rule = precheck["rule_id"] if precheck and precheck.get("rule_id") in kind else None
    why = verdict.get("explanation") or ""
    out = lambda outcome, rule, reason: {"outcome": outcome, "rule_id": rule, "reason": reason}

    flag = next((r for r in ([pre_rule] if precheck and precheck.get("tag") in FLAG_TAGS else []) + named
                 if r and kind.get(r) == "Flag"), None)
    if flag:                                                       # 1. a Flag rule applies: never rejected
        if status == "real_issue":
            return out("Candidate", flag, f"{rule_name(flag, rules)} applies and the judge found a real issue. {why}".strip())
        return out("Needs review", flag, f"{rule_name(flag, rules)} applies, but the judge said "
                   f"{status.replace('_', ' ')}. " + ((precheck or {}).get("reason") or why))
    if "C13" in kind:                                              # 2. decided before
        earlier = decided_before(finding, room, rejected or [])
        if earlier:
            return out("Rejected by rule", "C13", f"Rejected before ({earlier.get('check_id') or 'earlier check'}): "
                       f"{earlier.get('reason') or 'no reason recorded'}")
    if "C14" in kind and status == "not_in_documents" and not verdict.get("own_quotes_found"):    # 3. evidence not found
        return out("Rejected by rule", "C14", f"No quote of the finding is in the documents. {why}".strip())
    judge_reject = next((r for r in named if kind.get(r) == "Reject"), None)
    pre_reject = pre_rule if pre_rule and kind.get(pre_rule) == "Reject" else None
    if pre_reject and status in ("known_change", "not_a_discrepancy", "not_in_documents"):         # 4. both agree
        return out("Rejected by rule", pre_reject, precheck["reason"])
    if judge_reject and not precheck and status != "real_issue":
        return out("Rejected by rule", judge_reject, why)
    if pre_reject and status == "real_issue":                      # 5. they disagree
        return out("Needs review", pre_reject, f"The rule pre-check says {precheck['tag'].lower()} "
                   f"({rule_name(pre_reject, rules)}), but the judge found a real issue. {why}".strip())
    if judge_reject and status == "real_issue":
        return out("Needs review", judge_reject, f"The judge found a real issue but also named {rule_name(judge_reject, rules)}. {why}".strip())
    if status == "real_issue":
        sev = contract._label(verdict.get("severity"), contract.SEVERITIES) or finding.get("severity")
        bar = min_candidate_severity()
        if "C12" in kind and sev and SEVERITY_ORDER[sev] < SEVERITY_ORDER[bar]:                    # 6. below the bar
            return out("Rejected by rule", "C12", f"A real difference, but judged {sev}: below the bar of {bar} for a "
                       f"major red flag. {why}".strip())
        return out("Candidate", None, why)                         # 7.
    if status == "cannot_decide":
        return out("Needs review", None, why or "The judge could not decide.")
    fallback = {"known_change": "C1", "not_in_documents": "C14"}.get(status, "C15")
    rule = judge_reject or (fallback if fallback in kind else None)
    if rule is None:
        return out("Needs review", None, f"The judge said {status.replace('_', ' ')}, but the rule for it is switched off. {why}".strip())
    return out("Rejected by rule", rule, why)
