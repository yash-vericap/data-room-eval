"""Checks every quote in the answer key against the stored document text."""
from __future__ import annotations

from .. import scoring, store


def check_answer_key(room: str) -> dict:
    """Checks every quote in the answer key against the stored document text. A quote that is not
    found is either an OCR miss or a slip in the answer key, and is worth a look either way."""
    chunks = store.load_chunks(room)
    try:
        cases = [c for c in store.load_cases() if c["data_room"] == room]
    except FileNotFoundError:
        cases = []
    checked = real = 0
    problems = []
    for c in cases:
        for cit in c["citations"]:
            pages = chunks.get(cit["doc_id"] or "")
            if not pages or not cit["quote"] or cit["quote"].startswith("["):
                continue
            res = scoring.quote_is_real(cit["quote"], pages, cit["page"])
            if res == "Not checked":
                continue
            checked += 1
            if res == "Real":
                real += 1
            else:
                problems.append({"case_id": c["case_id"], "citation": cit["raw"], "result": res})
    return {"cases": len(cases), "checked": checked, "real": real,
            "not_found": [p for p in problems if p["result"] == "Not found"],
            "wrong_page": [p for p in problems if p["result"] == "Wrong page"]}
