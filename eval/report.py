"""The score table of every stored run (reports/scores.csv), and a short Markdown version (reports/report.md)."""
from __future__ import annotations

import csv
from datetime import datetime

from . import scoring, store


def pct(x, digits=1):
    return "-" if x is None else f"{100 * x:.{digits}f}%"


def num(x, digits=2):
    return "-" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def score_row(res: dict) -> dict:
    m, r = res["metrics"], res["run"]
    return {
        "Run": r["run_id"], "Source": r["source"], "System": r["system"], "Version": r["version"],
        "Data room": r["data_room"], "Weighted recall": m["weighted_recall"], "Recall": m["recall"],
        "Found": m["found"], "Reportable": m["reportable"], "Critical missed": m["critical_missed"],
        "Precision": m["precision"], "False positives": m["false_positives"], "Findings": m["findings"],
        "Class accuracy": m["class_accuracy"], "Severity accuracy": m["severity_accuracy"],
        "Evidence sufficient": m["evidence_sufficient"], "Reasoning (0-2)": m["reasoning_avg"],
        "Needs review": m["needs_review"], "Minutes": m["duration_minutes"], "Cost (USD)": m["cost_usd"],
        "Contract problems": len(res["problems"]),
    }


PCT_COLS = ["Weighted recall", "Recall", "Precision", "Class accuracy", "Severity accuracy", "Evidence sufficient"]


def _table(rows: list[dict], cols: list[str]) -> str:
    def cell(row, c):
        v = row.get(c)
        if c in PCT_COLS or any(k in c.lower() for k in ("recall", "accuracy", "precision", "evidence sufficient")):
            return pct(v) if isinstance(v, (int, float)) or v is None else str(v)
        return num(v) if v is not None else "-"
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(cell(r, c).replace("|", "/") for c in cols) + " |" for r in rows]
    return "\n".join(out)


def write(results: list[dict] | None = None) -> tuple[str, str]:
    """Writes the table of every run, scored by the fixed rules. Returns (report path, csv path)."""
    results = scoring.score_all() if results is None else results
    rows = sorted((score_row(r) for r in results), key=lambda r: (r["Data room"], -(r["Weighted recall"] or 0)))
    store.REPORTS.mkdir(parents=True, exist_ok=True)
    md, csv_path = store.REPORTS / "report.md", store.REPORTS / "scores.csv"
    cases = store.load_cases()
    md.write_text("\n".join([
        "# Data room evaluation: scores per run", "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M}. Answer key: {cases[0]['snapshot'] if cases else '-'}, {len(cases)} cases.",
        "Every run is scored with the same fixed rules. The headline is severity-weighted recall on the withheld set.", "",
        _table(rows, ["Run", "Source", "Data room", "Weighted recall", "Recall", "Found", "Reportable", "Critical missed",
                      "Precision", "False positives", "Class accuracy", "Needs review"]), ""]), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["Run"])
        w.writeheader()
        w.writerows(rows)
    return str(md), str(csv_path)
