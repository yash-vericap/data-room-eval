"""One model call per case or leftover finding, and the rule checks on every answer."""
from __future__ import annotations

from .. import context, scoring
from .labels import CASE_LABELS, LINKING, NEW_LABELS, REVIEW
from .messages import case_message, focused, leftover_message
from .pages import _memo
from .prompts import SCHEMA_LEFTOVER, SCHEMA_NON_ISSUE, SCHEMA_REPORTABLE, SYSTEM, TASK_LEFTOVER, TASK_NON_ISSUE, TASK_REPORTABLE
from .storage import _now


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


def _audit(cfg: dict, model: str, sent: list, out: dict | None = None) -> dict:
    """What left the machine for one verdict: the pages, and the provider and model that actually answered."""
    out = out or {}
    return {"provider": out.get("provider") or cfg["provider"], "model": out.get("model") or model, "at": _now(), "pages": sent}


def judge_case(case: dict, findings: list[dict], ranked: list[dict], chunks: dict, client, model: str, cfg: dict,
               facts: list[dict] | None = None, rules: list[dict] | None = None) -> dict:
    full_ctx = context.block_for_case(case, facts, rules)           # what the stale check compares against
    ctx = context.block_for_case(case, facts, rules, rule_names_only=focused())
    if len(ctx) > cfg["max_input_chars"] // 2:
        ctx = context.block_for_case(case, facts, rules, max_facts=15, rule_names_only=focused())
    message, sent = case_message(case, findings, ranked, chunks, ctx, cfg["max_input_chars"])
    task, schema = (TASK_REPORTABLE, SCHEMA_REPORTABLE) if case["report"] else (TASK_NON_ISSUE, SCHEMA_NON_ISSUE)
    tin = tout = 0
    v, reason, out = None, None, {}
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
           "explanation": "", "case_hash": case_hash(case, full_ctx), "sent": _audit(cfg, model, sent, out),
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
        out.append(_memo(("quote", id(pages), c.get("doc_id"), c.get("page"), c.get("quote")),
                         lambda: scoring.quote_is_real(c["quote"], pages, c.get("page"))) if pages and c.get("quote") else "Not checked")
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
           "sent": _audit(cfg, model, sent, out), "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"]}
    v = out["verdict"]
    if v is None:
        res["explanation"] = f"Needs review: {out['error'] or 'no usable answer'}."
        return res
    on = {r["rule_id"] for r in context.rules_on(rules)}
    found = bool(v["quote"].strip()) and (_shown(v["quote"], message) or any(      # the pages it was shown first
        scoring.quote_is_real(v["quote"], pages, None) in ("Real", "Partly found", "Wrong page") for pages in chunks.values()))
    res.update(status=NEW_LABELS[v["status"]], raw_status=v["status"],
               rule_ids=[r.upper() for r in dict.fromkeys(v["rule_ids"]) if r.upper() in on],
               fact_or_judgment=v["fact_or_judgment"], why_it_matters=v["why_it_matters"],
               why_it_might_not=v["why_it_might_not"], severity=v["severity"], quote=v["quote"], quote_found=found,
               explanation=v["explanation"])
    return res
