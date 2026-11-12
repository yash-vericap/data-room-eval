"""Reading and writing the project files: answer key, submissions, manual reviews, document text."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import contract

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """Reads KEY=VALUE lines from .env into the environment. Values already set are left alone."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = re.split(r"\s+#", value.strip(), maxsplit=1)[0].strip().strip("'\"")
        if key.strip() and value:
            os.environ.setdefault(key.strip(), value)


_load_env_file(ROOT / ".env")
# Everything the tool reads and writes lives under DATA. On a server, point EVAL_DATA_DIR at a
# persistent disk so runs, manual decisions and judge verdicts survive a restart.
DATA = Path(os.environ.get("EVAL_DATA_DIR") or ROOT).resolve()
ANSWER_KEY = DATA / "answer_key"
SUBMISSIONS = DATA / "submissions"
REVIEWS = DATA / "reviews" / "decisions.json"
DATA_ROOM = DATA / "data_room"
REPORTS = DATA / "reports"


def _read(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


# ---- answer key -------------------------------------------------------------------------------

DRAFT = "draft"


def _path(name: str) -> Path:
    return ANSWER_KEY / f"{name}.json"


def snapshots() -> list[str]:
    """The frozen answer keys (library_v1, library_v2, ...), oldest first. The working draft is not one of them."""
    names = [p.stem for p in ANSWER_KEY.glob("library_*.json") if re.fullmatch(r"library_v\d+", p.stem)]
    return sorted(names, key=lambda n: int(n.split("_v")[1]))


def has_draft() -> bool:
    return _path("library_draft").exists()


def resolve_snapshot(snapshot: str | None = None) -> str:
    """The answer key a name stands for: 'draft' when asked for and present, otherwise a frozen snapshot
    (the newest when none is named). With no frozen snapshot at all, the draft is used."""
    names = snapshots()
    if snapshot == DRAFT:
        if has_draft():
            return DRAFT
        snapshot = None
    if snapshot in names:
        return snapshot
    if names:
        return names[-1]
    if has_draft():
        return DRAFT
    raise FileNotFoundError(f"No answer key found in {ANSWER_KEY}. Run: python -m eval import-sheet <file>")


def load_library(snapshot: str | None = None) -> dict:
    name = resolve_snapshot(snapshot)
    return _read(_path("library_draft" if name == DRAFT else name))


def load_cases(snapshot: str | None = None) -> list[dict]:
    """The cases of one answer key: a frozen snapshot by name, 'draft' for the working draft, or the
    newest frozen snapshot when nothing is named."""
    return load_library(snapshot)["cases"]


def snapshot_label(snapshot: str | None = None) -> str:
    name = resolve_snapshot(snapshot)
    return "Working draft" if name == DRAFT else "Library " + name.split("_")[1]


def load_documents() -> dict[tuple[str, str], dict]:
    docs = _read(ANSWER_KEY / "documents.json", [])
    return {(d["data_room"], d["doc_id"]): d for d in docs}


# ---- submissions ------------------------------------------------------------------------------

def load_runs() -> list[dict]:
    """Every run under submissions/, each with its contract problems and file path."""
    runs = []
    for path in sorted(SUBMISSIONS.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            runs.append({"run": {"run_id": path.stem, "data_room": "", "source": "", "system": path.stem},
                         "findings": [], "problems": [f"Not valid JSON: {e}"], "path": str(path)})
            continue
        run, problems = contract.normalise(payload)
        run["problems"], run["path"] = problems, str(path.relative_to(DATA))
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
    path = SUBMISSIONS / sub / f"{safe}.json"
    _write(path, payload)
    return path, problems


# ---- manual reviews ---------------------------------------------------------------------------

def review_key(run_id: str, finding_id: str) -> str:
    return f"{run_id}::{finding_id}"


def load_reviews() -> dict[str, dict]:
    return _read(REVIEWS, {})


def save_review(run_id: str, finding_id: str, *, status: str, case_ids: list[str], evidence: str | None = None,
                reasoning: int | None = None, note: str = "", decided_by: str = "evaluator") -> None:
    """Stores one manual decision. It overrides the automatic match for that finding from then on."""
    reviews = load_reviews()
    reviews[review_key(run_id, finding_id)] = {
        "status": status, "case_ids": case_ids, "evidence": evidence, "reasoning": reasoning, "note": note,
        "decided_by": decided_by, "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write(REVIEWS, reviews)


def delete_review(run_id: str, finding_id: str) -> None:
    reviews = load_reviews()
    if reviews.pop(review_key(run_id, finding_id), None) is not None:
        _write(REVIEWS, reviews)


# ---- document text, for the "quote is real" check ----------------------------------------------

_CHUNKS_PROBLEM: str | None = None


def chunks_problem() -> str | None:
    """Why page text could not be read from the document store on the last try, or None."""
    return _CHUNKS_PROBLEM


def load_chunks(data_room: str) -> dict[str, dict[int | None, str]]:
    """{doc_id: {page: text}} for one data room.

    With MONGO_URI set, the text comes from the document store (eval/doc_store.py). A room that is not
    in the store yet is read from the local folder. Without MONGO_URI everything is read locally. When
    the store cannot be reached the answer is empty, so quote checks show "Not checked" and the rest of
    the scoring still works; chunks_problem() says why."""
    global _CHUNKS_PROBLEM
    from . import doc_store
    if doc_store.enabled():
        try:
            out = doc_store.load_chunks(data_room)
            _CHUNKS_PROBLEM = None
            if out:
                return out
        except doc_store.StoreUnavailable as e:
            _CHUNKS_PROBLEM = str(e)
            return {}
    return load_local_chunks(data_room)


def load_local_chunks(data_room: str) -> dict[str, dict[int | None, str]]:
    """Reads data_room/<room>/chunks.json ([{doc_id, page, text}]) and any DOC-xx.txt files (pages
    separated by a form feed). Empty when no text is stored locally."""
    out: dict[str, dict] = {}
    folder = DATA_ROOM / data_room
    for row in _read(folder / "chunks.json", []) or []:
        doc = str(row.get("doc_id", "")).upper()
        page = row.get("page")
        out.setdefault(doc, {})
        out[doc][page] = out[doc].get(page, "") + "\n" + str(row.get("text", ""))
    for path in sorted(folder.glob("DOC-*.txt")) if folder.exists() else []:
        doc = re.match(r"(DOC-\d+)", path.stem.upper()).group(1)
        for i, text in enumerate(path.read_text(encoding="utf-8", errors="ignore").split("\f"), start=1):
            out.setdefault(doc, {})[i] = text
    return out
