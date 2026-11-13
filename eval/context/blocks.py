"""The <data_room_context> block shown to the model with a case or a finding."""
from __future__ import annotations

from .. import matching
from .facts import _src, _src_text, chain, chain_text, doc_info, load_facts, norm_values
from .rules import rules_on


def _fact_line(f: dict, facts: list[dict]) -> str:
    unit = f" ({f['unit_basis']})" if f.get("unit_basis") else ""
    line = (f"- {f['fact_id']} | {f.get('subject') or 'other'} | {f.get('scope') or 'whole project'} | "
            f"{f.get('value')}{unit} | {f.get('value_status') or 'status not given'} | as of {f.get('as_of') or 'not given'} | "
            f"source {_src_text(f.get('source')) or 'not given'}")
    if len(chain(f, facts)) > 1:
        line += f"\n  Change chain: {chain_text(f, facts)}"
    return line


def _block(room: str, facts: list[dict], doc_ids: set[str], all_facts: list[dict], rules: list[dict], max_facts: int | None,
           rule_names_only: bool = False) -> str:
    docs = doc_info(room)
    if max_facts is not None:
        facts = facts[:max_facts]
    doc_ids = set(doc_ids) | {d for f in facts for d in [_src(f.get("source")).get("doc_id"), _src(f.get("change_source")).get("doc_id")] if d}
    if rule_names_only:          # the case already states the correct reading, so the rule text is not needed
        L = ["<data_room_context>", "Context rules in force (names only): "
             + "; ".join(f"{r['rule_id']} {r['name']} ({r['type']})" for r in rules) + "."]
    else:
        L = ["<data_room_context>", "Context rules (apply them as written):"]
        L += [f"- {r['rule_id']} [{r['type']}] {r['name']}: {r['text']}" for r in rules]
    L += ["", "Known facts:"]
    L += [_fact_line(f, all_facts) for f in facts] or ["- No fact is recorded for this."]
    L += ["", "Documents (date and authority; an empty date means the date is not recorded):"]
    for d in sorted(doc_ids):
        info = docs.get(d, {})
        L.append(f"- {d} | {info.get('title') or 'title not recorded'} | date {info.get('doc_date') or 'not recorded'} | "
                 f"{info.get('authority') or 'authority not recorded'} | {info.get('status') or 'status not recorded'}")
    L.append("</data_room_context>")
    return "\n".join(L)


def block_for_case(case: dict, facts: list[dict] | None = None, rules: list[dict] | None = None,
                   max_facts: int | None = None, rule_names_only: bool = False) -> str:
    """The context for one answer-key case: its linked facts with their change chains, the dates and
    authority of the documents it cites, and the rules that are switched on."""
    room = case["data_room"]
    all_facts = load_facts(room) if facts is None else [f for f in facts if f.get("data_room") == room]
    ids = set(case.get("register_ids") or [])
    linked, seen = [], set()
    for f in all_facts:
        if f["fact_id"] in ids:
            for member in chain(f, all_facts):
                if member["fact_id"] not in seen:
                    seen.add(member["fact_id"])
                    linked.append(member)
    doc_ids = set(case.get("documents") or []) | {c["doc_id"] for c in case.get("citations") or [] if c.get("doc_id")}
    return _block(room, linked, doc_ids, all_facts, rules_on(rules), max_facts, rule_names_only)


def _finding_text(finding: dict) -> str:
    return " ".join([finding.get("summary") or "", finding.get("claims_compared") or "", finding.get("explanation") or "",
                     " || ".join(c.get("quote") or "" for c in finding.get("citations") or [])])


def _finding_values(finding: dict) -> set[str]:
    return (matching.key_values(finding.get("summary") or "") | matching.key_values(finding.get("claims_compared") or "")
            | matching.key_values(" || ".join(c.get("quote") or "" for c in finding.get("citations") or [])))


def facts_for_finding(finding: dict, room: str, facts: list[dict] | None = None) -> list[dict]:
    """Facts whose values, subject or documents overlap the finding, closest first."""
    all_facts = load_facts(room) if facts is None else [f for f in facts if f.get("data_room") == room]
    vals, text = _finding_values(finding), _finding_text(finding).lower()
    docs = {c["doc_id"] for c in finding.get("citations") or [] if c.get("doc_id")}
    scored = []
    for f in all_facts:
        score = 3 * bool(norm_values(f) & vals) + 2 * bool(f.get("subject") and str(f["subject"]).lower() in text)
        if score:
            scored.append((score + bool(_src(f.get("source")).get("doc_id") in docs), f))
    return [f for _, f in sorted(scored, key=lambda t: -t[0])]


def block_for_finding(finding: dict, room: str, facts: list[dict] | None = None, rules: list[dict] | None = None,
                      max_facts: int | None = 15) -> str:
    all_facts = load_facts(room) if facts is None else [f for f in facts if f.get("data_room") == room]
    near, seen = [], set()
    for f in facts_for_finding(finding, room, all_facts):
        for member in chain(f, all_facts):
            if member["fact_id"] not in seen:
                seen.add(member["fact_id"])
                near.append(member)
    docs = {c["doc_id"] for c in finding.get("citations") or [] if c.get("doc_id")}
    return _block(room, near, docs, all_facts, rules_on(rules), max_facts)
