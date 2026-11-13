"""Where everything lives, and the answer key.

Everything the tool reads and writes lives under DATA. On a server, point EVAL_DATA_DIR at a persistent disk.
Runs and manual decisions are in run_files.py, page text in pages.py; both are reachable from here."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


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


def data_rooms(cases: list[dict] | None = None) -> list[str]:
    """Every data room the tool knows: rooms with answer-key cases, rooms in the document list, and rooms
    whose page text is stored (locally or in the document store). A room added from the app shows up
    here before it has any case."""
    from . import doc_store
    rooms = {c["data_room"] for c in cases or []} | {r for r, _ in load_documents()}
    if DATA_ROOM.exists():
        rooms |= {p.name for p in DATA_ROOM.iterdir() if p.is_dir() and (p / "chunks.json").exists()}
    if doc_store.enabled():
        try:
            rooms |= {r["room"] for r in doc_store.list_rooms()}
        except doc_store.StoreUnavailable:
            pass
    return sorted(r for r in rooms if r)


def load_documents() -> dict[tuple[str, str], dict]:
    docs = _read(ANSWER_KEY / "documents.json", [])
    return {(d["data_room"], d["doc_id"]): d for d in docs}

from .run_files import delete_review, load_reviews, load_runs, review_key, save_submission  # noqa: E402,F401
from .pages import chunks_problem, load_chunks, load_local_chunks  # noqa: E402,F401
