"""Pieces every screen uses: column formats, the status markers, the page header and its filters, and cards."""
from __future__ import annotations

import html

import streamlit as st

from eval import context, judge, store
from eval import reality_check as rc

from .state import S


PCT = st.column_config.NumberColumn(format="percent")
BAR = st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)


# Vericap run check
MARK = {rc.FOUND: "🟢", rc.PARTIAL: "🟠", rc.MISSED: "🔴", rc.WRONG: "🔴", rc.REVIEW: "⚪", "Not checked": "⚪",
        rc.LABELLED: "🟢", rc.NOT_FLAGGED: "🟢"}
QUOTE_LABEL = {"Real": "Found on the page", "Partly found": "Partly found", "Wrong page": "Wrong page",
               "Not found": "Not found", "Not checked": "Not checked"}
RESULT_MARK = {"Pass": "✅ Pass", "Fail": "❌ Fail", "Unknown": "❔ Unknown", "Info": "ℹ️ Info"}
LEGEND = "🟢 found, or a non-issue left alone · 🟠 partially found · 🔴 missed, or a non-issue flagged · ⚪ needs review"


def sticky(widget, label: str, name: str, options: list | None = None, **kw):
    """A filter that keeps its value when you move between screens. With options it is a select box,
    without it a checkbox. Changing it reruns the page so everything above it uses the new value."""
    if options is None:
        current = bool(st.session_state.get(name, False))
    else:
        current = st.session_state.get(name) if st.session_state.get(name) in options else options[0]
    if f"w_{name}" not in st.session_state or (options is not None and st.session_state[f"w_{name}"] not in options):
        st.session_state[f"w_{name}"] = current
    value = widget(label, key=f"w_{name}", **kw) if options is None else widget(label, options, key=f"w_{name}", **kw)
    if value != current:
        st.session_state[name] = value
        st.rerun()
    return value


def page_header(title: str, intro: str, room_filter: bool = False):
    """The title of a screen, one sentence on what it is for, and the filters that apply to it."""
    st.header(title)
    st.write(intro)
    cols = st.columns(4)
    with cols[0]:
        sticky(st.selectbox, "Answer key", "answer_key", S.keys, format_func=store.snapshot_label,
               help="Frozen snapshots never change. The working draft holds uploads and accepted candidates that "
                    "are not frozen yet.")
    if room_filter:
        with cols[1]:
            sticky(st.selectbox, "Data room", "room_filter", ["All"] + S.rooms)


def case_card(c: dict):
    st.markdown(f"**{c['case_id']}** · {c['classification']} · {c['severity']} · "
                f"{'report' if c['report'] else 'do not report'} · {c['set']}"
                + (" · ambiguous" if c["ambiguous"] else ""))
    st.write(c["summary"])
    st.caption("Claims compared")
    st.write(c["claims_compared"])
    st.caption("Citations")
    st.write("\n".join(f"- {x['raw']}" for x in c["citations"]))
    st.caption("Explanation")
    st.write(c["explanation"])
    if c["alternative_readings"]:
        st.caption("Alternative readings")
        st.write(c["alternative_readings"])


def _safe(text: str) -> str:
    return html.escape(text or "").replace("$", "&#36;")


def page_excerpt(text: str, quote: str, radius: int = 700) -> str:
    """A page as HTML, cut around the quoted words, with the quote in bold when it is there word for word."""
    text = text or ""
    at = text.lower().find((quote or "").lower()) if quote else -1
    if at < 0:
        body = _safe(judge.excerpt(text, quote or "", radius) if quote else text[:2 * radius] + (" ..." if len(text) > 2 * radius else ""))
    else:
        start, end = max(0, at - radius), min(len(text), at + len(quote) + radius)
        body = (("... " if start else "") + _safe(text[start:at]) + "<b>" + _safe(text[at:at + len(quote)]) + "</b>"
                + _safe(text[at + len(quote):end]) + (" ..." if end < len(text) else ""))
    return f'<div style="white-space:pre-wrap;font-size:0.85rem;border-left:3px solid #bbb;padding-left:0.6rem">{body}</div>'


def check_finding_card(f: dict, chunks: dict):
    st.markdown(f"**{f['finding_id']}** · {f['classification'] or f['raw_classification'] or '(no class)'} · "
                f"{f['severity'] or f['raw_severity'] or '(no severity)'}")
    st.write(f["summary"])
    if f["claims_compared"]:
        st.caption("Claims compared")
        st.write(f["claims_compared"])
    st.caption("Citations, each with its quote check")
    for c, q in zip(f["citations"], rc.own_quotes(f, chunks)):
        st.write(f"- {c['raw']} — {QUOTE_LABEL[q]}")
    if not f["citations"]:
        st.write("- (none)")
    if f["explanation"]:
        st.caption("Explanation")
        st.write(f["explanation"])


def case_facts(c: dict):
    facts = context.load_facts(c["data_room"])
    mine = [f for f in facts if f["fact_id"] in (c.get("register_ids") or [])]
    st.caption("Linked facts")
    if not mine:
        st.write(f"{', '.join(c.get('register_ids') or []) or 'None'}. "
                 + ("The fact sheet is not uploaded yet." if not facts else ""))
    for f in mine:
        st.write(f"- {f['fact_id']} · {f.get('subject')} · {f.get('value')} · {f.get('value_status')}. "
                 f"Change history: {context.chain_text(f, facts)}")
