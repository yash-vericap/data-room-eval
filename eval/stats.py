"""Numbers across checked runs: one row per run, how stable each case is across runs of one data room,
two runs side by side, recall by severity and class, where findings went, and the models used."""
from __future__ import annotations

from collections import Counter

from . import contract
from . import reality_check as rc

FOUND, PARTIAL, MISSED = rc.FOUND, rc.PARTIAL, rc.MISSED


def checked(room: str | None = None) -> list[dict]:
    """Every stored check that has at least one verdict, oldest first, each with its results."""
    out = []
    for meta in reversed(rc.list_checks(room)):
        if meta["verdicts"]:
            out.append(meta)
    return out


def run_row(check: dict, res: dict) -> dict:
    m, a = res["metrics"], res["metrics"]["all"]
    return {"Run": check["label"], "Data room": check["data_room"], "Checked": (check["created_at"] or "")[:16].replace("T", " "),
            "Findings": m["findings"], "Accuracy": a["accuracy"], "Withheld": m["withheld"]["accuracy"],
            "Found": a["found"], "Partially found": a["partial"], "Missed": a["missed"], "Critical missed": a["critical_missed"],
            "Backed by documents": m["grounded_share"], "New real issues": m["new_real"], "Rejected by rules": m["rejected_by_rules"],
            "Made up": m["made_up"], "Non-issues flagged": m["wrongly_flagged"],
            "Open verdicts": a["open"] + m["needs_review"] + m["not_checked"],
            "Tokens in": check.get("input_tokens") or 0, "Tokens out": check.get("output_tokens") or 0}


def stability(runs: list[tuple[dict, dict]]) -> list[dict]:
    """Per reportable case, its status in every run of one data room, and whether runs agree on it."""
    rows: dict[str, dict] = {}
    for check, res in runs:
        for r in res["cases"]:
            row = rows.setdefault(r["case_id"], {"Case": r["case_id"], "Severity": r["severity"], "Set": r["set"],
                                                 "Summary": r["summary"], "_w": r["weight"], "_s": []})
            row["_s"].append(r["status"])
            row[check["label"]] = r["status"]
    out = []
    for row in rows.values():
        s = row.pop("_s")
        found, partial = s.count(FOUND), s.count(PARTIAL)
        row["Found in"] = f"{found} of {len(s)}"
        row["Partly in"] = partial
        row["Pattern"] = ("Found every time" if found == len(s) else "Never found" if found + partial == 0
                          else "Found sometimes")
        out.append(row)
    order = {"Never found": 0, "Found sometimes": 1, "Found every time": 2}
    return sorted(out, key=lambda r: (order[r["Pattern"]], -r.pop("_w")))


def compare(a: tuple[dict, dict], b: tuple[dict, dict]) -> list[dict]:
    """Two runs of one data room, case by case: what the later one gained, lost or did better or worse."""
    rank = {FOUND: 2, PARTIAL: 1}
    sa = {r["case_id"]: r for r in a[1]["cases"]}
    out = []
    for r in b[1]["cases"]:
        x, y = sa.get(r["case_id"], {}).get("status", "Not checked"), r["status"]
        dx, dy = rank.get(x, 0), rank.get(y, 0)
        change = "Same" if x == y else "Gained" if dx == 0 and dy == 2 else "Lost" if dx == 2 and dy == 0 \
            else "Better" if dy > dx else "Worse" if dy < dx else "Changed"
        out.append({"Case": r["case_id"], "Severity": r["severity"], "Summary": r["summary"], a[0]["label"]: x,
                    b[0]["label"]: y, "Change": change})
    order = {"Lost": 0, "Worse": 1, "Gained": 2, "Better": 3, "Changed": 4, "Same": 5}
    return sorted(out, key=lambda r: (order[r["Change"]], r["Case"]))


def by_dimension(runs: list[tuple[dict, dict]], cases: list[dict], dim: str) -> list[dict]:
    """Found and partly found shares by severity or by expected class, over the selected runs."""
    key = {c["case_id"]: (c["severity"] if dim == "severity" else c["classification"]) for c in cases}
    groups: dict[str, Counter] = {}
    for _, res in runs:
        for r in res["cases"]:
            g = groups.setdefault(key.get(r["case_id"], "-"), Counter())
            g["cases"] += 1
            g[r["status"]] += 1
    order = contract.SEVERITIES if dim == "severity" else contract.CLASSES
    out = []
    for name in sorted(groups, key=lambda k: order.index(k) if k in order else 99):
        g = groups[name]
        out.append({"Severity" if dim == "severity" else "Class": name, "Case verdicts": g["cases"],
                    "Found": g[FOUND] / g["cases"], "Partially found": g[PARTIAL] / g["cases"], "Missed": g[MISSED] / g["cases"]})
    return out


def finding_flow(runs: list[tuple[dict, dict]]) -> list[dict]:
    """Where every finding of the selected runs went, by the class the run gave it."""
    flow = Counter()
    for check, res in runs:
        links = rc.linked(check)
        band = {n["finding_id"]: n["band"] for n in res["new"]}
        for f in check["findings"]:
            to = "Mapped to a case" if f["finding_id"] in links else band.get(f["finding_id"], "Not checked")
            flow[(f["classification"] or "Class not read", to)] += 1
    return [{"Class given": c, "Went to": t, "Findings": n} for (c, t), n in sorted(flow.items())]


def rule_rejections(runs: list[tuple[dict, dict]]) -> dict[str, int]:
    out = Counter()
    for _, res in runs:
        out.update(res["metrics"]["rejected_per_rule"])
    return dict(out)


def models(runs: list[tuple[dict, dict]]) -> dict[str, int]:
    out = Counter()
    for check, _ in runs:
        out.update(rc.models_used(check))
    return dict(out)
