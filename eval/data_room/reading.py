"""Reads one PDF page by page: the text layer when there is one, OCR (tesseract) for scanned pages."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


MIN_TEXT = 40          # a page with fewer characters than this is treated as a scan


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def _page_count(pdf: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf)).pages)


def read_pdf(pdf: Path) -> list[dict]:
    """[{page, text, read_by}] for one PDF. read_by is 'text', 'ocr' or 'unreadable'."""
    have_pdftotext, have_ocr = shutil.which("pdftotext"), shutil.which("tesseract") and shutil.which("pdftoppm")
    n = _page_count(pdf)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, n + 1):
            text = ""
            if have_pdftotext:
                text = _run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(pdf), "-"])
            else:
                from pypdf import PdfReader
                text = PdfReader(str(pdf)).pages[page - 1].extract_text() or ""
            read_by = "text"
            if len(text.strip()) < MIN_TEXT:
                read_by = "unreadable"
                if have_ocr:
                    stem = Path(tmp) / f"p{page}"
                    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", str(page), "-l", str(page),
                                    "-singlefile", str(pdf), str(stem)], capture_output=True, check=False)
                    ocr = _run(["tesseract", f"{stem}.png", "-", "--psm", "6"])
                    if len(ocr.strip()) >= MIN_TEXT:
                        text, read_by = ocr, "ocr"
            out.append({"page": page, "text": text.replace("\f", "").strip(), "read_by": read_by})
    return out
