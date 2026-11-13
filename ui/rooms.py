"""The Data rooms screen: every data room with its numbers, and adding a new one."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from eval import data_room, store
from eval import reality_check as rc

from .common import page_header
from .state import S, stamp


# Data rooms
@st.cache_data(show_spinner=False)
def _page_counts(stamp: float, room_name: str) -> dict[str, int]:
    return {doc: len(pages) for doc, pages in store.load_chunks(room_name).items()}


def _room_rows() -> list[dict]:
    checks = rc.list_checks()
    out = []
    for r in S.rooms:
        docs = [d for (rm, _), d in S.documents.items() if rm == r]
        text = _page_counts(stamp(), r)
        pages = sum(text.values())
        mine = [c for c in S.cases if c["data_room"] == r]
        ready = "Ready" if text and mine else "Documents only: no ground-truth case yet" if text else "No document text stored"
        out.append({"Data room": r, "Status": ready, "Documents": len(text) or len(docs), "Pages": pages,
                    "Ground-truth cases": len(mine), "Reportable": sum(c["report"] for c in mine),
                    "Non-issue": sum(not c["report"] for c in mine), "Critical": sum(c["severity"] == "Critical" for c in mine),
                    "Vericap checks": sum(c["data_room"] == r for c in checks),
                    "Baseline runs": sum(x["run"]["data_room"] == r and x["run"]["source"] == "Baseline model" for x in S.results)})
    return out


def screen_rooms():
    page_header("Data rooms", "Every data room the tool knows, and the place to add a new one. A new data room shows "
                              "up in every list as soon as its documents are read.")
    table = _room_rows()
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    if S.rooms:
        with st.expander("Documents of a data room"):
            pick = st.selectbox("Data room", S.rooms, key="rooms_docs")
            text = store.load_chunks(pick)
            listed = {doc: d for (rm, doc), d in S.documents.items() if rm == pick}
            st.dataframe(pd.DataFrame([{"Document": doc, "Title": (listed.get(doc) or {}).get("title", ""),
                                        "Type": (listed.get(doc) or {}).get("type", ""),
                                        "Pages read": len(text.get(doc, {})), "In the document list": "Yes" if doc in listed else "No"}
                                       for doc in sorted(set(text) | set(listed))]), hide_index=True, width="stretch")

    st.subheader("Add a data room")
    st.write("Give it a name and upload its PDFs, or one zip that holds them. Each page is read once and stored as "
             "text, so quotes can be checked and pages can be shown to the model.")
    with st.form("add_room", clear_on_submit=False):
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("Data room name", placeholder="HTC03", help="Capital letters and digits, starting with a "
                             "letter. Case IDs for this room start with it, for example HTC03-001.")
        files = c2.file_uploader("PDFs, or one zip", type=["pdf", "zip"], accept_multiple_files=True)
        replace = st.checkbox("Replace the documents already stored under this name", value=False,
                              help="Off: the upload is added to what is stored, and a document with the same ID is replaced. "
                                   "On: everything stored for this data room is replaced by the upload.")
        go = st.form_submit_button("Read the documents and add the data room", type="primary")
    if go:
        try:
            with st.spinner("Reading the documents. Scanned pages take longer."):
                out = data_room.add_files(name, {f.name: f.getvalue() for f in files or []}, replace=replace)
        except (ValueError, FileNotFoundError) as e:
            st.error(str(e))
        except Exception as e:                                # a broken PDF must not crash the page
            st.error(f"The documents could not be read: {e}")
        else:
            st.cache_data.clear()
            pages = sum(d["pages"] for d in out["documents"])
            st.success(f"{out['room']} is added: {len(out['documents'])} documents, {pages} pages, stored in {out['stored']}. "
                       f"It is now in every data room list.")
            st.dataframe(pd.DataFrame([{"Document": d["doc_id"], "File": d["file"], "Pages": d["pages"], "Read by OCR": d["ocr"],
                                        "Pages that could not be read": ", ".join(map(str, d["unreadable"]))}
                                       for d in out["documents"]]), hide_index=True, width="stretch")
            if out["renamed"]:
                st.caption("Files without a document ID were numbered: " + "; ".join(f"{k} is {v.split('_')[0]}" for k, v in out["renamed"].items()) + ".")
            if any(d["unreadable"] for d in out["documents"]):
                st.warning("Some pages could not be read. They are scans, and no OCR program is installed on this machine.")
            if out["problems"]:
                st.warning("The copy in the document store could not be verified, so local copies were kept: " + "; ".join(out["problems"][:3]))
            st.info("Next: add this data room's cases to the Ground Truth tab of the evaluation sheet (and its documents "
                    "to the Documents tab), then upload the sheet. Until then a Vericap run on it is checked against the "
                    "documents only.")
