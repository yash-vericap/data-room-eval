"""Matching findings to answer-key cases.

Three steps, as in the methodology:
1. Location. A case is a candidate for a finding when the finding cites at least one of the case's
   documents.
2. Content. Each candidate pair gets a score from three parts: how much of the case's cited
   documents and pages the finding covers, how many of the case's key values (amounts, dates,
   percentages, counts) appear in the finding, and how similar the wording is.
3. Manual review. Pairs between the two thresholds go to a review list. A stored manual decision
   always wins over the automatic result.

Everything here is rule-based and gives the same answer on every run.
"""
from __future__ import annotations

import math
import re
from collections import Counter

MATCH_AT = 0.50     # at or above: clear match
REVIEW_AT = 0.36    # between REVIEW_AT and MATCH_AT: needs a manual decision
MERGE_AT = 0.62     # a second case this strong, and close to the best one, counts as merged into the finding
MERGE_RATIO = 0.88
W_LOCATION, W_VALUES, W_TEXT = 0.30, 0.35, 0.35
NO_VALUES_FACTOR = 0.85   # score ceiling for a pair that shares no figures
SIBLING_GAP = 0.20        # how close a reportable case must score to replace a negative case (see _prefer_reportable)

# ---- key values ---------------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_WORDS = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
_DATE_WORDS2 = re.compile(rf"\b(\d{{1,2}})\s+({_MON})\.?,?\s+(\d{{4}})\b", re.I)
_DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTH_YEAR = re.compile(rf"\b({_MON})\.?\s+(\d{{4}})\b", re.I)
_SKIP_REF = re.compile(r"\b(?:DOC|R\d*|HTC\d*|CO|CD|F)-\d+\b|\bpp?\.\s*\d+(?:\s*-\s*\d+)?|\b(?:section|sec\.|slide|line|lines|row|page|"
                       r"item|comment|condition|milestone|paragraph|exhibit|appendix|schedule|part)\s+\d+(?:\.\d+)*(?:\([a-z0-9]+\))*",
                       re.I)
_NUMBER = re.compile(
    r"(\$\s?)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(%|percent\b|cents?\b|mm\b|m\b|million\b|bn\b|billion\b|k\b|thousand\b)?",
    re.I)
_MULT = {"m": 1e6, "mm": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "k": 1e3, "thousand": 1e3}


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def key_values(text: str) -> set[str]:
    """Amounts, percentages, counts and dates in a text, in one standard form.

    $24,600,000, $24.6M and "24,600 ($ in thousands)" all give 2.46e+07; July 15, 2025 and
    7/15/2025 give the same date.
    """
    out: set[str] = set()
    if not text:
        return out
    for seg in re.split(r"\s*\|\|\s*|\n+", text):
        s = seg

        def _date(y, m, d):
            if 1 <= m <= 12 and 1 <= d <= 31:
                out.add(f"md:{m:02d}-{d:02d}")
                if y:
                    out.add(f"d:{y:04d}-{m:02d}-{d:02d}")

        for m in _DATE_WORDS.finditer(s):
            _date(int(m.group(3)) if m.group(3) else None, _MONTHS[m.group(1).lower()], int(m.group(2)))
        for m in _DATE_WORDS2.finditer(s):
            _date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        for m in _DATE_NUM.finditer(s):
            y = int(m.group(3))
            _date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
        for m in _MONTH_YEAR.finditer(s):
            out.add(f"my:{int(m.group(2)):04d}-{_MONTHS[m.group(1).lower()]:02d}")
        s = _DATE_WORDS.sub(" ", _DATE_WORDS2.sub(" ", _DATE_NUM.sub(" ", _MONTH_YEAR.sub(" ", s))))
        s = _SKIP_REF.sub(" ", s)
        thousands = bool(re.search(r"in thousands|\$\s?000s?|\(000s?\)|\$ thousands", seg, re.I))
        for m in _NUMBER.finditer(s):
            dollar, raw, suffix = m.group(1), m.group(2), (m.group(3) or "").lower()
            try:
                x = float(raw.replace(",", ""))
            except ValueError:
                continue
            if suffix in ("%", "percent"):
                out.add(f"{_fmt(x)}%")
                continue
            if suffix.startswith("cent"):
                out.add(_fmt(x / 100))
                continue
            if suffix in _MULT:
                out.add(_fmt(x * _MULT[suffix]))
                continue
            if not dollar and "," not in raw and "." not in raw and (x < 10 or 1900 <= x <= 2100):
                if 1900 <= x <= 2100:
                    out.add(f"y:{int(x)}")
                continue            # bare small integers carry no signal
            out.add(_fmt(x))
            if thousands:
                out.add(_fmt(x * 1000))
    return out


# ---- wording ------------------------------------------------------------------------------------

_STOP = set("""a an and are as at be been both but by can could do does for from had has have if in into is it its may more
no not of on or other should so than that the their them then there these this those to under was were which while who
will with would doc docs document documents states state says said shows show stated gives per p pp section""".split())
_WORD = re.compile(r"[a-z][a-z0-9'&-]{1,}")


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall((text or "").lower()):
        w = w.strip("'-")
        if len(w) < 3 or w in _STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def _tfidf(tok: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tok)
    return {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ---- scoring one data room ----------------------------------------------------------------------

def _cit_text(cits: list[dict]) -> str:
    return " || ".join(c.get("quote") or "" for c in cits)


def _locs(cits: list[dict]) -> tuple[set, set]:
    docs = {c["doc_id"] for c in cits if c.get("doc_id")}
    pages = {(c["doc_id"], c["page"]) for c in cits if c.get("doc_id") and c.get("page") is not None}
    return docs, pages


def _f1(a: set, b: set) -> float:
    """Overlap of what the finding cites (a) with what the case cites (b), counting both directions."""
    hit = len(a & b)
    return 2 * hit / (len(a) + len(b)) if hit else 0.0


class RoomIndex:
    """Everything about one data room's cases that the matcher needs, worked out once."""

    def __init__(self, cases: list[dict]):
        self.cases = cases
        self.case_tokens, self.case_values, self.case_locs = {}, {}, {}
        df_tok, df_val = Counter(), Counter()
        for c in cases:
            text = " ".join([c["summary"], c["claims_compared"], c["explanation"], _cit_text(c["citations"])])
            tok = tokens(text)
            vals = key_values(c["claims_compared"]) | key_values(_cit_text(c["citations"]))
            self.case_tokens[c["case_id"]], self.case_values[c["case_id"]] = tok, vals
            docs, pages = _locs(c["citations"])
            docs |= set(c.get("documents") or [])
            self.case_locs[c["case_id"]] = (docs, pages)
            df_tok.update(set(tok))
            df_val.update(vals)
        n = max(len(cases), 1)
        self.idf = {t: math.log((n + 1) / (d + 0.5)) for t, d in df_tok.items()}
        self.val_idf = {v: math.log((n + 1) / (d + 0.5)) for v, d in df_val.items()}
        self.case_vec = {cid: _tfidf(tok, self.idf) for cid, tok in self.case_tokens.items()}

    def score(self, finding: dict, case: dict) -> dict:
        cid = case["case_id"]
        f_docs, f_pages = _locs(finding["citations"])
        c_docs, c_pages = self.case_locs[cid]
        if not (f_docs & c_docs):
            return {"score": 0.0, "location": 0.0, "values": 0.0, "text": 0.0}
        location = 0.5 * _f1(f_docs, c_docs) + 0.5 * (_f1(f_pages, c_pages) if c_pages and f_pages else _f1(f_docs, c_docs))

        f_text = " ".join([finding["summary"], finding["claims_compared"], finding["explanation"]])
        f_vals = key_values(finding["claims_compared"]) | key_values(_cit_text(finding["citations"])) | key_values(
            finding["summary"])
        c_vals = self.case_values[cid]
        if c_vals:
            w = lambda v: self.val_idf.get(v, 1.0)
            values = sum(w(v) for v in c_vals & f_vals) / sum(w(v) for v in c_vals)
        else:
            values = None
        text = _cosine(_tfidf(tokens(f_text + " " + _cit_text(finding["citations"])), self.idf), self.case_vec[cid])
        text = min(1.0, text / 0.45)       # a cosine of 0.45 between two write-ups of one issue is already high
        no_values = (W_LOCATION * location + W_TEXT * text) / (W_LOCATION + W_TEXT)
        if values is None:                 # case without figures: wording and location carry the score
            score = no_values
        else:                              # a finding may be right without repeating the case's figures
            score = max(W_LOCATION * location + W_VALUES * values + W_TEXT * text, NO_VALUES_FACTOR * no_values)
        return {"score": round(score, 4), "location": round(location, 3),
                "values": None if values is None else round(values, 3), "text": round(text, 3)}


def match_run(findings: list[dict], cases: list[dict], reviews: dict[str, dict] | None = None,
              run_id: str = "") -> list[dict]:
    """Returns one row per finding-to-case link (a finding with no case gets one row).

    Row fields: finding_id, case_id (or None), status, score, parts, decided ('manual' or 'rules'),
    candidates (the three best cases with their scores), note, evidence_manual, reasoning.
    """
    reviews = reviews or {}
    index = RoomIndex(cases)
    by_id = {c["case_id"]: c for c in cases}
    prelim = []
    for f in findings:
        scored = sorted(((index.score(f, c), c["case_id"]) for c in cases), key=lambda t: -t[0]["score"])
        cands = [{"case_id": cid, **parts} for parts, cid in scored[:3] if parts["score"] > 0]
        prelim.append((f, cands))

    rows: list[dict] = []
    auto: list[tuple[dict, list[dict]]] = []
    for f, cands in prelim:
        rv = reviews.get(f"{run_id}::{f['finding_id']}")
        if rv:
            ids = [c for c in rv.get("case_ids") or [] if c in by_id] or [None]
            for i, cid in enumerate(ids):
                sc = next((c for c in cands if c["case_id"] == cid), None)
                rows.append({"finding_id": f["finding_id"], "case_id": cid, "status": rv["status"],
                             "score": sc["score"] if sc else None, "decided": "manual", "candidates": cands,
                             "note": rv.get("note") or "", "evidence_manual": rv.get("evidence"),
                             "reasoning": rv.get("reasoning"), "merged_row": i > 0})
        else:
            auto.append((f, cands))

    taken = {r["case_id"] for r in rows if r["status"] == "Match" and r["case_id"]}
    links = []          # (score, finding, case_id, cands, merged)
    for f, cands in auto:
        if not cands or cands[0]["score"] < REVIEW_AT:
            rows.append(_row(f, None, "False positive candidate", cands))
            continue
        best = _prefer_reportable(f, cands, by_id)
        if best["score"] < MATCH_AT:
            rows.append(_row(f, best["case_id"], "Needs review", cands))
            continue
        links.append((best["score"], f, best["case_id"], cands, False))
        for extra in cands:
            if extra is best or not by_id[extra["case_id"]]["report"]:
                continue                        # a second link is only ever added to a reportable case
            if extra["score"] >= MERGE_AT and extra["score"] >= MERGE_RATIO * best["score"]:
                links.append((extra["score"], f, extra["case_id"], cands, True))
    for score, f, cid, cands, merged in sorted(links, key=lambda t: -t[0]):
        if cid in taken:
            if not merged:                      # the same issue reported again: best copy already counted
                rows.append(_row(f, cid, "Duplicate", cands))
            continue
        taken.add(cid)
        r = _row(f, cid, "Match", cands)
        r["merged_row"] = merged
        rows.append(r)
    order = {f["finding_id"]: i for i, f in enumerate(findings)}
    rows.sort(key=lambda r: (order[r["finding_id"]], r.get("merged_row", False)))
    return rows


def _prefer_reportable(finding: dict, cands: list[dict], by_id: dict) -> dict:
    """Negative cases often sit right next to a reportable one (the signed and draft agreements
    differ, which is fine; the model relies on the draft, which is not). When the best candidate is
    a negative case, a reportable case scores close behind, and the finding cites a document that
    only the reportable case involves, the finding is about the reportable case."""
    best = cands[0]
    if by_id[best["case_id"]]["report"]:
        return best
    f_docs = {c["doc_id"] for c in finding["citations"] if c.get("doc_id")}
    neg_docs = set(by_id[best["case_id"]].get("documents") or [])
    for other in cands[1:]:
        case = by_id[other["case_id"]]
        if not case["report"] or other["score"] < MATCH_AT or other["score"] < best["score"] - SIBLING_GAP:
            continue
        if f_docs & (set(case.get("documents") or []) - neg_docs):
            return other
    return best


def _row(f, cid, status, cands):
    sc = next((c["score"] for c in cands if c["case_id"] == cid), None)
    return {"finding_id": f["finding_id"], "case_id": cid, "status": status, "score": sc, "decided": "rules",
            "candidates": cands, "note": "", "evidence_manual": None, "reasoning": None, "merged_row": False}
