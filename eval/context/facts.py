"""The fact sheet and the document dates: values, their status and the chain of changes between them."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from .. import contract, matching, store


def load_facts(room: str | None = None) -> list[dict]:
    facts = store._read(store.ANSWER_KEY / "facts.json", []) or []
    return [f for f in facts if room is None or f.get("data_room") == room]


def doc_info(room: str) -> dict[str, dict]:
    """{doc_id: document entry} for one room, with doc_date and authority when the sheet gives them."""
    return {doc: d for (r, doc), d in store.load_documents().items() if r == room}


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


def text_hash(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]
