"""The document pages shown to the model: whole, or cut to excerpts around the quoted words. Quote checks are cached."""
from __future__ import annotations

from .. import matching, scoring


_MEMO: dict[tuple, object] = {}        # quote checks are slow and repeat across calls and reruns


def _memo(key: tuple, fn):
    if key not in _MEMO:
        if len(_MEMO) > 50000:
            _MEMO.clear()
        _MEMO[key] = fn()
    return _MEMO[key]


def _page_of(cit: dict, chunks: dict) -> int | None:
    """The page a citation points at; when the page number is missing or wrong, the page that holds the quote."""
    pages = chunks.get(cit.get("doc_id") or "") or {}
    return _memo(("page", id(pages), cit.get("doc_id"), cit.get("page"), cit.get("quote") or ""), lambda: _find_page(cit, pages))


def _find_page(cit: dict, pages: dict) -> int | None:
    page = cit.get("page")
    if not cit.get("quote"):
        return page if page in pages else None
    if page in pages and scoring.quote_is_real(cit["quote"], {page: pages[page]}, page) == "Real":
        return page
    hit = next((p for p in sorted(x for x in pages if x is not None)
                if scoring.quote_is_real(cit["quote"], {p: pages[p]}, p) == "Real"), None)
    return hit if hit is not None else (page if page in pages else None)


def _excerpts(text: str, quotes: list[str], radius: int) -> str:
    """The parts of a page around each quoted passage, joined where they overlap, so a page that holds
    several quotes is sent once and not once per quote."""
    low, spans = text.lower(), []
    for q in quotes or [""]:
        at = low.find(q.lower()) if q else -1
        if at < 0:
            words = [w for w in (q or "").split() if len(w) > 3][:4]
            at = next((low.find(w.lower()) for w in words if w.lower() in low), 0)
        spans.append([max(0, at - radius), min(len(text), at + len(q or "") + radius)])
    spans.sort()
    merged = [spans[0]]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    body = " ... ".join(text[a:b] for a, b in merged)
    return ("... " if merged[0][0] else "") + body + (" ..." if merged[-1][1] < len(text) else "")


def _pages_block(cits: list[dict], chunks: dict, radius: int | None, extra: list[tuple[str, int]] = ()) -> tuple[str, list]:
    """The cited pages as <page> blocks, whole or cut to excerpts around the quoted words. Each page is sent
    once, however many quotes point at it."""
    order, quotes = [], {}
    for doc, page, quote in [(c["doc_id"], _page_of(c, chunks), c.get("quote") or "") for c in cits if c.get("doc_id")] + \
            [(d, p, "") for d, p in extra]:
        text = (chunks.get(doc) or {}).get(page) if page is not None else None
        if not text:
            continue
        if (doc, page) not in quotes:
            order.append((doc, page))
            quotes[(doc, page)] = []
        if quote:
            quotes[(doc, page)].append(quote)
    parts = []
    for doc, page in order:
        text = chunks[doc][page].strip()
        body = text if radius is None else _excerpts(text, quotes[(doc, page)], radius)
        parts.append(f'<page doc="{doc}" page="{page}">\n{body}\n</page>')
    if not parts:
        return ("The text of the cited pages is not stored. The only passages available are the quotes above. "
                "You cannot confirm that a quote really appears in its document."), []
    note = "Each block is an excerpt of the page around the quoted words, not the whole page.\n" if radius is not None else ""
    return note + "\n".join(parts), [[d, p] for d, p in order]


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
