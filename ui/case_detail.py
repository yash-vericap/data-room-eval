"""Ground-truth cases as a list of toggles, most severe first."""
from __future__ import annotations

import streamlit as st

from .common import MARK
from .case_view import case_view, room_index


def _label(r: dict) -> str:
    flags = [t for t, on in (("set by hand", r["manual"]), ("decided by rule", r.get("by_rule")), ("stale", r["stale"])) if on]
    text = f"{MARK[r['status']]} {r['case_id']} · {r['severity']} · {r['summary'][:110]}" + ("…" if len(r["summary"]) > 110 else "")
    return (text + (f"  ({', '.join(flags)})" if flags else "")).replace("$", "\\$")


def case_list(check: dict, rows: list[dict], cmp: dict, chunks: dict, by_f: dict, empty: str):
    if not rows:
        st.caption(empty)
        return
    index = room_index(check["data_room"])
    for r in sorted(rows, key=lambda r: (-r["weight"], r["case_id"])):
        with st.expander(_label(r)):
            case_view(check, r, cmp, chunks, by_f, index)
