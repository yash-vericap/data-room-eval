"""Amounts, percentages, counts and dates in a text, in one standard form, so $24,600,000, $24.6M and
"24,600 ($ in thousands)" compare as equal."""
from __future__ import annotations

import re


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
