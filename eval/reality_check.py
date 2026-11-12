"""The Vericap run check: one run of our own system against the ground truth and the documents.

The run does not have to follow the output contract. read_findings() finds the list of findings in any
JSON shape and reads each one leniently. The check then has two steps, each one model call per item:

1. Every ground-truth case against the run: Found, Partially found or Missed for a reportable case;
   Not flagged, Labelled correctly or Wrongly flagged for a non-issue case.
2. Every finding that maps to no case against the documents: a real issue the ground truth does not
   have, a known change, not a discrepancy, or not in the documents. The rule gate (eval/context.py)
   then rejects what the rules exclude, so a reviewer only sees findings that could matter.

Safeguards: every verdict must quote a passage, and the quote is checked by rule against what the model
was shown; finding IDs and rule IDs are checked against the real lists; the model can never add a case
or change a label. A manual verdict always wins over the model's.

Every verdict is saved the moment it exists (reality_checks/<check_id>.json), so a check stopped by a
provider limit loses nothing and carries on when run again.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import context, contract, judge, library, matching, scoring, store
from .providers import JudgeQuotaReached, JudgeUnavailable, settings

PROMPT_VERSION = "RC-v2"
CHECKS = store.DATA / "reality_checks"
PARTIAL_CREDIT = 0.5

FOUND, PARTIAL, MISSED, REVIEW = "Found", "Partially found", "Missed", "Needs review"
NOT_FLAGGED, LABELLED, WRONG = "Not flagged", "Labelled correctly", "Wrongly flagged"
REAL, KNOWN, NOT_DISC, NOT_IN_DOCS = "Real issue, not in ground truth", "Known change", "Not a discrepancy", "Not in documents"
CASE_LABELS = {"found": FOUND, "partially_found": PARTIAL, "missed": MISSED, "cannot_decide": REVIEW,
               "wrongly_flagged": WRONG, "labelled_correctly": LABELLED, "not_flagged": NOT_FLAGGED}
NEW_LABELS = {"real_issue": REAL, "known_change": KNOWN, "not_a_discrepancy": NOT_DISC, "not_in_documents": NOT_IN_DOCS,
              "cannot_decide": REVIEW}
NEW_RAW = {v: k for k, v in NEW_LABELS.items()}
LINKING = {FOUND, PARTIAL, WRONG, LABELLED}                 # statuses that tie a finding to a case
CANDIDATE, REJECTED_RULE, REJECTED_EVALUATOR = "Candidate", "Rejected by rule", "Rejected by evaluator"
BANDS = [CANDIDATE, REVIEW, REJECTED_RULE, REJECTED_EVALUATOR]
STATUS_ORDER = [MISSED, WRONG, REVIEW, "Not checked", PARTIAL, FOUND, LABELLED, NOT_FLAGGED]

SYSTEM = """You are an independent reviewer of an AI system that looks for discrepancies across the documents of a deal data room (US historic tax credit deals). An evaluator wrote the ground truth by hand. You compare the system's output with the ground truth and with the documents. Your verdict is used to score the system, so accuracy matters more than being agreeable: a confident, well-written finding can still be wrong or only half right.

Use only what is in the message. Do not use outside knowledge and do not assume what other documents say. When the material does not settle the question, answer "cannot_decide"; that is better than a guess. Different wording from the ground truth is fine. Sharing a document or a figure is not enough on its own: a finding covers a case only when it is about the same underlying problem.

The message may hold a data room context: known facts, the changes between them, document dates and authority, and context rules. Apply the rules as written. Read the wording of every date and figure: an estimate, target or projection is a forecast, not a fact, and a value that a dated document has replaced is no longer current."""

_QUOTE = ("quote: the passage your verdict relies on most, copied word for word from the material in the message. It is "
          "checked automatically, and a quote that is not in the message voids the verdict.")
TASK_REPORTABLE = f"""Your task: decide whether the run's findings cover the ground-truth case in the message.

status:
- found: a finding states the same problem with its essential facts: the right documents on both sides, the conflicting figures, dates or terms, and the right conclusion. Differences in wording and severity do not matter.
- partially_found: a finding is about this problem but leaves out or gets wrong an essential part: only one side of the conflict, a missing document the case rests on, a wrong figure or date, half the conclusion, or a symptom reported without its cause.
- missed: no finding is about this problem.
- cannot_decide: the material does not settle it.
finding_ids: the IDs of the findings that cover the case, exactly as written. Empty when missed.
covered: one sentence on what the run got right. Empty when missed.
missing: one sentence on what was left out or wrong. Empty when found.
{_QUOTE}
explanation: one sentence on why."""
TASK_NON_ISSUE = f"""Your task: the ground-truth case in the message is a known non-issue. The documents differ or look odd, but it must not be reported as a problem. Decide what the run did with it.

status:
- wrongly_flagged: a finding reports it as a contradiction or as missing evidence.
- labelled_correctly: a finding mentions it but calls it explained, contextual or consistent.
- not_flagged: no finding is about it.
- cannot_decide: the material does not settle it.
finding_ids: the IDs of the findings that are about this case, exactly as written. Empty when not flagged.
covered: one sentence on what the run said about it. Empty when not flagged.
missing: one sentence on what the run got wrong. Empty when it was right.
{_QUOTE}
explanation: one sentence on why."""
TASK_LEFTOVER = """Your task: the finding in the message maps to no ground-truth case. Decide from the document pages whether it is a real issue.

status:
- real_issue: the pages show a genuine discrepancy, or genuinely missing evidence, as the finding says.
- known_change: the difference is a change the data room records (an amendment, a repricing, a rate reset, a signed change order), or two forecasts that moved, so the context rules say it is not a discrepancy.
- not_a_discrepancy: the figures or passages exist, but they agree, or the difference is explained in another way such as a different basis, phase or unit.
- not_in_documents: the figures, quotes or claims cannot be found in the pages, or the pages say something else.
- cannot_decide: the pages do not settle it.
rule_ids: the IDs of the context rules your verdict relies on, for example C1. Empty when none applies.
fact_or_judgment: "fact" when the issue can be checked against the documents, "judgment" when it rests on opinion.
why_it_matters: one sentence on what goes wrong for the customer or investor if this is real. Empty when it is not real.
why_it_might_not: one sentence giving the strongest reason this may not belong in the ground truth. Empty when there is none.
severity: Critical, High, Medium or Low for a real issue, otherwise not_applicable.
quote: a passage copied word for word from the pages that your verdict rests on, or empty when the pages hold nothing relevant.
explanation: one sentence on why.
A rule pre-check result may be shown. It comes from fixed rules and the fact sheet; you may disagree with it."""


def _schema(statuses: list[str]) -> dict:
    props = {"status": {"type": "string", "enum": statuses}, "finding_ids": {"type": "array", "items": {"type": "string"}},
             "covered": {"type": "string"}, "missing": {"type": "string"}, "quote": {"type": "string"},
             "explanation": {"type": "string"}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA_REPORTABLE = _schema(["found", "partially_found", "missed", "cannot_decide"])
SCHEMA_NON_ISSUE = _schema(["wrongly_flagged", "labelled_correctly", "not_flagged", "cannot_decide"])
_NEW_PROPS = {
    "status": {"type": "string", "enum": list(NEW_LABELS)}, "rule_ids": {"type": "array", "items": {"type": "string"}},
    "fact_or_judgment": {"type": "string", "enum": ["fact", "judgment"]}, "why_it_matters": {"type": "string"},
    "why_it_might_not": {"type": "string"},
    "severity": {"type": "string", "enum": contract.SEVERITIES + ["not_applicable"]},
    "quote": {"type": "string"}, "explanation": {"type": "string"}}
SCHEMA_LEFTOVER = {"type": "object", "properties": _NEW_PROPS, "required": list(_NEW_PROPS), "additionalProperties": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- reading a run in any JSON shape ------------------------------------------------------------------------

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
_DOC = re.compile(r"\bDOC[-_ ]?0*(\d+)\b", re.I)
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


def _doc_id(text) -> str | None:
    m = _DOC.search(str(text or ""))
    return f"DOC-{int(m.group(1)):02d}" if m else None


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
                items.append({"doc_id": _doc_id(_get(item, _CIT_KEYS["doc_id"])) or _doc_id(json.dumps(item, default=str)),
                              "page": _get(item, _CIT_KEYS["page"]), "location": _text(_get(item, _CIT_KEYS["location"])),
                              "quote": _text(_get(item, _CIT_KEYS["quote"]))})
            elif item not in (None, ""):
                items.append(_fix_docs(str(item)))
        cits = contract.parse_citations(items)
    for c in cits:
        c["doc_id"] = _doc_id(c["doc_id"]) if c.get("doc_id") else None
        if c["doc_id"] and not c["quote"]:
            c["raw"] = c["doc_id"] + (f" p.{c['page']}" if c["page"] is not None else "")
        elif c["doc_id"]:
            c["raw"] = (f"{c['doc_id']}" + (f" p.{c['page']}" if c["page"] is not None else "")
                        + (f", {c['location']}" if c["location"] else "") + f": '{c['quote']}'")
    return cits


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
    if isinstance(payload, dict):
        meta = next((payload[k] for k in ("run", "run_details", "metadata") if isinstance(payload.get(k), dict)), {})
        meta = dict(meta)
        room = meta.get("data_room") or meta.get("data_room_id") or payload.get("data_room") or payload.get("data_room_id")
        if room:
            meta["data_room"] = str(room).strip().upper()

    findings, notes = [], []
    for i, item in enumerate(rows, start=1):
        claims, explanation = _text(_get(item, ALIASES["claims_compared"])), _text(_get(item, ALIASES["explanation"]))
        raw = json.dumps(item, ensure_ascii=False, default=str)
        summary = _text(_get(item, ALIASES["summary"])) or (claims or explanation or raw)[:240]
        cits = _citations(_get(item, ALIASES["citations"]))
        cited = {c["doc_id"] for c in cits if c["doc_id"]}
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

    note(sum(not any(c["doc_id"] for c in f["citations"]) for f in findings), "names no document.", "name no document.")
    note(sum(not any(c["quote"] for c in f["citations"]) for f in findings), "quotes no passage.", "quote no passage.")
    note(sum(f["classification"] is None for f in findings), "has no class that could be read.", "have no class that could be read.")
    note(sum(f["severity"] is None for f in findings), "has no severity that could be read.", "have no severity that could be read.")
    return {"findings": findings, "source_path": path, "notes": notes, "run_meta": meta}


# ---- storage ---------------------------------------------------------------------------------------------------

_LOCK = threading.Lock()


def check_id(room: str, model: str, findings: list[dict]) -> str:
    parts = [room, model, PROMPT_VERSION]
    for f in findings:
        parts += [f["finding_id"], f["summary"], f["claims_compared"], " || ".join(c["raw"] for c in f["citations"])]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def _path(cid: str):
    return CHECKS / f"{cid}.json"


def save(check: dict) -> None:
    store._write(_path(check["check_id"]), check)


def load_check(cid: str) -> dict | None:
    return store._read(_path(cid))


def list_checks() -> list[dict]:
    """Stored checks, newest first: {"check_id", "label", "data_room", "created_at", "findings"}."""
    out = []
    for path in CHECKS.glob("*.json") if CHECKS.exists() else []:
        c = store._read(path) or {}
        if c.get("check_id"):
            out.append({"check_id": c["check_id"], "label": c.get("label"), "data_room": c.get("data_room"),
                        "created_at": c.get("created_at"), "findings": len(c.get("findings") or [])})
    return sorted(out, key=lambda c: c["created_at"] or "", reverse=True)


def open_check(room: str, label: str, read: dict, model: str | None = None) -> dict:
    """The stored check for this run and model, or a new one. The same run with the same model reopens the
    same check, so a check that stopped halfway carries on."""
    cfg = settings()
    model = model or cfg["model"] or "unset"
    cid = check_id(room, model, read["findings"])
    check = load_check(cid)
    if check is None:
        check = {"check_id": cid, "label": label, "data_room": room, "source": "Our system", "snapshot": None,
                 "model": model, "provider": cfg["provider"], "prompt_version": PROMPT_VERSION, "created_at": _now(),
                 "source_path": read["source_path"], "read_notes": read["notes"], "run_meta": read["run_meta"],
                 "findings": read["findings"], "case_verdicts": {}, "new_verdicts": {}, "manual": {},
                 "input_tokens": 0, "output_tokens": 0}
    elif label and label != check.get("label"):
        check["label"] = label
    save(check)
    return check


def set_manual(check: dict, kind: str, id_: str, status: str, finding_ids: list[str] | None = None, note: str = "",
               case_hash: str | None = None) -> None:
    """A verdict set by hand. kind is 'case' or 'finding'. It wins over the model's verdict from then on."""
    check["manual"][f"{kind}::{id_}"] = {"status": status, "finding_ids": list(finding_ids or []), "note": note,
                                         "at": _now(), "case_hash": case_hash}
    save(check)


def clear_manual(check: dict, kind: str, id_: str) -> None:
    if check["manual"].pop(f"{kind}::{id_}", None) is not None:
        save(check)


# ---- what the model is shown ---------------------------------------------------------------------------------------

def _finding_full(f: dict) -> str:
    return "\n".join([f'<finding id="{f["finding_id"]}">',
                      f"Class: {f['classification'] or f.get('raw_classification') or 'not given'}",
                      f"Severity: {f['severity'] or f.get('raw_severity') or 'not given'}",
                      f"Summary: {f['summary']}", f"Claims compared: {f['claims_compared'] or '(none)'}",
                      "Citations:", "\n".join(f"- {c['raw']}" for c in f["citations"]) or "- (none)",
                      f"Explanation: {f['explanation'] or '(none)'}", "</finding>"])


def _finding_short(f: dict) -> str:
    docs = ", ".join(sorted({c["doc_id"] for c in f["citations"] if c["doc_id"]})) or "no document"
    return f"- {f['finding_id']} | {f['classification'] or 'no class'} | {f['severity'] or 'no severity'} | {f['summary'][:200]} | {docs}"


def _page_of(cit: dict, chunks: dict) -> int | None:
    """The page a citation points at; when the page number is missing or wrong, the page that holds the quote."""
    pages = chunks.get(cit.get("doc_id") or "") or {}
    page = cit.get("page")
    if not cit.get("quote"):
        return page if page in pages else None
    if page in pages and scoring.quote_is_real(cit["quote"], {page: pages[page]}, page) == "Real":
        return page
    hit = next((p for p in sorted(x for x in pages if x is not None)
                if scoring.quote_is_real(cit["quote"], {p: pages[p]}, p) == "Real"), None)
    return hit if hit is not None else (page if page in pages else None)


def _pages_block(cits: list[dict], chunks: dict, radius: int | None, extra: list[tuple[str, int]] = ()) -> tuple[str, list]:
    """The cited pages as <page> blocks, whole or cut to an excerpt around the quoted words."""
    seen, parts, sent = set(), [], []
    todo = [(c["doc_id"], _page_of(c, chunks), c.get("quote") or "") for c in cits if c.get("doc_id")] + [(d, p, "") for d, p in extra]
    for doc, page, quote in todo:
        text = (chunks.get(doc) or {}).get(page) if page is not None else None
        if not text or ((doc, page) in seen and radius is None):
            continue
        body = text.strip() if radius is None else judge._excerpt(text.strip(), quote, radius)
        if (doc, page, body) in seen:
            continue
        seen.update({(doc, page), (doc, page, body)})
        parts.append(f'<page doc="{doc}" page="{page}">\n{body}\n</page>')
        if [doc, page] not in sent:
            sent.append([doc, page])
    if not parts:
        return ("The text of the cited pages is not stored. The only passages available are the quotes above. "
                "You cannot confirm that a quote really appears in its document."), []
    note = "Each block is an excerpt of the page around the quoted words, not the whole page.\n" if radius is not None else ""
    return note + "\n".join(parts), sent


def rank_findings(case: dict, findings: list[dict], index: matching.RoomIndex) -> list[dict]:
    """The findings most likely to be about a case, best first."""
    case_tok = set(index.case_tokens[case["case_id"]])
    scored = []
    for f in findings:
        s = index.score(f, case)["score"]
        if s == 0 and case_tok:          # no shared document: fall back to shared wording, at half weight
            tok = set(matching.tokens(" ".join([f["summary"], f["claims_compared"], f["explanation"]])))
            s = 0.5 * len(tok & case_tok) / len(case_tok)
        if s > 0.05:
            scored.append((s, f))
    return [f for _, f in sorted(scored, key=lambda t: -t[0])]


CASE_LEVELS = [(None, 8, None), (1200, 6, None), (600, 5, None), (300, 4, 40), (150, 3, 20)]   # radius, in full, listed
LEFTOVER_LEVELS = [None, 1500, 700, 300]


def case_message(case: dict, findings: list[dict], ranked: list[dict], chunks: dict, ctx: str, max_chars: int) -> tuple[str, list]:
    """The message for one case, cut to fit max_chars. The context block is never cut."""
    head = ["<ground_truth_case>", f"ID: {case['case_id']}", f"Expected class: {case['classification']}",
            f"Severity: {case['severity']}", f"Should be reported as a problem: {'yes' if case['report'] else 'no'}",
            f"Summary: {case['summary']}", f"Claims compared: {case['claims_compared']}", "Citations:",
            "\n".join(f"- {c['raw']}" for c in case["citations"]) or "- (none)",
            f"Correct interpretation: {case['explanation']}"]
    if case.get("alternative_readings"):
        head.append(f"Alternative readings: {case['alternative_readings']}")
    head += ["</ground_truth_case>", "", ctx, ""]
    message, sent = "", []
    for radius, n_full, n_listed in CASE_LEVELS:
        pages, sent = _pages_block(case["citations"], chunks, radius)
        full = ranked[:n_full]
        full_ids = {f["finding_id"] for f in full}
        rest = [f for f in findings if f["finding_id"] not in full_ids]
        listed = rest if n_listed is None else rest[:max(0, n_listed - len(full))]
        parts = head + ["<cited_pages>", pages, "</cited_pages>", "", f"<run_findings count=\"{len(findings)}\">"]
        parts += [_finding_full(f) for f in full] or ["No finding of the run shares a document or wording with this case."]
        if listed:
            parts += ["", "Other findings of the run, in short (ID | class | severity | summary | documents):"]
            parts += [_finding_short(f) for f in listed]
        if len(rest) > len(listed):
            parts.append(f"{len(rest) - len(listed)} more findings of the run are left out to keep this message short.")
        parts += ["</run_findings>", "", "Return your verdict."]
        message = "\n".join(parts)
        if len(message) <= max_chars:
            break
    return message, sent


def _best_pages(finding: dict, chunks: dict, n: int = 3) -> list[tuple[str, int]]:
    """The pages that best match a finding's summary and claims, for findings that cite too little."""
    text = f"{finding['summary']} {finding['claims_compared']}"
    vals, tok = matching.key_values(text), set(matching.tokens(text))
    scored = []
    for doc, pages in chunks.items():
        for page, body in pages.items():
            if page is None or not body:
                continue
            s = 3 * len(vals & matching.key_values(body)) + 5 * (len(tok & set(matching.tokens(body))) / len(tok) if tok else 0)
            if s > 0:
                scored.append((s, doc, page))
    return [(d, p) for _, d, p in sorted(scored, reverse=True)[:n]]


def leftover_message(finding: dict, chunks: dict, ctx: str, pre: dict | None, max_chars: int) -> tuple[str, list]:
    usable = {(c["doc_id"], _page_of(c, chunks)) for c in finding["citations"] if c.get("doc_id")}
    usable = {u for u in usable if u[1] is not None}
    extra = _best_pages(finding, chunks) if len(usable) < 2 else []
    head = [_finding_full(finding), "", ctx, ""]
    if pre:
        head += [f"Rule pre-check result (from fixed rules and the fact sheet; you may disagree): {pre['tag']} "
                 f"({pre['rule_id']}). {pre['reason']}", ""]
    message, sent = "", []
    for radius in LEFTOVER_LEVELS:
        pages, sent = _pages_block(finding["citations"], chunks, radius, extra)
        message = "\n".join(head + ["<document_pages>", pages, "</document_pages>", "", "Return your verdict."])
        if len(message) <= max_chars:
            break
    return message, sent


# ---- asking the model -------------------------------------------------------------------------------------------------

def _ask(client, model: str, task: str, message: str, schema: dict) -> dict:
    """One stateless call: the system prompt with the task, and one message. No tools, no history.
    Returns {"verdict": dict | None, "error", "input_tokens", "output_tokens"}. JudgeUnavailable and
    JudgeQuotaReached pass through."""
    return client.complete(model, SYSTEM + "\n\n" + task, message, schema)


def _shown(quote: str, material: str) -> bool:
    return scoring.quote_is_real(quote, {1: material}, 1) == "Real"


def case_hash(case: dict, ctx: str) -> str:
    """Changes when the case, or the context the model is shown for it, changes."""
    return context.text_hash(case["classification"], case["severity"], case["report"], case["summary"],
                             case["claims_compared"], " || ".join(c["raw"] for c in case["citations"]),
                             case["explanation"], case.get("alternative_readings") or "", ctx)


def _audit(cfg: dict, model: str, sent: list) -> dict:
    return {"provider": cfg["provider"], "model": model, "at": _now(), "pages": sent}


def judge_case(case: dict, findings: list[dict], ranked: list[dict], chunks: dict, client, model: str, cfg: dict,
               facts: list[dict] | None = None, rules: list[dict] | None = None) -> dict:
    ctx = context.block_for_case(case, facts, rules)
    if len(ctx) > cfg["max_input_chars"] // 2:
        ctx = context.block_for_case(case, facts, rules, max_facts=15)
    message, sent = case_message(case, findings, ranked, chunks, ctx, cfg["max_input_chars"])
    task, schema = (TASK_REPORTABLE, SCHEMA_REPORTABLE) if case["report"] else (TASK_NON_ISSUE, SCHEMA_NON_ISSUE)
    tin = tout = 0
    v, reason = None, None
    for _ in (1, 2):
        out = _ask(client, model, task, message, schema)
        tin, tout = tin + out["input_tokens"], tout + out["output_tokens"]
        if out["verdict"] is None:
            v, reason = None, out["error"] or "no usable answer"
            continue
        v = out["verdict"]
        if not v["quote"].strip() and v["status"] in ("missed", "not_flagged", "cannot_decide"):
            reason = None                     # nothing in the run is about the case, so there may be nothing to quote
            break
        if _shown(v["quote"], message):
            reason = None
            break
        reason = "the verdict quotes text that was not shown"
    known = {f["finding_id"] for f in findings}
    res = {"status": REVIEW, "raw_status": None, "finding_ids": [], "covered": "", "missing": "", "quote": "",
           "explanation": "", "case_hash": case_hash(case, ctx), "sent": _audit(cfg, model, sent),
           "input_tokens": tin, "output_tokens": tout}
    if v is None or reason:
        res["explanation"] = f"Needs review: {reason}." + (f" The model said: {v['explanation']}" if v else "")
        if v:
            res.update(raw_status=v["status"], quote=v["quote"])
        return res
    ids = [i for i in dict.fromkeys(v["finding_ids"]) if i in known]
    label = CASE_LABELS[v["status"]]
    res.update(status=label, raw_status=v["status"], finding_ids=ids if label in LINKING else [], covered=v["covered"],
               missing=v["missing"], quote=v["quote"], explanation=v["explanation"])
    if label in LINKING and not ids:
        res.update(status=REVIEW, explanation=f"Needs review: the verdict was {label.lower()}, but it names no finding "
                                              f"that is in the run. The model said: {v['explanation']}")
    return res


def own_quotes(finding: dict, chunks: dict) -> list[str]:
    """The quote check for each of a finding's own citations."""
    out = []
    for c in finding["citations"]:
        pages = chunks.get(c.get("doc_id") or "")
        out.append(scoring.quote_is_real(c["quote"], pages, c.get("page")) if pages and c.get("quote") else "Not checked")
    return out


def judge_leftover(finding: dict, room: str, chunks: dict, client, model: str, cfg: dict, facts: list[dict] | None = None,
                   rules: list[dict] | None = None, docs: dict | None = None) -> dict:
    pre = context.precheck(finding, room, facts, docs)
    ctx = context.block_for_finding(finding, room, facts, rules)
    message, sent = leftover_message(finding, chunks, ctx, pre, cfg["max_input_chars"])
    out = _ask(client, model, TASK_LEFTOVER, message, SCHEMA_LEFTOVER)
    mine = own_quotes(finding, chunks)
    res = {"status": REVIEW, "raw_status": "cannot_decide", "rule_ids": [], "fact_or_judgment": "", "why_it_matters": "",
           "why_it_might_not": "", "severity": "not_applicable", "quote": "", "quote_found": False, "explanation": "",
           "precheck": pre, "own_quotes": mine, "own_quotes_found": any(q in ("Real", "Partly found", "Wrong page") for q in mine),
           "sent": _audit(cfg, model, sent), "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}
    v = out["verdict"]
    if v is None:
        res["explanation"] = f"Needs review: {out['error'] or 'no usable answer'}."
        return res
    on = {r["rule_id"] for r in context.rules_on(rules)}
    found = any(scoring.quote_is_real(v["quote"], pages, None) in ("Real", "Partly found", "Wrong page")
                for pages in chunks.values()) if v["quote"].strip() else False
    res.update(status=NEW_LABELS[v["status"]], raw_status=v["status"],
               rule_ids=[r.upper() for r in dict.fromkeys(v["rule_ids"]) if r.upper() in on],
               fact_or_judgment=v["fact_or_judgment"], why_it_matters=v["why_it_matters"],
               why_it_might_not=v["why_it_might_not"], severity=v["severity"], quote=v["quote"], quote_found=found,
               explanation=v["explanation"])
    return res


# ---- the effective verdicts -----------------------------------------------------------------------------------------------

def case_verdict(check: dict, case_id: str) -> dict | None:
    """The verdict in force for a case: the manual one when there is one, otherwise the model's."""
    model = check["case_verdicts"].get(case_id)
    manual = check["manual"].get(f"case::{case_id}")
    if manual:
        return {**(model or {}), "status": manual["status"], "finding_ids": manual["finding_ids"], "manual": True,
                "note": manual["note"], "manual_case_hash": manual.get("case_hash"),
                "model_status": model["status"] if model else None}
    return {**model, "manual": False} if model else None


def linked(check: dict, case_ids: set[str] | None = None) -> dict[str, list[str]]:
    """{finding_id: [case_id, ...]} over the verdicts in force."""
    out: dict[str, list[str]] = {}
    ids = set(check["case_verdicts"]) | {k.split("::", 1)[1] for k in check["manual"] if k.startswith("case::")}
    for cid in sorted(ids):
        if case_ids is not None and cid not in case_ids:
            continue
        v = case_verdict(check, cid)
        if v and v["status"] in LINKING:
            for fid in v["finding_ids"]:
                out.setdefault(fid, []).append(cid)
    return out


def _room_cases(check: dict, cases: list[dict]) -> list[dict]:
    return [c for c in cases if c["data_room"] == check["data_room"]]


def _stale(check: dict, case: dict, facts=None, rules=None) -> bool:
    v = check["case_verdicts"].get(case["case_id"])
    return bool(v) and v.get("case_hash") != case_hash(case, context.block_for_case(case, facts, rules))


def remaining(check: dict, cases: list[dict], facts=None, rules=None) -> dict:
    """What is still to be asked: {"cases": [ids], "stale": [ids], "findings": [ids], "total"}.
    A case with a manual verdict is not asked again. Leftover findings are only known for certain once
    every case has a verdict; until then every unlinked finding is counted."""
    room_cases = _room_cases(check, cases)
    stale = [c["case_id"] for c in room_cases if _stale(check, c, facts, rules)]
    todo = [c["case_id"] for c in room_cases
            if f"case::{c['case_id']}" not in check["manual"] and (c["case_id"] not in check["case_verdicts"] or c["case_id"] in stale)]
    links = linked(check, {c["case_id"] for c in room_cases})
    left = [f["finding_id"] for f in check["findings"]
            if f["finding_id"] not in links and f["finding_id"] not in check["new_verdicts"]
            and f"finding::{f['finding_id']}" not in check["manual"]]
    return {"cases": todo, "stale": [s for s in stale if f"case::{s}" not in check["manual"]], "findings": left,
            "total": len(todo) + len(left)}


# ---- running the check --------------------------------------------------------------------------------------------------------

def run_check(check: dict, cases: list[dict], client=None, progress=None, snapshot: str | None = None,
              workers: int | None = None) -> dict:
    """Runs whatever is still open: first every case without a current verdict, then every finding that maps
    to no case, then the rule gate. Each verdict is saved as soon as it exists.

    progress(step, i, n) is called after every verdict. Returns {"asked", "left", "stopped"}; `stopped`
    holds the provider's message when a limit ended the run early."""
    cfg = settings()
    model = check["model"]
    room = check["data_room"]
    room_cases = _room_cases(check, cases)
    chunks = store.load_chunks(room)
    facts, rules, docs = context.load_facts(room), context.load_rules(), context.doc_info(room)
    todo = remaining(check, cases, facts, rules)
    out = {"asked": 0, "left": todo["total"], "stopped": None}
    if not todo["total"]:
        _gate_all(check, room_cases, rules)
        return out
    client = client or judge._client()
    index = matching.RoomIndex(room_cases)
    by_id = {c["case_id"]: c for c in room_cases}
    stop = threading.Event()
    if snapshot:
        check["snapshot"] = snapshot

    def guarded(fn, key, bucket):
        def work(item):
            if stop.is_set():
                return False
            try:
                res = fn(item)
            except JudgeQuotaReached as e:
                stop.set()
                out["stopped"] = str(e)
                return False
            except JudgeUnavailable:
                stop.set()
                raise
            with _LOCK:                       # save at once: nothing is lost if the run stops
                check[bucket][key(item)] = res
                check["input_tokens"] += res.pop("input_tokens", 0)
                check["output_tokens"] += res.pop("output_tokens", 0)
                res["at"] = _now()
                save(check)
            return True
        return work

    def run(step, items, work):
        done = 0
        with ThreadPoolExecutor(max_workers=workers or cfg["workers"]) as pool:
            for i, ok in enumerate(pool.map(work, items), start=1):
                done += bool(ok)
                if progress:
                    progress(step, i, len(items))
        return done

    todo_cases = [by_id[c] for c in todo["cases"]]
    out["asked"] += run("Cases against the run", todo_cases, guarded(
        lambda c: judge_case(c, check["findings"], rank_findings(c, check["findings"], index), chunks, client, model, cfg,
                             facts, rules), lambda c: c["case_id"], "case_verdicts"))
    if not stop.is_set():
        left = remaining(check, cases, facts, rules)
        if not left["cases"]:                 # step 2 only once every case has a verdict
            by_f = {f["finding_id"]: f for f in check["findings"]}
            out["asked"] += run("Leftover findings against the documents", [by_f[i] for i in left["findings"]], guarded(
                lambda f: judge_leftover(f, room, chunks, client, model, cfg, facts, rules, docs),
                lambda f: f["finding_id"], "new_verdicts"))
    _gate_all(check, room_cases, rules)
    out["left"] = remaining(check, cases, facts, rules)["total"]
    return out


def _gate_all(check: dict, room_cases: list[dict], rules: list[dict] | None = None) -> None:
    """Runs the rule gate over every judged leftover finding and stores the outcome with its verdict."""
    rejected = [r for r in library.load_rejected() if r.get("check_id") != check["check_id"]]
    by_f = {f["finding_id"]: f for f in check["findings"]}
    changed = False
    for fid, v in check["new_verdicts"].items():
        g = context.gate(by_f[fid], v.get("precheck"), v, check["data_room"], rules, rejected)
        if v.get("gate") != g:
            v["gate"], changed = g, True
    if changed:
        save(check)


# ---- scores -------------------------------------------------------------------------------------------------------------------------

def finding_band(check: dict, fid: str) -> tuple[str, dict]:
    """Where an unmapped finding sits: Candidate, Needs review, Rejected by rule or Rejected by evaluator,
    with its verdict. A manual verdict on the finding wins."""
    v = dict(check["new_verdicts"].get(fid) or {})
    manual = check["manual"].get(f"finding::{fid}")
    if manual:
        v.update(manual=True, note=manual["note"], model_status=v.get("status"))
        if manual["status"] == REJECTED_EVALUATOR:
            return REJECTED_EVALUATOR, v
        v["status"] = manual["status"]
        band = CANDIDATE if manual["status"] == REAL else REVIEW if manual["status"] == REVIEW else REJECTED_EVALUATOR
        return band, v
    if not v:
        return "Not checked", {"status": "Not checked"}
    return (v.get("gate") or {}).get("outcome") or REVIEW, v


def _block(rows: list[dict]) -> dict:
    points, possible = sum(r["points"] for r in rows), sum(r["weight"] for r in rows)
    crit = [r for r in rows if r["severity"] == "Critical"]
    return {"cases": len(rows), "found": sum(r["status"] == FOUND for r in rows),
            "partial": sum(r["status"] == PARTIAL for r in rows), "missed": sum(r["status"] == MISSED for r in rows),
            "open": sum(r["status"] in (REVIEW, "Not checked") for r in rows),
            "points": points, "possible": possible, "accuracy": points / possible if possible else None,
            "critical": len(crit), "critical_missed": sum(r["status"] == MISSED for r in crit)}


def results(check: dict, cases: list[dict], chunks: dict | None = None) -> dict:
    """Everything the screen and the report show: {"cases", "non_issues", "new", "metrics"}.

    cases and non_issues: one row per ground-truth case with the verdict in force. new: one row per finding
    that maps to no case, with its band. Found earns the full weight, Partially found half."""
    room_cases = _room_cases(check, cases)
    by_f = {f["finding_id"]: f for f in check["findings"]}
    rules = context.load_rules()
    rep, non = [], []
    for c in room_cases:
        v = case_verdict(check, c["case_id"]) or {"status": "Not checked", "finding_ids": [], "manual": False}
        fids = [i for i in v.get("finding_ids") or [] if i in by_f]
        stale = _stale(check, c) if not v.get("manual") else bool(v.get("manual_case_hash")) and v["manual_case_hash"] != case_hash(c, context.block_for_case(c))
        row = {"case_id": c["case_id"], "status": v["status"], "severity": c["severity"], "weight": c["weight"],
               "set": c["set"], "report": c["report"], "summary": c["summary"], "classification": c["classification"],
               "finding_ids": fids, "covered": v.get("covered") or "", "missing": v.get("missing") or "",
               "quote": v.get("quote") or "", "explanation": v.get("explanation") or "", "manual": bool(v.get("manual")),
               "note": v.get("note") or "", "model_status": v.get("model_status"), "stale": stale,
               "origin_check": c.get("origin_check"), "rule_ids": context.case_rules(c, rules)}
        if c["report"]:
            row["points"] = c["weight"] if v["status"] == FOUND else PARTIAL_CREDIT * c["weight"] if v["status"] == PARTIAL else 0
            row["classes"] = [by_f[i]["classification"] for i in fids]
            row["severities"] = [by_f[i]["severity"] for i in fids]
            row["class_correct"] = (c["classification"] in row["classes"]) if fids and v["status"] in (FOUND, PARTIAL) else None
            rep.append(row)
        else:
            non.append(row)

    links = linked(check, {c["case_id"] for c in room_cases})
    new = []
    for f in check["findings"]:
        if f["finding_id"] in links:
            continue
        band, v = finding_band(check, f["finding_id"])
        gate = v.get("gate") or {}
        new.append({"finding_id": f["finding_id"], "band": band, "status": v.get("status") or "Not checked",
                    "summary": f["summary"], "severity_given": f["severity"], "severity_judged": v.get("severity"),
                    "documents": sorted({c["doc_id"] for c in f["citations"] if c["doc_id"]}),
                    "precheck": (v.get("precheck") or {}).get("tag"), "rule_id": gate.get("rule_id"),
                    "reason": gate.get("reason") or "", "explanation": v.get("explanation") or "",
                    "manual": bool(v.get("manual")), "note": v.get("note") or "", "quote": v.get("quote") or "",
                    "quote_found": v.get("quote_found"), "rule_ids": v.get("rule_ids") or []})

    mine = {r["case_id"] for r in rep if r["origin_check"] == check["check_id"]}
    grounded_cases = {r["case_id"] for r in rep if r["status"] in (FOUND, PARTIAL)}
    grounded = sum(any(c in grounded_cases for c in cids) for cids in links.values()) + sum(n["status"] == REAL for n in new)
    by_rule: dict[str, int] = {}
    for n in new:
        if n["band"] == REJECTED_RULE:
            by_rule[n["rule_id"] or "(no rule)"] = by_rule.get(n["rule_id"] or "(no rule)", 0) + 1
    chunks = store.load_chunks(check["data_room"]) if chunks is None else chunks
    quotes = [q for f in check["findings"] for q in own_quotes(f, chunks) if q != "Not checked"]
    judged_class = [r["class_correct"] for r in rep if r["class_correct"] is not None]
    n_find = len(check["findings"])
    rejected = sum(by_rule.values())
    metrics = {
        "all": _block(rep), "withheld": _block([r for r in rep if r["set"] == "Withheld"]),
        "development": _block([r for r in rep if r["set"] == "Development"]),
        "all_before": _block([r for r in rep if r["case_id"] not in mine]), "from_this_run": len(mine),
        "findings": n_find, "grounded": grounded, "grounded_share": grounded / n_find if n_find else None,
        "new_real": sum(n["status"] == REAL for n in new), "known_change": sum(n["status"] == KNOWN for n in new),
        "not_in_documents": sum(n["status"] == NOT_IN_DOCS for n in new),
        "not_a_discrepancy": sum(n["status"] == NOT_DISC for n in new),
        "wrongly_flagged": sum(r["status"] == WRONG for r in non),
        "wrongly_flagged_rules": {r["case_id"]: r["rule_ids"] for r in non if r["status"] == WRONG},
        "rejected_by_rules": rejected, "rejected_per_rule": by_rule, "noise_share": rejected / n_find if n_find else None,
        "made_up": sum(n["band"] == REJECTED_RULE and n["status"] == NOT_IN_DOCS for n in new),
        "candidates": sum(n["band"] == CANDIDATE for n in new), "accepted": len(mine),
        "needs_review": sum(n["band"] == REVIEW for n in new),
        "rejected_by_evaluator": sum(n["band"] == REJECTED_EVALUATOR for n in new),
        "not_checked": sum(n["band"] == "Not checked" for n in new),
        "stale": sum(r["stale"] for r in rep + non),
        "class_accuracy": sum(judged_class) / len(judged_class) if judged_class else None,
        "quotes_checked": len(quotes),
        "quotes_found": sum(q != "Not found" for q in quotes) / len(quotes) if quotes else None,
    }
    return {"cases": rep, "non_issues": non, "new": new, "metrics": metrics}


def verdict_sentence(res: dict, label: str = "Vericap") -> str:
    """The result in one plain sentence, built from the numbers."""
    m, a = res["metrics"], res["metrics"]["all"]
    text = (f"{label} found {a['found']} of {a['cases']} cases fully, {a['partial']} partly and missed {a['missed']}"
            + (f", including {a['critical_missed']} Critical" if a["critical_missed"] else "") + ".")
    if a["open"]:
        text += f" {a['open']} case verdicts are still open."
    extra = []
    if m["new_real"]:
        extra.append(f"{m['new_real']} finding{'s are real issues' if m['new_real'] != 1 else ' is a real issue'} the ground truth does not have")
    if m["known_change"] + m["wrongly_flagged"]:
        n = m["known_change"] + m["wrongly_flagged"]
        extra.append(f"{n} {'were known changes or non-issues' if n != 1 else 'was a known change or non-issue'} reported as problems")
    if m["made_up"]:
        extra.append(f"{m['made_up']} could not be found in the documents")
    return text + (" " + ", and ".join(extra).capitalize() + "." if extra else "")


# ---- against the baselines ----------------------------------------------------------------------------------------------------------------

def as_contract_run(check: dict) -> dict:
    """The run in the output contract format, so the rule-based scorer and the other screens can read it."""
    meta = check.get("run_meta") or {}
    return {
        "run": {"run_id": check["label"], "data_room": check["data_room"], "source": "Our system",
                "system": str(meta.get("system") or "Vericap"), "version": str(meta.get("version") or ""),
                "model": str(meta.get("model") or ""), "notes": f"Read by the Vericap run check ({check['check_id']})."},
        "findings": [{"finding_id": f["finding_id"], "classification": f["classification"], "severity": f["severity"],
                      "summary": f["summary"], "claims_compared": f["claims_compared"],
                      "citations": [{"doc_id": c["doc_id"], "page": c["page"], "location": c["location"], "quote": c["quote"]}
                                    for c in f["citations"]],
                      "explanation": f["explanation"], "confidence": f["confidence"]} for f in check["findings"]],
    }


def baseline_comparison(check: dict, scored_runs: list[dict], cases: list[dict] | None = None) -> dict:
    """The run next to every baseline on the same data room, all scored by the same rules with no manual
    decisions for our run. Returns {"table", "rank", "runs", "baselines", "found_by", "baseline_ids"}."""
    cases = store.load_cases() if cases is None else cases
    run, problems = contract.normalise(as_contract_run(check))
    run["run"]["problems"] = problems
    ours = scoring.score_run(run, cases, {})
    base = [r for r in scored_runs if r["run"]["data_room"] == check["data_room"] and r["run"]["source"] == "Baseline model"]

    def row(res, mine=False):
        m, a = res["metrics"], res["metrics"]["all_cases"]
        return {"Run": res["run"]["run_id"], "System": "Vericap (this run)" if mine else res["run"]["system"],
                "Weighted recall, all cases (rules)": a["weighted_recall"], "Cases found": a["found"],
                "Critical missed": a["critical_missed"], "Precision": m["precision"], "Findings": m["findings"], "ours": mine}

    table = sorted([row(ours, True)] + [row(r) for r in base],
                   key=lambda r: -(r["Weighted recall, all cases (rules)"] or 0))
    found_by: dict[str, list[str]] = {}
    for r in base:
        for c in r["cases"]:
            if c["report"] and c["outcome"] == "Found":
                found_by.setdefault(c["case_id"], []).append(r["run"]["run_id"])
    return {"table": table, "rank": next(i for i, r in enumerate(table, start=1) if r["ours"]), "runs": len(table),
            "baselines": len(base), "found_by": found_by, "baseline_ids": [r["run"]["run_id"] for r in base]}


# ---- candidate review ---------------------------------------------------------------------------------------------------------------------

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
    f = next(x for x in check["findings"] if x["finding_id"] == fid)
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


def pages_sent(check: dict) -> list[dict]:
    """What left the machine: every document page sent to the model, with the provider and model."""
    seen: dict[tuple, dict] = {}
    for kind, bucket in (("case", check["case_verdicts"]), ("finding", check["new_verdicts"])):
        for key, v in bucket.items():
            s = v.get("sent") or {}
            for doc, page in s.get("pages") or []:
                row = seen.setdefault((doc, page, s.get("provider"), s.get("model")),
                                      {"doc_id": doc, "page": page, "provider": s.get("provider"), "model": s.get("model"),
                                       "calls": 0, "last_sent": s.get("at")})
                row["calls"] += 1
                row["last_sent"] = max(row["last_sent"] or "", s.get("at") or "")
    return sorted(seen.values(), key=lambda r: (r["doc_id"], r["page"] if r["page"] is not None else -1))


# ---- the written report --------------------------------------------------------------------------------------------------------------------------

def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def markdown(check: dict, res: dict, cmp: dict | None = None, snapshot_label: str = "") -> str:
    m, a = res["metrics"], res["metrics"]["all"]
    found_by, n_base = (cmp or {}).get("found_by", {}), (cmp or {}).get("baselines", 0)
    order = lambda rows: sorted(rows, key=lambda r: -r["weight"])
    L = [f"# Vericap run check: {check['label']}", "",
         f"Data room {check['data_room']}. Answer key: {snapshot_label or check.get('snapshot') or 'not recorded'}. "
         f"Model: {check['model']} via {check['provider']}. Checked {check['created_at'][:10]}.", "",
         "## Result", "", verdict_sentence(res, check["label"]), "",
         f"- Accuracy: {_pct(a['accuracy'])} ({a['points']:g} of {a['possible']:g} points). Found earns the full weight, "
         f"partially found half.",
         f"- Found {a['found']}, partially found {a['partial']}, missed {a['missed']} of {a['cases']} cases. "
         f"Critical missed: {a['critical_missed']}.",
         f"- Withheld set: {_pct(m['withheld']['accuracy'])}. Development set: {_pct(m['development']['accuracy'])}.",
         f"- Findings: {m['findings']}. Backed by the documents: {m['grounded']}. Real issues not in the ground truth: "
         f"{m['new_real']}. Not in the documents: {m['not_in_documents']}. Not discrepancies: {m['not_a_discrepancy']}. "
         f"Known changes: {m['known_change']}. Non-issues flagged as problems: {m['wrongly_flagged']}.",
         f"- Quote check: {_pct(m['quotes_found'])} of {m['quotes_checked']} quoted passages are in their document.", ""]
    if cmp:
        L += ["## Against the baselines", "",
              f"Rank {cmp['rank']} of {cmp['runs']} runs on {check['data_room']}, by the same rules for every run. "
              f"This can differ from the accuracy above, which comes from the model's verdicts.", ""]
        L += [f"- {r['Run']} ({r['System']}): weighted recall {_pct(r['Weighted recall, all cases (rules)'])}, "
              f"{r['Cases found']} cases found, {r['Critical missed']} Critical missed, precision {_pct(r['Precision'])}, "
              f"{r['Findings']} findings" for r in cmp["table"]] + [""]

    def section(title, status, extra=False):
        rows = order([r for r in res["cases"] if r["status"] == status])
        out = [f"## {title} ({len(rows)})", ""]
        for r in rows:
            text = f"- {r['case_id']} ({r['severity']}): {r['summary']}"
            if r["finding_ids"]:
                text += f" Findings: {', '.join(r['finding_ids'])}."
            if status == PARTIAL and r["missing"]:
                text += f" Left out: {r['missing']}"
            if extra and n_base:
                text += f" Found by {len(found_by.get(r['case_id'], []))} of {n_base} baselines."
            out.append(text)
        return out + ([""] if rows else ["None.", ""])

    L += section("Missed", MISSED, True) + section("Partially found", PARTIAL, True) + section("Found", FOUND)
    open_cases = [r for r in res["cases"] + res["non_issues"] if r["status"] in (REVIEW, "Not checked")]
    if open_cases:
        L += [f"## Case verdicts still open ({len(open_cases)})", ""] + [f"- {r['case_id']}: {r['status']}. {r['explanation']}" for r in open_cases] + [""]

    by_f = {f["finding_id"]: f for f in check["findings"]}
    cands = [n for n in res["new"] if n["band"] in (CANDIDATE, REJECTED_EVALUATOR)]
    L += [f"## Candidates for the ground truth ({len(cands) + m['accepted']})", ""]
    for p in [p for p in library.load_pending() if p.get("check_id") == check["check_id"] and p["kind"] == "case"]:
        L.append(f"- Accepted as {p['case_id']}: {p['case']['summary']} Reason: {p['reason']}")
    for n in cands:
        decision = f"Rejected by the evaluator. Reason: {n['note']}" if n["band"] == REJECTED_EVALUATOR else "Not decided yet."
        L.append(f"- {n['finding_id']} ({n['severity_judged'] or n['severity_given'] or 'no severity'}): {n['summary']} {decision}")
    L += ["" if cands or m["accepted"] else "None.", ""]
    L += [f"## Rejected by rules ({m['rejected_by_rules']})", ""]
    for rule, count in sorted(m["rejected_per_rule"].items()):
        L.append(f"### {context.rule_name(rule)} ({count})")
        L += [f"- {n['finding_id']}: {n['summary']} {n['reason']}" for n in res["new"] if n["band"] == REJECTED_RULE and (n["rule_id"] or "(no rule)") == rule]
        L.append("")
    review = [n for n in res["new"] if n["band"] in (REVIEW, "Not checked")]
    L += [f"## Needs review ({len(review)})", ""] + [f"- {n['finding_id']}: {n['summary']} {n['reason'] or n['explanation']}" for n in review] + [""]
    wrong = [r for r in res["non_issues"] if r["status"] == WRONG]
    L += [f"## Known non-issues flagged as problems ({len(wrong)})", ""]
    for r in wrong:
        rule = f" Rule broken: {', '.join(context.rule_name(x) for x in r['rule_ids'])}." if r["rule_ids"] else ""
        L.append(f"- {r['case_id']}: {r['summary']} Findings: {', '.join(r['finding_ids'])}.{rule}")
    L += ["", "## Answer key changes", ""]
    changes = [e for e in library.load_changelog() if e.get("origin") == check["check_id"]]
    L += [f"- {e['at'][:10]} {e['action']} {e['object']} {e['id']}: {e['reason']}" for e in changes] or ["None from this check."]
    if m["from_this_run"]:
        b = m["all_before"]
        L += ["", f"{m['from_this_run']} cases in the answer key came from this run. Without them the accuracy is "
                  f"{_pct(b['accuracy'])} ({b['points']:g} of {b['possible']:g} points)."]
    return "\n".join(L) + "\n"
