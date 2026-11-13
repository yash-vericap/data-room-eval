"""What the fact sheet alone says about a finding, before any model is asked."""
from __future__ import annotations

from .. import matching
from .blocks import _finding_values
from .facts import _src, _src_text, as_date, doc_info, load_facts, norm_values
from .rules import ACTUAL, FORECAST, TAG_RULE


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
