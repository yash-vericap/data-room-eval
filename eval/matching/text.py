"""Wording: word tokens and the tf-idf similarity of two texts."""
from __future__ import annotations

import math
import re
from collections import Counter


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
