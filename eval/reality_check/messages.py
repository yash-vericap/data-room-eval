"""The message for one case or one leftover finding, cut to fit the model's input limit."""
from __future__ import annotations

import os

from .. import matching
from .pages import _best_pages, _page_of, _pages_block


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


def focused() -> bool:
    """On (the default): a case is only shown the findings related to it, and a case with no related finding
    is decided by rule with no model call. EVAL_RC_FOCUS=0 shows every finding for every case."""
    return (os.environ.get("EVAL_RC_FOCUS") or "1").strip() != "0"


def min_relevance() -> float:
    """How related a finding must be to be shown for a case. Every finding-to-case link decided by hand in
    the baseline runs scores 0.31 or more, so 0.20 keeps them all with room to spare."""
    try:
        return float(os.environ.get("EVAL_RC_MIN_RELEVANCE") or (0.20 if focused() else 0.05))
    except ValueError:
        return 0.20


def rank_findings(case: dict, findings: list[dict], index: matching.RoomIndex) -> list[dict]:
    """The findings most likely to be about a case, best first."""
    case_tok = set(index.case_tokens[case["case_id"]])
    floor = min_relevance()
    scored = []
    for f in findings:
        s = index.score(f, case)["score"]
        if s == 0 and case_tok:          # no shared document: fall back to shared wording, at half weight
            tok = set(matching.tokens(" ".join([f["summary"], f["claims_compared"], f["explanation"]])))
            s = 0.5 * len(tok & case_tok) / len(case_tok)
        if s > floor:
            scored.append((s, f))
    return [f for _, f in sorted(scored, key=lambda t: -t[0])]


CASE_LEVELS = [(None, 8, None), (1200, 6, None), (600, 5, None), (300, 4, 40), (150, 3, 20)]   # radius, in full, listed
LEFTOVER_LEVELS = [None, 1500, 700, 300]


def case_message(case: dict, findings: list[dict], ranked: list[dict], chunks: dict, ctx: str, max_chars: int,
                 focus: bool | None = None) -> tuple[str, list]:
    """The message for one case, cut to fit max_chars. The context block is never cut. With focus, only the
    findings related to the case are shown; otherwise the others follow in short."""
    focus = focused() if focus is None else focus
    head = ["<ground_truth_case>", f"ID: {case['case_id']}", f"Expected class: {case['classification']}",
            f"Severity: {case['severity']}", f"Should be reported as a problem: {'yes' if case['report'] else 'no'}",
            f"Summary: {case['summary']}", f"Claims compared: {case['claims_compared']}", "Citations:",
            "\n".join(f"- {c['raw']}" for c in case["citations"]) or "- (none)",
            f"Correct interpretation: {case['explanation']}"]
    if case.get("alternative_readings"):
        head.append(f"Alternative readings: {case['alternative_readings']}")
    head += ["</ground_truth_case>", "", ctx, ""]
    pool = ranked if focus else findings
    unrelated = len(findings) - len(ranked) if focus else 0
    message, sent = "", []
    for radius, n_full, n_listed in CASE_LEVELS:
        pages, sent = _pages_block(case["citations"], chunks, radius)
        full = ranked[:n_full]
        full_ids = {f["finding_id"] for f in full}
        rest = [f for f in pool if f["finding_id"] not in full_ids]
        listed = rest if n_listed is None else rest[:max(0, n_listed - len(full))]
        parts = head + ["<cited_pages>", pages, "</cited_pages>", "", f"<run_findings count=\"{len(findings)}\">"]
        parts += [_finding_full(f) for f in full] or ["No finding of the run shares a document or wording with this case."]
        if listed:
            parts += ["", ("Other related findings" if focus else "Other findings of the run") + ", in short (ID | class | severity | summary | documents):"]
            parts += [_finding_short(f) for f in listed]
        if len(rest) > len(listed):
            parts.append(f"{len(rest) - len(listed)} more findings of the run are left out to keep this message short.")
        if unrelated:
            parts.append(f"{unrelated} other findings of the run share no document, figure or wording with this case "
                         f"and are not shown.")
        parts += ["</run_findings>", "", "Return your verdict."]
        message = "\n".join(parts)
        if len(message) <= max_chars:
            break
    return message, sent


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
