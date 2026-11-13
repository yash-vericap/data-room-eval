"""The score of one finding against one case: location, key values and wording."""
from __future__ import annotations

import math
from collections import Counter

from .text import _cosine, _tfidf, tokens
from .values import key_values


W_LOCATION, W_VALUES, W_TEXT = 0.30, 0.35, 0.35


NO_VALUES_FACTOR = 0.85   # score ceiling for a pair that shares no figures


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
