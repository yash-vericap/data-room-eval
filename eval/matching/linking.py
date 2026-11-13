"""Links every finding of a run to a case, a duplicate, the review queue or no case. A manual decision wins."""
from __future__ import annotations

from .index import RoomIndex


MATCH_AT = 0.50     # at or above: clear match
REVIEW_AT = 0.36    # between REVIEW_AT and MATCH_AT: needs a manual decision
MERGE_AT = 0.62     # a second case this strong, and close to the best one, counts as merged into the finding
MERGE_RATIO = 0.88
SIBLING_GAP = 0.20        # how close a reportable case must score to replace a negative case (see _prefer_reportable)


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
