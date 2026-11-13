"""Stored runs (submissions/) and the manual decisions on their findings (reviews/decisions.json)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import contract, store


def load_runs() -> list[dict]:
    """Every run under submissions/, each with its contract problems and file path."""
    runs = []
    for path in sorted(store.SUBMISSIONS.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            runs.append({"run": {"run_id": path.stem, "data_room": "", "source": "", "system": path.stem},
                         "findings": [], "problems": [f"Not valid JSON: {e}"], "path": str(path)})
            continue
        run, problems = contract.normalise(payload)
        run["problems"], run["path"] = problems, str(path.relative_to(store.DATA))
        runs.append(run)
    return runs


def save_submission(payload: dict, folder: str | None = None, allow_problems: bool = False) -> tuple[Path | None, list[str]]:
    """Checks a run against the contract and stores it. Returns (path or None if rejected, problems)."""
    run, problems = contract.normalise(payload)
    if problems and not allow_problems:
        return None, problems
    rid = run["run"]["run_id"]
    if not rid:
        return None, problems
    sub = folder or ("baseline" if run["run"]["source"] == "Baseline model" else "system")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", rid)
    path = store.SUBMISSIONS / sub / f"{safe}.json"
    store._write(path, payload)
    return path, problems


def review_key(run_id: str, finding_id: str) -> str:
    return f"{run_id}::{finding_id}"


def load_reviews() -> dict[str, dict]:
    return store._read(store.REVIEWS, {})


def delete_review(run_id: str, finding_id: str) -> None:
    reviews = load_reviews()
    if reviews.pop(review_key(run_id, finding_id), None) is not None:
        store._write(store.REVIEWS, reviews)
