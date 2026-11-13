"""Adds the documents of a data room to the tool, so quotes can be checked against the real text.

    python -m eval add-data-room path/to/HTC03_Some_Project.zip
    python -m eval add-data-room path/to/folder --room HTC03

Each PDF must start with its document ID (DOC-01_..., DOC-02_...). Every page is read once:
pages with a text layer through pdftotext, scanned pages through OCR (tesseract).

Where the result goes:
- With MONGO_URI set, the page text is written to MongoDB (eval/doc_store.py), and the PDFs too when
  EVAL_STORE_PDFS=1. Everything is read back and compared. Only when that passes are no local copies
  kept (--keep-local keeps them). When it fails, the local copies are written and the failure is reported.
- Without MONGO_URI, the result is stored as data_room/<room>/chunks.json, one entry per page:
  {doc_id, page, text, read_by}, and the PDFs are copied to data_room/<room>/documents/.

    python -m eval move-to-mongo [--rooms HTC01 HTC02] [--with-pdfs]

moves rooms that are already in data_room/ to MongoDB the same way, and deletes each local folder after
its copy is verified."""
from __future__ import annotations

from .adding import ROOM_NAME, add_files, register_documents  # noqa: F401
from .ingest import add  # noqa: F401
from .moving import local_rooms, move_to_mongo  # noqa: F401
from .quotes import check_answer_key  # noqa: F401
from .reading import read_pdf  # noqa: F401



