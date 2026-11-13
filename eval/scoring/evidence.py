"""Evidence: is a quoted passage really in its document, and does a finding cite what its case rests on."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


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
