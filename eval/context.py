"""The data room context layer: what is known about a data room besides its documents.

Three parts:
- the fact sheet (answer_key/facts.json): values with their status, date, source and the fact each one replaces;
- document attributes (doc_date and authority in answer_key/documents.json);
- the context rules (answer_key/context_rules.json, or DEFAULT_RULES when the file is missing).

It is used in four places: as a block of text in every check message (block_for_case, block_for_finding),
in the rule pre-check that runs before a leftover finding is judged (precheck), in the rule gate that
runs after it (gate), and in the sheet upload, which warns about cases that rest on unrecorded changes.

Everything here is rule-based and gives the same answer every time. Rules, facts and document dates are
changed in the evaluation sheet and uploaded; nothing in this module writes to them.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date

from . import contract, matching, store

SUBJECTS = ["QRE", "federal credit amount", "state credit amount", "credit price", "credit type", "equity amount",
            "loan amount", "developer fee", "total development cost", "placed in service date", "completion date",
            "Part 2 approval date", "Part 3 approval date", "closing date", "ownership share", "scope", "other"]
VALUE_STATUSES = ["Actual", "Signed", "Approved", "Estimate", "Target", "Projected", "Draft", "Superseded"]
FORECAST = {"Estimate", "Target", "Projected"}
ACTUAL = {"Actual"}
AUTHORITY = ["Executed legal document", "Government approval", "Third-party certification",
             "Lender or investor document", "Financial model", "Presentation or summary", "Correspondence", "Draft"]
RULE_TYPES = ["Reject", "Flag", "Guide"]
TAG_RULE = {"Known change": "C1", "Stale value": "C2", "Unexplained change": "C3", "Two forecasts": "C4",
            "Forecast against actual": "C5", "Two actuals": "C6", "Different basis": "C9"}
FLAG_TAGS = {"Stale value", "Unexplained change", "Two actuals"}


def _rule(rule_id, type_, name, text, expected="", critical=True, **extra):
    return {"rule_id": rule_id, "name": name, "text": text, "type": type_, "expected_class": expected,
            "critical": critical, "on": True, "notes": "", **extra}


DEFAULT_RULES = [
    _rule("C1", "Reject", "Documented change",
          "When a value changes through a dated document that records the change and its reason (an amendment, a "
          "repricing letter, a rate reset, a signed change order), the old and new values are not a discrepancy "
          "between themselves.", "Contextual difference"),
    _rule("C2", "Flag", "Stale value after a change",
          "A document dated after a change, or presented as current (a revised deck, a snapshot sent to a buyer), that "
          "still carries the old value is a discrepancy. C1 never covers this case.", "Contradiction"),
    _rule("C3", "Flag", "Unexplained change",
          "Two values for the same subject and scope, both presented as current, with no document recording a change, "
          "are a contradiction. When a change is mentioned but the document that records it is missing, the issue is "
          "missing evidence.", "Contradiction, or Insufficient evidence"),
    _rule("C4", "Reject", "Two forecasts",
          "Estimated, target, anticipated, scheduled, projected and expected dates or figures are forecasts. Two "
          "forecasts that differ, in documents of different dates, are not a contradiction: the forecast moved. Two "
          "forecasts that differ in documents of the same date or version are a contradiction, and this rule does not "
          "reject them.", "Contextual difference"),
    _rule("C5", "Reject", "Forecast against actual",
          "A forecast that differs from a later actual value is not a contradiction. A document dated after the actual "
          "value that still presents the forecast as current falls under C2.", "Contextual difference"),
    _rule("C6", "Flag", "Two actuals",
          "Two values stated as actual for the same event (placed in service, completion, closing) that differ are a "
          "contradiction, whatever the documents are.", "Contradiction"),
    _rule("C7", "Flag", "Unexplained delay that matters",
          "An actual date later than a forecast or a deadline in a legal document is missing evidence when the delay "
          "changes something that matters (the credit year, a loan maturity, an investor installment, a compliance "
          "period) and no document explains it, even though the dates are not a contradiction.", "Insufficient evidence"),
    _rule("C8", "Reject", "Signed against draft",
          "Where a signed and a draft version differ, the signed one governs and the difference is not a discrepancy. "
          "A document that relies on the draft's figure falls under C2.", "Contextual difference"),
    _rule("C9", "Reject", "Different basis",
          "Different units, scope (one building against the project), basis (gross against net, per credit against "
          "total) or phase are not a discrepancy once converted to the same basis. Values that still differ after "
          "conversion are not rejected.", "Contextual difference"),
    _rule("C10", "Guide", "Authority",
          "When documents conflict, the more authoritative document is taken as correct when naming the stale one. "
          "The conflict is still reported.", "", critical=False),
    _rule("C11", "Reject", "Same event",
          "Two dates are compared only when they refer to the same event. \"Launched\", \"opened\" or \"began "
          "operations\" are not the same as \"placed in service\" unless the fact sheet maps them to the same subject."),
    _rule("C12", "Reject", "Immaterial difference",
          "Rounding, formatting, typing errors and naming variants that do not change the meaning are not red flags. "
          "A money difference within the threshold (the larger of $1,000 and 0.5% of the larger value) is immaterial.",
          "Consistent", min_amount=1000, min_share=0.005),
    _rule("C13", "Reject", "Decided before",
          "A finding that matches a candidate the evaluator already rejected in an earlier check, on the same data "
          "room and answer key, gets the same decision.", "(as decided)", critical=False),
    _rule("C14", "Reject", "Evidence not found",
          "Every quote the finding gives is missing from the documents, and the judge found the claim is not in the "
          "pages. The finding is made up or misread."),
    _rule("C15", "Reject", "Out of scope",
          "Advice, recommendations, best practice and general risks that are not a conflict between documents or a "
          "missing piece of evidence the deal relies on.", "", critical=False),
]
RULE_FIELDS = ["rule_id", "name", "text", "type", "expected_class", "critical", "on"]
FACT_FIELDS = ["fact_id", "data_room", "subject", "scope", "value", "unit_basis", "value_status", "as_of", "source",
               "supersedes", "change_reason", "change_source", "notes"]
SEVERITY_ORDER = {s: i for i, s in enumerate(reversed(contract.SEVERITIES))}     # Low 0 ... Critical 3


# ---- loading ------------------------------------------------------------------------------------------

def load_rules() -> list[dict]:
    """The rule bundle: the uploaded rules, or the defaults when no Context Rules tab was ever uploaded."""
    rules = store._read(store.ANSWER_KEY / "context_rules.json")
    return rules if rules else [dict(r) for r in DEFAULT_RULES]


def rules_on(rules: list[dict] | None = None) -> list[dict]:
    return [r for r in (load_rules() if rules is None else rules) if r.get("on", True)]


def rule_name(rule_id: str | None, rules: list[dict] | None = None) -> str:
    r = next((r for r in (load_rules() if rules is None else rules) if r["rule_id"] == rule_id), None)
    return f"{rule_id} {r['name']}" if r else (rule_id or "")


def load_facts(room: str | None = None) -> list[dict]:
    facts = store._read(store.ANSWER_KEY / "facts.json", []) or []
    return [f for f in facts if room is None or f.get("data_room") == room]


def doc_info(room: str) -> dict[str, dict]:
    """{doc_id: document entry} for one room, with doc_date and authority when the sheet gives them."""
    return {doc: d for (r, doc), d in store.load_documents().items() if r == room}


def min_candidate_severity() -> str:
    return contract._label(os.environ.get("EVAL_MIN_CANDIDATE_SEVERITY"), contract.SEVERITIES) or "Medium"


# ---- values and dates -----------------------------------------------------------------------------------

def norm_values(fact: dict) -> set[str]:
    """The fact's value in the matcher's standard form. Worked out on load, never stored."""
    value, unit = str(fact.get("value") or ""), str(fact.get("unit_basis") or "")
    if re.search(r"thousand|000s", unit, re.I) and "thousand" not in value.lower():
        value += " ($ in thousands)"
    return matching.key_values(value)


def as_date(text) -> date | None:
    """A date from '2025-01-15', 'January 15, 2025' or '1/15/2025'. None when there is none."""
    text = str(text or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    full = sorted(v for v in matching.key_values(text) if v.startswith("d:"))
    if full:
        y, mo, d = (int(x) for x in full[0][2:].split("-"))
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def _src(value) -> dict:
    """A source or change source as {doc_id, page, location, quote, raw}, from a dict or a citation string."""
    if isinstance(value, dict):
        return value
    cits = contract.parse_citations(str(value or ""))
    return cits[0] if cits else {}


def _src_text(value) -> str:
    s = _src(value)
    if not s or not s.get("doc_id"):
        return ""
    return s["doc_id"] + (f" p.{s['page']}" if s.get("page") is not None else "")


def chain(fact: dict, facts: list[dict]) -> list[dict]:
    """The full change chain a fact belongs to, oldest value first."""
    by_id = {f["fact_id"]: f for f in facts if f.get("data_room") == fact.get("data_room")}
    first, seen = fact, {fact["fact_id"]}
    while first.get("supersedes") in by_id and first["supersedes"] not in seen:
        first = by_id[first["supersedes"]]
        seen.add(first["fact_id"])
    out, cur = [first], first
    while True:
        nxt = next((f for f in by_id.values() if f.get("supersedes") == cur["fact_id"] and f not in out), None)
        if nxt is None:
            return out
        out.append(nxt)
        cur = nxt


def chain_text(fact: dict, facts: list[dict]) -> str:
    """'R-004 $25 Signed 2024-03-01 → R-019 $20 Signed 2025-01-15 (rate reset; DOC-17 p.3)'."""
    parts = []
    for f in chain(fact, facts):
        text = " ".join(str(x) for x in [f["fact_id"], f.get("value"), f.get("value_status"), f.get("as_of")] if x)
        if f.get("supersedes"):
            why = "; ".join(x for x in [str(f.get("change_reason") or ""), _src_text(f.get("change_source"))] if x)
            text += f" ({why})" if why else " (no document records this change)"
        parts.append(text)
    return " → ".join(parts)


# ---- the block of text shown to the model ----------------------------------------------------------------

def _fact_line(f: dict, facts: list[dict]) -> str:
    unit = f" ({f['unit_basis']})" if f.get("unit_basis") else ""
    line = (f"- {f['fact_id']} | {f.get('subject') or 'other'} | {f.get('scope') or 'whole project'} | "
            f"{f.get('value')}{unit} | {f.get('value_status') or 'status not given'} | as of {f.get('as_of') or 'not given'} | "
            f"source {_src_text(f.get('source')) or 'not given'}")
    if len(chain(f, facts)) > 1:
        line += f"\n  Change chain: {chain_text(f, facts)}"
    return line


def _block(room: str, facts: list[dict], doc_ids: set[str], all_facts: list[dict], rules: list[dict], max_facts: int | None) -> str:
    docs = doc_info(room)
    if max_facts is not None:
        facts = facts[:max_facts]
    doc_ids = set(doc_ids) | {d for f in facts for d in [_src(f.get("source")).get("doc_id"), _src(f.get("change_source")).get("doc_id")] if d}
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
                   max_facts: int | None = None) -> str:
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
    return _block(room, linked, doc_ids, all_facts, rules_on(rules), max_facts)


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


def text_hash(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


# ---- rule pre-check ---------------------------------------------------------------------------------------

def _tag(tag: str, facts: list[dict], reason: str) -> dict:
    return {"tag": tag, "rule_id": TAG_RULE[tag], "facts": [f["fact_id"] for f in facts], "reason": reason}


def _same_scope(a: dict, b: dict) -> bool:
    sa, sb = str(a.get("scope") or "").strip().lower(), str(b.get("scope") or "").strip().lower()
    return not sa or not sb or sa == sb


def _doc_values(finding: dict) -> dict[str, set[str]]:
    """Which values each cited document carries, going by the finding's own quotes."""
    out: dict[str, set[str]] = {}
    for c in finding.get("citations") or []:
        if c.get("doc_id"):
            out.setdefault(c["doc_id"], set()).update(matching.key_values(c.get("quote") or ""))
    return out


def precheck(finding: dict, room: str, facts: list[dict] | None = None, docs: dict | None = None) -> dict | None:
    """What the fact sheet alone says about a finding, before any model is asked.

    Returns {"tag", "rule_id", "facts", "reason"}, or None when the facts do not settle it. The tags are
    Known change, Stale value, Unexplained change, Two forecasts, Forecast against actual, Two actuals
    and Different basis. A rule that needs a document date and finds none gives no tag."""
    all_facts = load_facts(room) if facts is None else [f for f in facts if f.get("data_room") == room]
    docs = doc_info(room) if docs is None else docs
    vals = _finding_values(finding)
    hit = [f for f in all_facts if norm_values(f) & vals]
    if len(hit) < 2:
        return None
    carried = _doc_values(finding)
    ddate = lambda doc: as_date((docs.get(doc) or {}).get("doc_date"))

    # 1. a value and the value that replaced it
    for new in hit:
        old = next((f for f in hit if f["fact_id"] == new.get("supersedes")), None)
        if old is None:
            continue
        pair = [old, new]
        if not _src(new.get("change_source")).get("doc_id"):
            return _tag("Unexplained change", pair, f"{new['fact_id']} replaces {old['fact_id']} ({old.get('value')} to "
                        f"{new.get('value')}), but no document records the change.")
        changed = as_date(new.get("as_of")) or ddate(_src(new.get("change_source")).get("doc_id"))
        old_vals, new_vals = norm_values(old) - norm_values(new), norm_values(new) - norm_values(old)
        own_old = {_src(old.get("source")).get("doc_id")}
        own_new = {_src(new.get("source")).get("doc_id"), _src(new.get("change_source")).get("doc_id")}
        undated = False
        for doc, v in carried.items():
            if not (v & old_vals) or v & new_vals or doc in own_old or doc in own_new:
                continue                     # only a third document that carries the old value can be stale
            when = ddate(doc)
            if when is None or changed is None:
                undated = True
            elif when > changed:
                return _tag("Stale value", pair, f"{doc}, dated {when.isoformat()}, still carries {old.get('value')} after "
                            f"the change to {new.get('value')} on {changed.isoformat()} ({new['fact_id']}).")
        if undated:
            return None                      # cannot decide without the document's date
        return _tag("Known change", pair, f"{old.get('value')} became {new.get('value')} "
                    f"({new.get('change_reason') or 'recorded change'}; {_src_text(new.get('change_source'))}), "
                    f"and each cited document carries the value of its own date.")

    # 2. two values for one subject and scope with no link between them
    for i, a in enumerate(hit):
        for b in hit[i + 1:]:
            if not a.get("subject") or a.get("subject") != b.get("subject") or not _same_scope(a, b):
                continue
            va, vb = norm_values(a), norm_values(b)
            if va & vb:
                if str(a.get("value")) != str(b.get("value")) or a.get("unit_basis") != b.get("unit_basis"):
                    return _tag("Different basis", [a, b], f"{a.get('value')} ({a.get('unit_basis') or 'no unit'}) and "
                                f"{b.get('value')} ({b.get('unit_basis') or 'no unit'}) are the same once converted.")
                continue
            sa, sb = a.get("value_status"), b.get("value_status")
            if sa in ACTUAL and sb in ACTUAL:
                return _tag("Two actuals", [a, b], f"{a['fact_id']} ({a.get('value')}) and {b['fact_id']} ({b.get('value')}) "
                            f"are both stated as actual for {a['subject']}.")
            da, db = ddate(_src(a.get("source")).get("doc_id")), ddate(_src(b.get("source")).get("doc_id"))
            if sa in FORECAST and sb in FORECAST:
                if da is None or db is None:
                    return None
                if da == db:
                    return _tag("Unexplained change", [a, b], f"Two forecasts for {a['subject']} differ in documents of the "
                                f"same date ({da.isoformat()}).")
                return _tag("Two forecasts", [a, b], f"{a.get('value')} and {b.get('value')} are both forecasts for "
                            f"{a['subject']}, in documents dated {da.isoformat()} and {db.isoformat()}: the forecast moved.")
            if (sa in FORECAST and sb in ACTUAL) or (sa in ACTUAL and sb in FORECAST):
                fc, act, fc_date = (a, b, da) if sa in FORECAST else (b, a, db)
                happened = as_date(act.get("as_of")) or as_date(act.get("value"))
                if fc_date and happened and fc_date > happened:
                    return _tag("Stale value", [fc, act], f"{_src_text(fc.get('source'))}, dated {fc_date.isoformat()}, still "
                                f"presents the forecast {fc.get('value')} after the actual {act.get('value')}.")
                return _tag("Forecast against actual", [fc, act], f"{fc.get('value')} was a forecast "
                            f"({fc.get('value_status')}); {act.get('value')} is the actual value for {a['subject']}.")
            if "Superseded" in (sa, sb) or "Draft" in (sa, sb):
                continue
            return _tag("Unexplained change", [a, b], f"{a['fact_id']} ({a.get('value')}) and {b['fact_id']} ({b.get('value')}) "
                        f"are both current for {a['subject']}, and no document records a change between them.")
    return None


# ---- rule gate --------------------------------------------------------------------------------------------

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


# ---- coverage of the rules by test cases --------------------------------------------------------------------

def case_rules(case: dict, rules: list[dict] | None = None) -> list[str]:
    """Rule IDs a case is a test case for: those named in its scenario tags."""
    ids = {r["rule_id"].upper() for r in (load_rules() if rules is None else rules)}
    found = []
    for tag in case.get("scenario_tags") or []:
        m = re.match(r"\s*(C\d+)\b", str(tag), re.I)
        if m and m.group(1).upper() in ids and m.group(1).upper() not in found:
            found.append(m.group(1).upper())
    return found


def coverage(cases: list[dict], rules: list[dict] | None = None) -> list[dict]:
    """Test cases per rule and data room. A Reject rule needs a non-issue case, a Flag rule a reportable one."""
    rules = load_rules() if rules is None else rules
    rooms = sorted({c["data_room"] for c in cases})
    rows = []
    for r in rules:
        for room in rooms:
            mine = [c for c in cases if c["data_room"] == room and r["rule_id"] in case_rules(c, rules)]
            rep, non = sum(bool(c["report"]) for c in mine), sum(not c["report"] for c in mine)
            need = "non-issue case" if r["type"] == "Reject" else "reportable case" if r["type"] == "Flag" else ""
            gap = bool(r.get("critical")) and ((r["type"] == "Reject" and not non) or (r["type"] == "Flag" and not rep))
            rows.append({"rule_id": r["rule_id"], "name": r["name"], "type": r["type"], "critical": bool(r.get("critical")),
                         "data_room": room, "reportable": rep, "non_issue": non, "gap": gap,
                         "needs": f"at least one {need}" if gap else ""})
    return rows
