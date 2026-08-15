"""
PDF extractor for the KITCOEK RAG Agent.

Strategy:
  1. Try PyMuPDF text extraction first (fast, works for digital PDFs).
  2. If a page yields < 20 chars (scanned/image PDF), fall back to
     PyMuPDF OCR via Tesseract (fitz.Page.get_textpage_ocr).
  3. Skip pages/files where OCR is also empty (charts, blank pages).

Requirements:
    pip install pymupdf requests
    # Tesseract OCR must be installed on the system for the OCR fallback:
    # Windows: https://github.com/UB-Mannheim/tesseract/wiki
    # Once installed, make sure `tesseract` is on PATH

Usage:
    python -m src.scraper.pdf_extractor
"""

import json
import os
import re
import time
from urllib.parse import urlparse

import fitz          # PyMuPDF >= 1.23
import requests

from . import config

# Minimum chars per page to trust digital extraction (below → try OCR)
MIN_CHARS_PER_PAGE = 20


def _safe_filename(url: str) -> str:
    name = os.path.basename(urlparse(url).path) or "file.pdf"
    return name.replace(" ", "_")


def _clean_pdf_text(text: str) -> str:
    """Basic cleanup of extracted PDF text."""
    # Remove excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n", text)
    # Remove lines that are just page numbers or single chars
    lines = [ln for ln in text.splitlines() if len(ln.strip()) > 2]
    return "\n".join(lines).strip()


def _extract_text_from_pdf(path: str) -> str:
    """
    Extract text from a PDF file.
    Falls back to OCR page-by-page when digital extraction fails.
    """
    try:
        doc = fitz.open(path)
    except Exception as e:
        return ""

    pages_text: list[str] = []
    ocr_used = False

    for page_num, page in enumerate(doc):
        # --- Digital extraction first ---
        digital = page.get_text("text").strip()

        if len(digital) >= MIN_CHARS_PER_PAGE:
            pages_text.append(digital)
            continue

        # --- Fallback: OCR via Tesseract ---
        try:
            tp = page.get_textpage_ocr(language="eng", dpi=200, full=False)
            ocr_text = page.get_text(textpage=tp).strip()
            if ocr_text:
                pages_text.append(ocr_text)
                ocr_used = True
            # If OCR also fails, skip this page silently
        except Exception:
            # Tesseract not installed or page is truly blank
            if digital:
                pages_text.append(digital)

    doc.close()

    combined = "\n\n".join(pages_text)
    if ocr_used:
        print(f"    [ocr-used] {os.path.basename(path)}")
    return _clean_pdf_text(combined)


def extract_pdfs(re_extract_empty: bool = True):
    """
    Download and extract text from all PDFs in pdf_links.json.

    Args:
        re_extract_empty: If True, re-try PDFs that previously yielded
                          empty text (catches scanned PDFs on retry).
    """
    pdf_list_path = os.path.join("data", "raw", "pdf_links.json")
    if not os.path.exists(pdf_list_path):
        print("[pdf_extractor] No pdf_links.json found — run crawler first.")
        return

    with open(pdf_list_path, "r", encoding="utf-8") as f:
        pdf_urls = json.load(f)

    os.makedirs(config.RAW_PDFS_DIR,      exist_ok=True)
    os.makedirs(config.RAW_PDF_FILES_DIR, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})

    total   = len(pdf_urls)
    saved   = 0
    skipped = 0

    for i, url in enumerate(pdf_urls, start=1):
        filename       = _safe_filename(url)
        local_pdf_path = os.path.join(config.RAW_PDF_FILES_DIR, filename)
        out_path       = os.path.join(config.RAW_PDFS_DIR, f"pdf_{i:04d}.json")

        # If already extracted and non-empty, skip unless re_extract_empty
        if os.path.exists(out_path):
            existing = json.load(open(out_path, encoding="utf-8"))
            if len(existing.get("text", "")) > 100:
                print(f"  [skip:exists] ({i}/{total}) {filename}")
                saved += 1
                continue
            if not re_extract_empty:
                print(f"  [skip:empty-exists] ({i}/{total}) {filename}")
                skipped += 1
                continue
            print(f"  [retry:was-empty] ({i}/{total}) {filename}")

        # Download if not on disk
        if not os.path.exists(local_pdf_path):
            try:
                resp = session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
                resp.raise_for_status()
                with open(local_pdf_path, "wb") as f:
                    f.write(resp.content)
            except requests.RequestException as e:
                print(f"  [error:download] ({i}/{total}) {url} -> {e}")
                skipped += 1
                continue

        # Extract text (with OCR fallback)
        text = _extract_text_from_pdf(local_pdf_path)

        if not text.strip():
            print(f"  [empty] ({i}/{total}) {filename} — no text extracted")
            skipped += 1
            # Still write an empty record so we don't retry forever
            record = {"url": url, "title": filename, "text": "", "doc_type": "pdf"}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            continue

        record = {
            "url":      url,
            "title":    filename,
            "text":     text,
            "doc_type": "pdf",
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        saved += 1
        print(f"  [saved] ({i}/{total}) {filename}  |  {len(text):,} chars")
        time.sleep(config.REQUEST_DELAY_SECONDS)

    print(f"\n[pdf_extractor] Done. Saved={saved}, Skipped/empty={skipped}")


if __name__ == "__main__":
    extract_pdfs()
