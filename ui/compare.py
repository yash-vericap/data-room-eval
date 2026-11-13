"""A ground-truth case and the run's findings in one table, field by field, so each line can be read across."""
from __future__ import annotations

from eval import matching
from eval import reality_check as rc

from .common import QUOTE_LABEL, _safe

CSS = """<style>
.vc-cmp{width:100%;border-collapse:collapse;font-size:.88rem;table-layout:fixed;margin-bottom:.6rem}
.vc-cmp th,.vc-cmp td{border:1px solid rgba(128,128,128,.3);padding:.45rem .6rem;vertical-align:top;text-align:left;
  white-space:pre-wrap;overflow-wrap:anywhere}
.vc-cmp th{background:rgba(128,128,128,.12)}
.vc-cmp td.f{font-weight:600;opacity:.75}
.vc-cmp td.none{font-style:italic;opacity:.75}
.vc-cmp .diff{font-weight:600}
</style>"""
FIELDS = ["Summary", "Class · severity", "Claims compared", "Citations", "Explanation"]
SHOWN = 3                                         # findings shown next to the case; the rest are named below


def _kind(x: dict, case: dict | None) -> str:
    cls = x.get("classification") or x.get("raw_classification") or "(no class)"
    sev = x.get("severity") or x.get("raw_severity") or "(no severity)"
    text = f"{_safe(cls)} · {_safe(sev)}"
    if case is not None:
        notes = [n for n, same in (("class", cls == case["classification"]), ("severity", sev == case["severity"])) if not same]
        if notes:
            text += f"\n<span class='diff'>≠ ground truth on {' and '.join(notes)}</span>"
    return text


def _citations(cits: list[dict], checks: list[str] | None) -> str:
    if not cits:
        return "(none)"
    checks = checks or [None] * len(cits)
    return "\n".join(f"• {_safe(c['raw'])}" + (f" — <i>{QUOTE_LABEL[q]}</i>" if q else "") for c, q in zip(cits, checks))


def _cell(field: str, x: dict, case: dict | None, quotes: list[str] | None) -> str:
    if field == "Summary":
        return _safe(x["summary"])
    if field == "Class · severity":
        return _kind(x, case)
    if field == "Citations":
        return _citations(x["citations"], quotes)
    key = "claims_compared" if field == "Claims compared" else "explanation"
    return _safe(x.get(key) or "") or "(none)"


def side_by_side(case: dict, findings: list[dict], chunks: dict, empty: str) -> str:
    """HTML: one row per field, the ground truth in the first column and each finding next to it."""
    cols = [(f"Ground truth · {case['case_id']}", case, None, None)]
    cols += [(f"The run · {f['finding_id']}", f, case, rc.own_quotes(f, chunks)) for f in findings[:SHOWN]]
    head = "<tr><th style='width:8.5rem'></th>" + "".join(f"<th>{_safe(t)}</th>" for t, *_ in cols)
    head += "<th>The run</th></tr>" if not findings else "</tr>"
    body = ""
    for i, field in enumerate(FIELDS):
        cells = "".join(f"<td>{_cell(field, x, ref, q)}</td>" for _, x, ref, q in cols)
        if not findings and i == 0:
            cells += f"<td class='none' rowspan='{len(FIELDS)}'>{_safe(empty)}</td>"
        body += f"<tr><td class='f'>{field}</td>{cells}</tr>"
    return f"<table class='vc-cmp'>{head}{body}</table>"


def closest(case: dict, findings: list[dict], index: matching.RoomIndex, n: int = 3) -> list[tuple[float, dict]]:
    """The run's findings nearest to a case by wording and documents, for a case nothing was linked to."""
    scored = sorted(((index.score(f, case)["score"], f) for f in findings), key=lambda t: -t[0])
    return [(s, f) for s, f in scored[:n] if s > 0]
