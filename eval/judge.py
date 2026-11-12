"""Approach B: the LLM judge.

For every finding the judge sees only three things: the finding, the answer-key cases the rules
consider closest, and the cited passages. It returns a fixed-structure verdict: does the finding
match a case, is the class right, is the evidence sufficient, a reasoning score of 0 to 2, the exact
passage it relies on and one line of explanation. That is the same set of columns the evaluator
filled in by hand for the baseline runs.

Safeguards, as in the methodology:
- Every verdict must quote a passage. The quote is checked by rule against the material the judge
  was shown. A verdict whose quote cannot be found is thrown out and asked once more; if it fails
  again the finding goes to manual review.
- Every finding is judged twice. If the two verdicts differ, the finding is marked unstable.
- The judge may answer "cannot decide", and may disagree with the answer key. Both go to manual review.
- A judge verdict never changes the headline score. Judge scores are shown next to the rule scores.

The judge runs on GitHub Models (eval/providers.py), with the token in GITHUB_MODELS_TOKEN, read
from the environment or the .env file.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import contract, matching, scoring, store
from .providers import ChatClient, JudgeQuotaReached, JudgeUnavailable, family, settings

PROMPT_VERSION = "J-v1"
VERDICTS = store.DATA / "judge" / "verdicts.json"
CANDIDATES = 3

SYSTEM = """You are an independent reviewer checking the output of an AI system that looks for discrepancies in a deal data room. An evaluator wrote an answer key of cases by hand. Your job is to compare one finding from the AI system with the answer-key cases shown to you and return a verdict. Your verdict is used to score the system, so accuracy matters more than agreeableness: a confident, well-written finding can still be wrong.

What you may use
- Only the finding, the candidate cases and the passages in the message. Do not use outside knowledge, and do not assume what other documents might say.
- If the material does not settle a question, answer cannot_decide for that field. That is a valid answer and is better than a guess.

How to decide each field
- match: "yes" when the finding is about the same underlying issue as a candidate case: the same facts, in the same documents, in conflict for the same reason. Different wording is fine. Sharing a document or a figure is not enough on its own. "no" when it is about none of the candidates.
- case_ids: the case or cases the finding matches. Usually one. Give two only when the finding clearly merges two separate cases. Empty when match is not "yes". Use only IDs from the candidates.
- class_correct: "yes" when the finding's classification equals the matched case's classification. With no match, "not_applicable".
- evidence: "Sufficient" when the finding cites every passage needed to support its conclusion, "Partial" when it cites only one side or leaves out a passage the conclusion needs, "Not supported" when the cited passages do not support the conclusion.
- reasoning_score: "2" when the explanation follows cleanly from the cited evidence. "1" when it reaches a broadly right conclusion but misreads a date, unit, amount or condition, or cites a wrong rule. "0" when it contradicts the evidence or rests on assumptions the evidence does not support.
- disagrees_with_answer_key: "yes" only when the passages in front of you show that the matched case's expected answer is wrong. Name the passage in the quote field.
- quote: the passage your verdict relies on most, copied character for character from the material in the message. It is checked automatically; a quote that cannot be found voids the verdict.
- explanation: one sentence that says why, referring to the quoted passage."""

SCHEMA = {
    "type": "object",
    "properties": {
        "match": {"type": "string", "enum": ["yes", "no", "cannot_decide"]},
        "case_ids": {"type": "array", "items": {"type": "string"}},
        "class_correct": {"type": "string", "enum": ["yes", "no", "not_applicable", "cannot_decide"]},
        "evidence": {"type": "string", "enum": ["Sufficient", "Partial", "Not supported", "cannot_decide"]},
        "reasoning_score": {"type": "string", "enum": ["0", "1", "2", "cannot_decide"]},
        "disagrees_with_answer_key": {"type": "string", "enum": ["no", "yes"]},
        "quote": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["match", "case_ids", "class_correct", "evidence", "reasoning_score", "disagrees_with_answer_key",
                 "quote", "explanation"],
    "additionalProperties": False,
}
KEY_FIELDS = ["match", "case_ids", "class_correct", "evidence", "reasoning_score", "disagrees_with_answer_key"]


def credentials_present() -> bool:
    return not settings()["problem"]


def judge_label() -> str:
    cfg = settings()
    return cfg["problem"] or f"{cfg['model']} via {cfg['provider']}" + (" (free tier)" if cfg["free"] else " (local)")


def _client():
    cfg = settings()
    if cfg["problem"]:
        raise JudgeUnavailable(cfg["problem"])
    return ChatClient(cfg)


# ---- what the judge is shown ----------------------------------------------------------------------

def _cits(cits: list[dict]) -> str:
    return "\n".join(f"- {c['raw']}" for c in cits) or "- (none)"


def _excerpt(text: str, quote: str, radius: int) -> str:
    """The part of a page around the quoted words, for models with a small input limit."""
    words = [w for w in quote.split() if len(w) > 3][:4]
    low = text.lower()
    at = next((low.find(w.lower()) for w in words if w.lower() in low), 0)
    start, end = max(0, at - radius), min(len(text), at + radius)
    return ("... " if start else "") + text[start:end] + (" ..." if end < len(text) else "")


def build_message(finding: dict, cands: list[dict], chunks: dict, max_chars: int = 400000) -> tuple[str, str]:
    """Returns (the user message, all quotable material as one text for the quote check).
    When the full cited pages would make the message longer than max_chars, each page is cut to an
    excerpt around the quoted words, and the message says so."""
    for radius in (None, 900, 400, 150):
        message, material = _build(finding, cands, chunks, radius)
        if len(message) <= max_chars:
            break
    return message, material


def _build(finding: dict, cands: list[dict], chunks: dict, radius: int | None) -> tuple[str, str]:
    parts = ["<finding>",
             f"ID: {finding['finding_id']}", f"Classification: {finding['classification']}",
             f"Severity: {finding['severity']}", f"Summary: {finding['summary']}",
             f"Claims compared: {finding['claims_compared']}", "Citations:", _cits(finding["citations"]),
             f"Explanation: {finding['explanation']}", "</finding>", "", "<candidate_cases>"]
    for c in cands:
        parts += [f'<case id="{c["case_id"]}">', f"Classification: {c['classification']}", f"Severity: {c['severity']}",
                  f"Should be reported as a discrepancy: {'yes' if c['report'] else 'no'}", f"Summary: {c['summary']}",
                  f"Claims compared: {c['claims_compared']}", "Supporting passages:", _cits(c["citations"]),
                  f"Correct reading: {c['explanation']}"]
        if c.get("alternative_readings"):
            parts.append(f"Alternative readings: {c['alternative_readings']}")
        parts.append("</case>")
    if not cands:
        parts.append("(No answer-key case shares a document with this finding.)")
    parts += ["</candidate_cases>", "", "<cited_passages>"]
    pages = []
    for c in finding["citations"]:
        text = (chunks.get(c["doc_id"] or "") or {}).get(c["page"])
        if text and (radius is not None or (c["doc_id"], c["page"]) not in [p[:2] for p in pages]):
            pages.append((c["doc_id"], c["page"], text.strip() if radius is None else _excerpt(text.strip(), c["quote"], radius)))
    if pages:
        if radius is not None:
            parts.append("Each block below is an excerpt of the cited page around the quoted words, not the whole page.")
        parts += [f'<page doc="{d}" page="{p}">\n{t}\n</page>' for d, p, t in pages]
    else:
        parts.append("The document text is not stored. The only passages available are the quotes in the finding's "
                     "citations and in the cases' supporting passages above. You cannot confirm that a quote really "
                     "appears in its document; judge on the quotes as given.")
    parts += ["</cited_passages>", "", "Return your verdict."]
    material = "\n".join([c["quote"] for c in finding["citations"]] + [finding["claims_compared"], finding["summary"]]
                         + [x["quote"] for c in cands for x in c["citations"]] + [c["claims_compared"] for c in cands]
                         + [t for _, _, t in pages])
    return "\n".join(parts), material


# ---- one call, one finding ------------------------------------------------------------------------

def _call(client, model: str, message: str) -> dict:
    """One judge call. Returns {"verdict": dict | None, "error": str | None, "input_tokens", "output_tokens"}."""
    return client.complete(model, SYSTEM, message, SCHEMA)


def _check(verdict: dict, cand_ids: set[str], material: str) -> str | None:
    """Rule check on one verdict. Returns the reason it is void, or None when it stands."""
    bad = [c for c in verdict["case_ids"] if c not in cand_ids]
    if bad:
        return f"names a case that was not shown: {', '.join(bad)}"
    if verdict["match"] == "yes" and not verdict["case_ids"]:
        return "says it matches but names no case"
    if scoring.quote_is_real(verdict["quote"], {1: material}, 1) != "Real":
        return "its quote is not in the material it was shown"
    return None


def _one_pass(client, model, message, cand_ids, material) -> dict:
    """A verdict, asked again once if it fails the rule check."""
    tokens_in = tokens_out = 0
    reason = None
    for attempt in (1, 2):
        out = _call(client, model, message)
        tokens_in, tokens_out = tokens_in + out["input_tokens"], tokens_out + out["output_tokens"]
        if out["verdict"] is None:
            reason = out["error"]
            continue
        v = out["verdict"]
        if v["match"] != "yes":
            v["case_ids"] = []
        reason = _check(v, cand_ids, material)
        if reason is None:
            return {"verdict": v, "void": None, "attempts": attempt, "input_tokens": tokens_in, "output_tokens": tokens_out}
    return {"verdict": out["verdict"], "void": reason, "attempts": 2, "input_tokens": tokens_in, "output_tokens": tokens_out}


def judge_finding(finding: dict, cands: list[dict], chunks: dict, run_info: dict, client, model: str,
                  passes: int = 2, max_chars: int = 400000) -> dict:
    message, material = build_message(finding, cands, chunks, max_chars)
    cand_ids = {c["case_id"] for c in cands}
    first = _one_pass(client, model, message, cand_ids, material)
    second = _one_pass(client, model, message, cand_ids, material) if passes >= 2 and not first["void"] else None
    reasons = []
    if first["void"]:
        reasons.append(f"Verdict void: {first['void']}")
    elif second and second["void"]:
        reasons.append(f"Second verdict void: {second['void']}")
    stable = None
    if second and not first["void"] and not second["void"]:
        a, b = first["verdict"], second["verdict"]
        changed = [k for k in KEY_FIELDS if (sorted(a[k]) if k == "case_ids" else a[k]) != (sorted(b[k]) if k == "case_ids" else b[k])]
        stable = not changed
        if changed:
            reasons.append("Unstable: the two verdicts differ on " + ", ".join(changed))
    v = first["verdict"] if not first["void"] else None
    if v:
        if "cannot_decide" in (v["match"], v["class_correct"], v["evidence"], v["reasoning_score"]):
            reasons.append("The judge could not decide")
        if v["disagrees_with_answer_key"] == "yes":
            reasons.append("The judge disagrees with the answer key")
    judge_family = family(model)
    if judge_family and judge_family == family(str(run_info.get("system", "")) + " " + str(run_info.get("model", ""))):
        reasons.append("The run comes from the same model family as the judge")
    return {
        "run_id": run_info["run_id"], "finding_id": finding["finding_id"], "model": model, "prompt_version": PROMPT_VERSION,
        "candidates": sorted(cand_ids), "verdict": v, "second_verdict": second["verdict"] if second and not second["void"] else None,
        "stable": stable, "quote_verified": v is not None, "needs_manual": bool(reasons), "reasons": reasons,
        "document_text_shown": ("excerpts" if "excerpt of the cited page" in message else "pages") if "<page doc=" in message else "none",
        "passes": 2 if second else 1,
        "input_tokens": first["input_tokens"] + (second["input_tokens"] if second else 0),
        "output_tokens": first["output_tokens"] + (second["output_tokens"] if second else 0),
        "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---- whole runs -----------------------------------------------------------------------------------

def load_verdicts() -> dict[str, dict]:
    return store._read(VERDICTS, {})


def judge_run(run: dict, cases: list[dict] | None = None, *, client=None, model: str | None = None, force: bool = False,
              limit: int | None = None, workers: int | None = None, progress=None) -> dict:
    """Judges every finding of a run that has no verdict yet (all of them with force=True) and stores
    each verdict as soon as it exists, so a run stopped by a free-tier limit can be continued later.
    Returns {"judged", "skipped", "left", "stopped", "needs_manual", "input_tokens", "output_tokens", "cost"}."""
    cases = store.load_cases() if cases is None else cases
    cfg = settings()
    model = model or cfg["model"] or "unset"
    info = run["run"]
    room_cases = [c for c in cases if c["data_room"] == info["data_room"]]
    by_id = {c["case_id"]: c for c in room_cases}
    chunks = store.load_chunks(info["data_room"])
    verdicts = load_verdicts()
    todo = [f for f in run["findings"]
            if force or (v := verdicts.get(store.review_key(info["run_id"], f["finding_id"]))) is None
            or v.get("prompt_version") != PROMPT_VERSION or v.get("model") != model]
    skipped = len(run["findings"]) - len(todo)
    todo = todo[:limit] if limit else todo
    out = {"judged": 0, "skipped": skipped, "left": 0, "stopped": None, "needs_manual": 0, "input_tokens": 0,
           "output_tokens": 0, "cost": "nothing to judge"}
    if not todo:
        return out
    client = client or _client()
    index = matching.RoomIndex(room_cases)
    stop, lock = threading.Event(), threading.Lock()

    def work(f):
        if stop.is_set():
            return None
        scored = sorted(((index.score(f, c)["score"], c["case_id"]) for c in room_cases), reverse=True)
        cands = [by_id[cid] for s, cid in scored[:CANDIDATES] if s > 0]
        try:
            res = judge_finding(f, cands, chunks, info, client, model, cfg["passes"], cfg["max_input_chars"])
        except JudgeQuotaReached as e:
            stop.set()
            out["stopped"] = str(e)
            return None
        except JudgeUnavailable:
            stop.set()                               # no point sending the remaining findings
            raise
        with lock:                                   # save at once: nothing judged is lost if the run stops
            saved = load_verdicts()
            saved[store.review_key(res["run_id"], res["finding_id"])] = res
            store._write(VERDICTS, saved)
        return res

    done = []
    with ThreadPoolExecutor(max_workers=workers or cfg["workers"]) as pool:
        for i, res in enumerate(pool.map(work, todo), start=1):
            if res:
                done.append(res)
            if progress:
                progress(i, len(todo))
    tin, tout = sum(d["input_tokens"] for d in done), sum(d["output_tokens"] for d in done)
    out.update(judged=len(done), left=len(todo) - len(done), needs_manual=sum(d["needs_manual"] for d in done),
               input_tokens=tin, output_tokens=tout, cost="free tier" if cfg["free"] else "not priced")
    return out


# ---- judge verdicts as a scoring, and the comparison with rules and manual decisions ------------------

def as_decisions(run: dict, verdicts: dict) -> dict[str, dict]:
    """Judge verdicts for one run in the same shape as manual decisions, so the same scoring code
    produces the approach B result. Findings the judge has not judged are left to the rules."""
    rid = run["run"]["run_id"]
    out, taken = {}, set()
    for f in run["findings"]:
        key = store.review_key(rid, f["finding_id"])
        jv = verdicts.get(key)
        if not jv:
            continue
        v = jv["verdict"]
        if v is None or v["match"] == "cannot_decide":
            status, ids = "Needs review", []
        elif v["match"] == "yes":
            ids = list(v["case_ids"])
            status = "Duplicate" if all(c in taken for c in ids) else "Match"
            taken.update(ids)
        else:
            status, ids = "False positive candidate", []
        out[key] = {"status": status, "case_ids": ids,
                    "evidence": v["evidence"] if v and v["evidence"] != "cannot_decide" else None,
                    "reasoning": int(v["reasoning_score"]) if v and v["reasoning_score"].isdigit() else None,
                    "note": ("Judge: " + v["explanation"]) if v else "Judge: " + "; ".join(jv["reasons"])}
    return out


def _links(rows: list[dict]) -> dict[str, tuple[str, frozenset]]:
    out = {}
    for r in rows:
        status, ids = out.get(r["finding_id"], (r["status"], frozenset()))
        if r["status"] in ("Match", "Duplicate") and r["case_id"]:
            ids = ids | {r["case_id"]}
        out[r["finding_id"]] = (status, ids)
    return out


def compare_run(run: dict, cases: list[dict], reviews: dict, verdicts: dict) -> dict:
    """Rules alone, judge alone and the manual decisions, finding by finding, for one run."""
    rid = run["run"]["run_id"]
    room_cases = [c for c in cases if c["data_room"] == run["run"]["data_room"]]
    rules = _links(matching.match_run(run["findings"], room_cases, {}, rid))
    judged = as_decisions(run, verdicts)
    rows = []
    for f in run["findings"]:
        key = store.review_key(rid, f["finding_id"])
        jd, jv, mv = judged.get(key), verdicts.get(key), reviews.get(key)
        r_status, r_ids = rules[f["finding_id"]]
        j_ids = frozenset(jd["case_ids"]) if jd else None
        m_ids = frozenset(mv.get("case_ids") or []) if mv and mv["status"] != "Needs review" else None

        def same(a, b):
            return (not a and not b) or (bool(a & b) and (a <= b or b <= a))

        rows.append({
            "finding_id": f["finding_id"], "summary": f["summary"],
            "rules_status": r_status, "rules_cases": ", ".join(sorted(r_ids)),
            "judge_status": jd["status"] if jd else "(not judged)", "judge_cases": ", ".join(sorted(j_ids or [])),
            "manual_status": mv["status"] if mv else "", "manual_cases": ", ".join(sorted(m_ids or [])),
            "agree": None if j_ids is None or r_status == "Needs review" or jd["status"] == "Needs review" else same(r_ids, j_ids),
            "rules_right": None if m_ids is None or r_status == "Needs review" else same(r_ids, m_ids),
            "judge_right": None if m_ids is None or j_ids is None or jd["status"] == "Needs review" else same(j_ids, m_ids),
            "judge_evidence": jd["evidence"] if jd else None, "manual_evidence": mv.get("evidence") if mv else None,
            "judge_reasoning": jd["reasoning"] if jd else None, "manual_reasoning": mv.get("reasoning") if mv else None,
            "needs_manual": bool(jv and jv["needs_manual"]), "reasons": "; ".join(jv["reasons"]) if jv else "",
            "stable": jv["stable"] if jv else None,
            "judge_quote": jv["verdict"]["quote"] if jv and jv["verdict"] else "",
            "judge_explanation": jv["verdict"]["explanation"] if jv and jv["verdict"] else "",
        })
    return {"rows": rows, "judged": sum(r["judge_status"] != "(not judged)" for r in rows), "findings": len(rows)}


def trust(runs: list[dict], cases: list[dict], reviews: dict, verdicts: dict) -> dict:
    """The numbers that say how far the judge can be relied on, over every judged finding."""
    rows = [r for run in runs for r in compare_run(run, cases, reviews, verdicts)["rows"] if r["judge_status"] != "(not judged)"]

    def rate(vals):
        vals = [v for v in vals if v is not None]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)

    ev = [(r["judge_evidence"] == r["manual_evidence"]) for r in rows if r["judge_evidence"] and r["manual_evidence"]]
    rs = [(r["judge_reasoning"] == r["manual_reasoning"]) for r in rows
          if r["judge_reasoning"] is not None and r["manual_reasoning"] is not None]
    both = [r for r in rows if r["judge_right"] is not None and r["rules_right"] is not None]
    return {
        "judged": len(rows),
        "rules_and_judge_agree": rate([r["agree"] for r in rows]),
        "judge_matches_manual": rate([r["judge_right"] for r in rows]),
        "rules_match_manual_same_findings": rate([r["rules_right"] for r in both]),
        "evidence_matches_manual": rate(ev), "reasoning_matches_manual": rate(rs),
        "unstable": sum(r["stable"] is False for r in rows),
        "needs_manual": sum(r["needs_manual"] for r in rows),
        "only_judge_right": sum(r["judge_right"] and not r["rules_right"] for r in both),
        "only_rules_right": sum(r["rules_right"] and not r["judge_right"] for r in both),
    }


def score_run(run: dict, cases: list[dict], verdicts: dict | None = None) -> dict | None:
    """The approach B result for one run, or None when the judge has not seen any of its findings."""
    verdicts = load_verdicts() if verdicts is None else verdicts
    decisions = as_decisions(run, verdicts)
    if not decisions:
        return None
    run = {**run, "run": {**run["run"], "problems": run.get("problems", [])}}
    return scoring.score_run(run, cases, decisions)
