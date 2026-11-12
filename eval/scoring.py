"""Scores one run against the answer key: matching, evidence checks and every metric."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from . import contract, matching, store

# ---- evidence -------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9$%.]+", " ", text).strip()


def _in_order(q: list[str], t: list[str], extra: int = 4) -> bool:
    """True when the quote's words appear in the text in order with at most `extra` other words in
    between. Covers table rows, where a quote skips a column ("Windows ... Yes $1,240,000")."""
    if len(q) < 3:
        return False
    for start in (i for i, w in enumerate(t) if w == q[0]):
        j, k = start, 0
        while j < len(t) and k < len(q) and j - start <= len(q) + extra:
            if t[j] == q[k]:
                k += 1
            j += 1
        if k == len(q):
            return True
    return False


_SPLIT = re.compile(r"""\s*(?:\.\.\.|\u2026|\|)\s*|['"\u2019\u201d]\s*(?:;|,|and|\+|/)?\s*['"\u2018\u201c]|\s*\[[^\]]*\]\s*""")


def quote_is_real(quote: str, doc_pages: dict, page) -> str:
    """Checks a quoted passage against the stored text of the cited document.

    A citation often strings several fragments together ('a'; 'b', or a ... b), so the quote is cut
    into fragments and each is looked for on the cited page or one page either side, allowing a few
    wrong characters for scanned pages and skipped columns in table rows.
    'Real': every fragment found there. 'Partly found': some were. 'Wrong page': found, but
    elsewhere in the document. 'Not found': no fragment is anywhere in the document."""
    fragments = [f for f in (_norm(x) for x in _SPLIT.split(quote or "")) if len(f) >= 4]
    if not fragments:
        return "Not checked"

    def found(q: str, text: str) -> bool:
        if q in text or _in_order(q.split(), text.split()):
            return True
        if len(q) > 400 or len(q) < 12 or not text:
            return False
        window, step = len(q) + 10, max(1, len(q) // 4)
        return max((SequenceMatcher(None, q, text[i:i + window], autojunk=False).ratio()
                    for i in range(0, max(1, len(text) - len(q) + 1), step)), default=0.0) >= 0.90

    near = " ".join(_norm(doc_pages[p]) for p in doc_pages if page is None or p is None or abs(p - page) <= 1)
    hits = [found(f, near) for f in fragments]
    if all(hits):
        return "Real"
    whole = " ".join(_norm(t) for t in doc_pages.values())
    anywhere = [h or found(f, whole) for h, f in zip(hits, fragments)]
    if all(anywhere):
        return "Wrong page" if not any(hits) else "Partly found"
    return "Partly found" if any(anywhere) else "Not found"


def check_evidence(finding: dict, case: dict | None, chunks: dict) -> dict:
    """Real (needs stored document text), relevant and sufficient, by rule.

    Relevant: share of the finding's citations that point at a page the answer key cites for the case.
    Sufficient: every document the case rests on is cited. One side of a contradiction is 'Partial'.
    """
    cits = finding["citations"]
    real = []
    for c in cits:
        pages = chunks.get(c["doc_id"] or "")
        real.append(quote_is_real(c["quote"], pages, c["page"]) if pages and c["quote"] else "Not checked")
    checked = [r for r in real if r != "Not checked"]
    out = {"real": real, "real_share": (sum(r == "Real" for r in checked) / len(checked)) if checked else None,
           "invented": sum(r == "Not found" for r in real), "relevant_share": None, "sufficient": None}
    if case:
        case_pages = {(c["doc_id"], c["page"]) for c in case["citations"]}
        case_docs = set(case.get("documents") or []) | {c["doc_id"] for c in case["citations"]}
        hits = [((c["doc_id"], c["page"]) in case_pages) or (c["page"] is None and c["doc_id"] in case_docs) for c in cits]
        out["relevant_share"] = sum(hits) / len(hits) if hits else 0.0
        cited = {c["doc_id"] for c in cits}
        covered = len(case_docs & cited)
        out["sufficient"] = "Sufficient" if covered == len(case_docs) else ("Partial" if covered else "Not supported")
    return out


# ---- one run --------------------------------------------------------------------------------------

def _rate(n, d):
    return n / d if d else None


def score_run(run: dict, all_cases: list[dict], reviews: dict | None = None, chunks: dict | None = None) -> dict:
    """Returns {"run", "rows", "cases", "metrics", "problems"} for one run.

    rows:  one per finding-to-case link, with the match, class, severity and evidence results.
    cases: one per answer-key case of the run's data room, with its outcome for this run.
    """
    info, findings = run["run"], run["findings"]
    room = info["data_room"]
    cases = [c for c in all_cases if c["data_room"] == room]
    by_case = {c["case_id"]: c for c in cases}
    by_finding = {f["finding_id"]: f for f in findings}
    chunks = store.load_chunks(room) if chunks is None else chunks
    links = matching.match_run(findings, cases, reviews if reviews is not None else store.load_reviews(), info["run_id"])

    rows = []
    for link in links:
        f, case = by_finding[link["finding_id"]], by_case.get(link["case_id"])
        ev = check_evidence(f, case, chunks)
        rows.append({
            **link,
            "classification": f["classification"], "severity": f["severity"], "summary": f["summary"],
            "confidence": f["confidence"],
            "expected_class": case["classification"] if case else None,
            "expected_severity": case["severity"] if case else None,
            "case_report": case["report"] if case else None,
            "case_set": case["set"] if case else None,
            "case_weight": case["weight"] if case else None,
            "case_ambiguous": case["ambiguous"] if case else None,
            "class_correct": (f["classification"] == case["classification"]) if case else None,
            "severity_correct": (f["severity"] == case["severity"]) if case else None,
            "evidence_rule": ev["sufficient"], "evidence": link["evidence_manual"] or ev["sufficient"],
            "relevant_share": ev["relevant_share"], "real_share": ev["real_share"], "invented": ev["invented"],
            "real": ev["real"],
        })

    matched = [r for r in rows if r["status"] == "Match" and r["case_id"]]
    best_for_case = {}
    for r in matched:
        best_for_case.setdefault(r["case_id"], r)

    case_rows = []
    for c in cases:
        r = best_for_case.get(c["case_id"])
        if c["report"]:
            outcome = "Found" if r else "Missed"
        else:
            outcome = "Correct" if (r is None or r["class_correct"]) else "False alarm"
        case_rows.append({
            "case_id": c["case_id"], "expected_class": c["classification"], "expected_severity": c["severity"],
            "weight": c["weight"], "report": c["report"], "set": c["set"], "ambiguous": c["ambiguous"],
            "summary": c["summary"], "check_type": c["check_type"], "scenario_tags": c["scenario_tags"],
            "documents": c["documents"], "outcome": outcome,
            "finding_id": r["finding_id"] if r else None, "class": r["classification"] if r else None,
            "severity": r["severity"] if r else None, "class_correct": r["class_correct"] if r else None,
            "severity_correct": r["severity_correct"] if r else None, "evidence": r["evidence"] if r else None,
            "reasoning": r["reasoning"] if r else None, "points": (c["weight"] if r else 0) if c["report"] else None,
        })

    return {"run": info, "rows": rows, "cases": case_rows, "problems": run.get("problems", []),
            "metrics": _metrics(info, findings, rows, case_rows)}


def _metrics(info, findings, rows, case_rows) -> dict:
    status = {}
    for r in rows:                                    # one status per finding (first row carries it)
        status.setdefault(r["finding_id"], r["status"])
    counted = [fid for fid, s in status.items() if s != "Duplicate"]
    matched = [r for r in rows if r["status"] == "Match" and r["case_id"]]

    def is_valid(r):                                  # reportable case found, or a negative case labelled correctly
        return r["case_report"] or r["class_correct"]

    valid = {r["finding_id"] for r in matched if is_valid(r)}
    false_alarm = {r["finding_id"] for r in matched if not is_valid(r)} - valid
    fp_candidates = [fid for fid, s in status.items() if s == "False positive candidate"]
    needs_review = [fid for fid, s in status.items() if s == "Needs review"]

    def detection(scope):
        rep = [c for c in case_rows if c["report"] and scope(c)]
        found = [c for c in rep if c["outcome"] == "Found"]
        w_all, w_found = sum(c["weight"] for c in rep), sum(c["weight"] for c in found)
        crit = [c for c in rep if c["expected_severity"] == "Critical"]
        return {
            "reportable": len(rep), "found": len(found), "recall": _rate(len(found), len(rep)),
            "weighted_found": w_found, "weighted_possible": w_all, "weighted_recall": _rate(w_found, w_all),
            "critical": len(crit), "critical_missed": sum(c["outcome"] == "Missed" for c in crit),
            "missed_ids": [c["case_id"] for c in rep if c["outcome"] == "Missed"],
        }

    withheld = detection(lambda c: c["set"] == "Withheld")
    reasoning = [r["reasoning"] for r in matched if r["reasoning"] is not None]
    evidence = Counter(r["evidence"] for r in matched if r["evidence"])
    real = [r["real_share"] for r in rows if r["real_share"] is not None]
    n_valid = len(valid)
    cost, minutes = info.get("cost_usd"), info.get("duration_minutes")
    return {
        "findings": len(counted), "findings_submitted": len(findings),
        "duplicates": sum(s == "Duplicate" for s in status.values()),
        "needs_review": len(needs_review), "manual_decisions": sum(r["decided"] == "manual" for r in rows),
        # headline: withheld set
        **{k: withheld[k] for k in ("reportable", "found", "recall", "weighted_found", "weighted_possible",
                                    "weighted_recall", "critical_missed")},
        "missed": withheld["missed_ids"],
        "development": detection(lambda c: c["set"] == "Development"),
        "all_cases": detection(lambda c: True),
        "withheld_clear_cases": detection(lambda c: c["set"] == "Withheld" and not c["ambiguous"]),
        "withheld_ambiguous_cases": detection(lambda c: c["set"] == "Withheld" and c["ambiguous"]),
        "precision": _rate(n_valid, len(counted)),
        "false_positives": len(fp_candidates) + len(false_alarm),
        "false_positive_candidates": fp_candidates, "false_alarms_on_negative_cases": sorted(false_alarm),
        "negative_cases": sum(not c["report"] for c in case_rows),
        "negative_cases_false_alarm": sum(c["outcome"] == "False alarm" for c in case_rows),
        "class_accuracy": _rate(sum(bool(r["class_correct"]) for r in matched), len(matched)),
        "severity_accuracy": _rate(sum(bool(r["severity_correct"]) for r in matched), len(matched)),
        "evidence_sufficient": _rate(evidence.get("Sufficient", 0), sum(evidence.values())),
        "evidence_counts": dict(evidence),
        "quotes_real": (sum(real) / len(real)) if real else None,
        "invented_citations": sum(r["invented"] for r in rows if not r.get("merged_row")),
        "reasoning_avg": (sum(reasoning) / len(reasoning)) if reasoning else None,
        "reasoning_scored": len(reasoning),
        "duration_minutes": minutes, "cost_usd": cost,
        "input_tokens": info.get("input_tokens"), "output_tokens": info.get("output_tokens"), "steps": info.get("steps"),
        "cost_per_valid_finding": _rate(cost, n_valid) if cost is not None else None,
        "minutes_per_valid_finding": _rate(minutes, n_valid) if minutes is not None else None,
        "contract_problems": len(info.get("problems", [])),
    }


def confusion(result: dict) -> dict[str, dict[str, int]]:
    """Expected class (rows) against reported class (columns), over matched findings."""
    grid = {e: {r: 0 for r in contract.CLASSES + ["(no label)"]} for e in contract.CLASSES}
    for r in result["rows"]:
        if r["status"] == "Match" and r["case_id"]:
            grid[r["expected_class"]][r["classification"] or "(no label)"] += 1
    return grid


def breakdown(result: dict, by: str, documents: dict | None = None) -> list[dict]:
    """Recall and class accuracy by one coverage dimension:
    'class', 'severity', 'check_type', 'scenario', 'set', 'doc_type' or 'doc_format'."""
    room = result["run"]["data_room"]
    groups = defaultdict(list)
    for c in result["cases"]:
        if by == "class":
            keys = [c["expected_class"]]
        elif by == "severity":
            keys = [c["expected_severity"]]
        elif by == "check_type":
            keys = [c["check_type"]]
        elif by == "set":
            keys = [c["set"]]
        elif by == "scenario":
            keys = c["scenario_tags"] or ["(none)"]
        elif by in ("doc_type", "doc_format"):
            field = "type" if by == "doc_type" else "format"
            keys = sorted({(documents or {}).get((room, d), {}).get(field) or "(unknown)" for d in c["documents"]})
        else:
            raise ValueError(by)
        for k in keys:
            groups[k].append(c)
    out = []
    for k, cs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        rep = [c for c in cs if c["report"]]
        neg = [c for c in cs if not c["report"]]
        found = [c for c in rep if c["outcome"] == "Found"]
        labelled = [c for c in cs if c["finding_id"]]
        out.append({
            by: k, "cases": len(cs), "reportable": len(rep), "found": len(found),
            "recall": _rate(len(found), len(rep)),
            "weighted_recall": _rate(sum(c["weight"] for c in found), sum(c["weight"] for c in rep)),
            "negative": len(neg), "false_alarms": sum(c["outcome"] == "False alarm" for c in neg),
            "class_accuracy": _rate(sum(bool(c["class_correct"]) for c in labelled), len(labelled)),
        })
    return out


def score_all(runs: list[dict] | None = None, cases: list[dict] | None = None, reviews: dict | None = None) -> list[dict]:
    runs = store.load_runs() if runs is None else runs
    cases = store.load_cases() if cases is None else cases
    reviews = store.load_reviews() if reviews is None else reviews
    chunk_cache: dict[str, dict] = {}
    out = []
    for run in runs:
        room = run["run"].get("data_room", "")
        if room not in chunk_cache:
            chunk_cache[room] = store.load_chunks(room)
        run["run"]["problems"] = run.get("problems", [])
        out.append(score_run(run, cases, reviews, chunk_cache[room]))
    return out
