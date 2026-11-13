"""The document store's settings, and the check that keeps page text off open lines and unknown hosts."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import providers


class StoreUnavailable(RuntimeError):
    """The document store cannot be used: wrong settings, a refused host, or MongoDB cannot be reached."""


def _sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _doc(name: str) -> str | None:
    m = re.match(r"(DOC-\d+)", Path(str(name)).name, re.I)
    return m.group(1).upper() if m else None


def uri() -> str:
    return (os.environ.get("MONGO_URI") or "").strip()


def db_name() -> str:
    return (os.environ.get("MONGO_DB") or "dataroom_eval").strip()


def store_pdfs() -> bool:
    return (os.environ.get("EVAL_STORE_PDFS") or "").strip() == "1"


def hosts(mongo_uri: str) -> list[str]:
    """The host names in a MongoDB connection string, without credentials or ports."""
    rest = re.sub(r"^mongodb(\+srv)?://", "", mongo_uri)
    rest = rest.rsplit("@", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return [h.strip().lower().rsplit(":", 1)[0].strip("[]") if not h.strip().startswith("[") else
            h.strip().lower().split("]")[0].strip("[") for h in rest.split(",") if h.strip()]


def check_uri(mongo_uri: str) -> None:
    """Refuses a connection string that would send page text over an open line or to a host that is not
    allowed. A local host needs neither TLS nor a place on the allowed list."""
    if not re.match(r"^mongodb(\+srv)?://", mongo_uri):
        raise StoreUnavailable("MONGO_URI must start with mongodb:// or mongodb+srv://.")
    names = hosts(mongo_uri)
    if not names:
        raise StoreUnavailable("MONGO_URI names no host.")
    remote = [h for h in names if not providers.is_local_host(h)]
    if not remote:
        return
    if not (mongo_uri.startswith("mongodb+srv://") or re.search(r"[?&](tls|ssl)=true", mongo_uri, re.I)):
        raise StoreUnavailable(f"MongoDB at {', '.join(remote)} is not on this machine, so TLS is required. "
                               f"Use a mongodb+srv:// address or add tls=true to MONGO_URI.")
    if providers.data_policy() == "strict":
        allowed = providers._names("EVAL_ALLOWED_HOSTS")
        bad = [h for h in remote if not any(h == a or h.endswith("." + a) for a in allowed)]
        if bad:
            raise StoreUnavailable(f"The data policy is strict and MongoDB host {', '.join(bad)} is not in "
                                   f"EVAL_ALLOWED_HOSTS. Add it there (next to the model's host) to allow it on purpose.")
