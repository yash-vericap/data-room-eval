"""Where checks are kept: reality_checks/<check_id>.json under the data folder, one file per run and model.
Every verdict is saved the moment it exists, so a check stopped by a limit loses nothing."""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone

from .. import store
from ..providers import settings
from .labels import PROMPT_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_LOCK = threading.Lock()


def check_id(room: str, findings: list[dict], model: str = "") -> str:
    """A run's identity: its data room and its findings. Two different JSON files for the same data room are
    two checks; the same file read again is the same check, whichever model answers. (Checks made before
    this change also had the model in their identity; open_check still finds them.)"""
    parts = [room, model, PROMPT_VERSION] if model else [room, PROMPT_VERSION]
    for f in findings:
        parts += [f["finding_id"], f["summary"], f["claims_compared"], " || ".join(c["raw"] for c in f["citations"])]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def checks_dir():
    return store.DATA / "reality_checks"


def _path(cid: str):
    return checks_dir() / f"{cid}.json"


def save(check: dict) -> None:
    store._write(_path(check["check_id"]), check)


def load_check(cid: str) -> dict | None:
    return store._read(_path(cid))


def delete_check(cid: str) -> None:
    """Removes a stored check. Accepted cases and rejected candidates it produced stay in the answer key."""
    if _path(cid).exists():
        _path(cid).unlink()


def list_checks(room: str | None = None) -> list[dict]:
    """Stored checks, newest first: {"check_id", "label", "data_room", "created_at", "findings", "verdicts"}."""
    out = []
    for path in checks_dir().glob("*.json") if checks_dir().exists() else []:
        c = store._read(path) or {}
        if c.get("check_id") and (room is None or c.get("data_room") == room):
            out.append({"check_id": c["check_id"], "label": c.get("label"), "data_room": c.get("data_room"),
                        "created_at": c.get("created_at"), "findings": len(c.get("findings") or []),
                        "verdicts": len(c.get("case_verdicts") or {}) + len(c.get("new_verdicts") or {})})
    return sorted(out, key=lambda c: c["created_at"] or "", reverse=True)


def _unique_label(room: str, label: str, cid: str) -> str:
    """Two runs on one data room never share a name, so they can be told apart everywhere."""
    taken = {c["label"] for c in list_checks(room) if c["check_id"] != cid}
    if label not in taken:
        return label
    n = 2
    while f"{label} ({n})" in taken:
        n += 1
    return f"{label} ({n})"


def open_check(room: str, label: str, read: dict, model: str | None = None) -> dict:
    """The stored check for this run, or a new one. The same run reopens the same check, so a check that
    stopped halfway carries on, also on a different model."""
    cfg = settings()
    model = model or cfg["model"] or "unset"
    cid = check_id(room, read["findings"])
    check = load_check(cid)
    if check is None:                     # a check made before the identity left out the model
        for m in dict.fromkeys([model] + [c["model"] for c in cfg.get("chain") or []]):
            check = load_check(check_id(room, read["findings"], m))
            if check:
                break
    if check is None:
        check = {"check_id": cid, "label": _unique_label(room, label, cid), "data_room": room, "source": "Our system",
                 "snapshot": None, "model": model, "provider": cfg["provider"], "prompt_version": PROMPT_VERSION,
                 "created_at": _now(), "source_path": read["source_path"], "read_notes": read["notes"],
                 "run_meta": read["run_meta"], "findings": read["findings"], "case_verdicts": {}, "new_verdicts": {},
                 "manual": {}, "input_tokens": 0, "output_tokens": 0}
    elif label and label != check.get("label"):
        check["label"] = _unique_label(room, label, check["check_id"])
    save(check)
    return check


def set_manual(check: dict, kind: str, id_: str, status: str, finding_ids: list[str] | None = None, note: str = "",
               case_hash: str | None = None) -> None:
    """A verdict set by hand. kind is 'case' or 'finding'. It wins over the model's verdict from then on."""
    check["manual"][f"{kind}::{id_}"] = {"status": status, "finding_ids": list(finding_ids or []), "note": note,
                                         "at": _now(), "case_hash": case_hash}
    save(check)


def clear_manual(check: dict, kind: str, id_: str) -> None:
    if check["manual"].pop(f"{kind}::{id_}", None) is not None:
        save(check)
