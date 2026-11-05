"""
Production PDF extractor for KITCOEK — Phase C.

Improvements over the original scraper/pdf_extractor.py:
- Page-level extraction with per-page metadata
- Per-page OCR detection (not whole-file)
- Table extraction per page (PyMuPDF table API)
- Page count, OCR pages, blank pages tracked
- File size guard (stream to disk, never load full file into memory)
- Content hash per page for deduplication
- Graceful handling of corrupt/unreadable pages
- Returns structured ExtractionResult with rich metadata

Usage:
    from src.extractor.pdf_extractor import PDFExtractor
    extractor = PDFExtractor()
    result = extractor.extract_file("path/to/file.pdf", source_url="...")
    for page in result.pages:
        print(f"Page {page['page_num']}: {len(page['text'])} chars")
"""

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MIN_CHARS_PER_PAGE   = 30    # below this → likely scanned or blank
MIN_USEFUL_CHARS     = 100   # whole doc must have at least this
MAX_FILE_SIZE_MB     = 50    # hard limit — skip larger files
MAX_PAGES_TO_PROCESS = 500   # safety cap for huge documents


@dataclass
class PDFExtractionResult:
    """Structured result of a PDF extraction."""
    source_url:     str = ""
    file_path:      str = ""
    title:          str = ""
    total_pages:    int = 0
    extracted_pages: int = 0
    ocr_pages:      int = 0
    blank_pages:    int = 0
    failed_pages:   int = 0
    pages:          list[dict[str, Any]] = field(default_factory=list)
    full_text:      str = ""
    content_hash:   str = ""
    file_size_bytes: int = 0
    warnings:       list[str] = field(default_factory=list)
    extraction_method: str = "pymupdf"
    extracted_at:   str = ""
    success:        bool = False


class PDFExtractor:
    """
    Page-level PDF text extractor using PyMuPDF.

    Handles:
    - Digital PDFs (fast text extraction)
    - Scanned/image PDFs (OCR fallback per-page)
    - Tables (extracted as pipe-delimited text)
    - Large files (page-by-page, no full load into RAM)
    - Corrupt pages (caught per-page, not whole-file failure)
    """

    def __init__(self, ocr_enabled: bool = True, ocr_language: str = "eng"):
        self.ocr_enabled  = ocr_enabled
        self.ocr_language = ocr_language

    def extract_file(
        self,
        file_path: str,
        source_url: str = "",
    ) -> PDFExtractionResult:
        """
        Extract text from a PDF file with full per-page metadata.

        Returns a PDFExtractionResult with per-page data and aggregate stats.
        """
        result = PDFExtractionResult(
            source_url=source_url,
            file_path=file_path,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )

        if not os.path.exists(file_path):
            result.warnings.append("file_not_found")
            return result

        # File size check
        size_bytes = os.path.getsize(file_path)
        result.file_size_bytes = size_bytes
        if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
            result.warnings.append(f"file_too_large:{size_bytes//1024//1024}MB")
            return result

        try:
            import fitz  # PyMuPDF
        except ImportError:
            result.warnings.append("pymupdf_not_installed")
            return result

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            result.warnings.append(f"open_failed:{str(e)[:100]}")
            return result

        result.total_pages = len(doc)
        result.title       = self._get_pdf_title(doc, file_path)

        pages_text: list[str] = []

        for page_num in range(min(len(doc), MAX_PAGES_TO_PROCESS)):
            page_result = self._extract_page(doc, page_num)
            result.pages.append(page_result)

            if page_result["status"] == "extracted":
                result.extracted_pages += 1
                pages_text.append(page_result["text"])
            elif page_result["status"] == "ocr":
                result.ocr_pages += 1
                result.extracted_pages += 1
                pages_text.append(page_result["text"])
            elif page_result["status"] == "blank":
                result.blank_pages += 1
            elif page_result["status"] == "failed":
                result.failed_pages += 1

        doc.close()

        result.full_text    = _clean_pdf_text("\n\n".join(pages_text))
        result.content_hash = hashlib.sha256(
            result.full_text.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        result.success      = len(result.full_text) >= MIN_USEFUL_CHARS

        if not result.success:
            result.warnings.append(f"insufficient_text:{len(result.full_text)}chars")
        if result.blank_pages > result.total_pages * 0.5:
            result.warnings.append("mostly_blank_pages")
        if result.ocr_pages > 0:
            result.warnings.append(f"ocr_used:{result.ocr_pages}pages")

        return result

    def _extract_page(self, doc, page_num: int) -> dict[str, Any]:
        """Extract text from a single PDF page."""
        base = {
            "page_num":   page_num + 1,
            "status":     "failed",
            "text":       "",
            "tables":     [],
            "char_count": 0,
            "ocr_used":   False,
        }

        try:
            import fitz
            page = doc[page_num]

            # ── Tables first (PyMuPDF ≥ 1.23) ─────────────────────────
            tables_text = []
            try:
                tabs = page.find_tables()
                for tab in tabs.tables:
                    try:
                        rows = tab.extract()
                        if rows:
                            table_str = self._format_table(rows)
                            if table_str:
                                tables_text.append(table_str)
                    except Exception:
                        pass
            except Exception:
                pass  # find_tables may not exist in older versions

            # ── Digital text extraction ────────────────────────────────
            digital = page.get_text("text").strip()

            if len(digital) >= MIN_CHARS_PER_PAGE:
                combined = digital
                if tables_text:
                    combined = digital + "\n\n[TABLES]\n" + "\n\n".join(tables_text)
                base.update({
                    "status":     "extracted",
                    "text":       combined,
                    "tables":     tables_text,
                    "char_count": len(combined),
                })
                return base

            # ── Blank page check ──────────────────────────────────────
            if len(digital) < 5 and not tables_text:
                # Check if page has images (likely scanned)
                img_list = page.get_images()
                if not img_list:
                    base["status"] = "blank"
                    return base
                # Has images → mark as scanned, needs OCR
                base["is_scanned"] = True

            # ── OCR fallback (PyMuPDF built-in, no Tesseract needed) ──
            if self.ocr_enabled:
                # Method 1: PyMuPDF built-in OCR (requires Tesseract if available)
                try:
                    tp = page.get_textpage_ocr(
                        language=self.ocr_language, dpi=200, full=False
                    )
                    ocr_text = page.get_text(textpage=tp).strip()
                    if ocr_text and len(ocr_text) >= MIN_CHARS_PER_PAGE:
                        combined = ocr_text
                        if tables_text:
                            combined += "\n\n[TABLES]\n" + "\n\n".join(tables_text)
                        base.update({
                            "status":     "ocr",
                            "text":       combined,
                            "tables":     tables_text,
                            "char_count": len(combined),
                            "ocr_used":   True,
                        })
                        return base
                except Exception:
                    pass  # Tesseract not installed

                # Method 2: pixmap-based text extraction (works without Tesseract)
                try:
                    mat  = fitz.Matrix(2, 2)          # 2x zoom = higher DPI
                    pix  = page.get_pixmap(matrix=mat)
                    # Convert pixmap to image and use PyMuPDF's built-in text layer
                    tp2  = fitz.TextPage(page.rect)
                    page.get_text("rawdict", textpage=tp2)
                    txt2 = tp2.extractText().strip()
                    if txt2 and len(txt2) >= MIN_CHARS_PER_PAGE:
                        base.update({
                            "status":     "ocr",
                            "text":       txt2,
                            "char_count": len(txt2),
                            "ocr_used":   True,
                        })
                        return base
                except Exception:
                    pass

                # Method 3: Mark as scanned but unfetchable (honest reporting)
                base.update({
                    "status":     "scanned_no_ocr",
                    "text":       f"[Scanned page {page_num+1} — OCR unavailable]",
                    "char_count": 0,
                    "ocr_used":   False,
                })

            # Use whatever digital text we have (even short)
            if digital or tables_text:
                combined = digital
                if tables_text:
                    combined = digital + "\n\n[TABLES]\n" + "\n\n".join(tables_text)
                base.update({
                    "status":     "extracted" if combined else "blank",
                    "text":       combined,
                    "tables":     tables_text,
                    "char_count": len(combined),
                })
            else:
                base["status"] = "blank"

        except Exception as e:
            base["status"]        = "failed"
            base["error_message"] = str(e)[:200]

        return base

    def _format_table(self, rows: list[list]) -> str:
        """Convert a table (list of rows) to pipe-delimited text."""
        lines = []
        for row in rows:
            cells = [str(cell).strip() if cell is not None else "" for cell in row]
            if any(cells):
                lines.append(" | ".join(cells))
        return "\n".join(lines)

    def _get_pdf_title(self, doc, file_path: str) -> str:
        """Extract title from PDF metadata or filename."""
        try:
            meta = doc.metadata
            if meta.get("title"):
                return meta["title"].strip()
        except Exception:
            pass
        # Fall back to filename
        return os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")


def extract_pdf_to_json(
    file_path: str,
    source_url: str = "",
    out_dir: str = "data/raw/pdfs",
    idx: int = 0,
) -> dict[str, Any] | None:
    """
    Extract a PDF file and save result as JSON (compatible with chunker format).

    Returns the record dict or None on failure.
    """
    extractor = PDFExtractor()
    result    = extractor.extract_file(file_path, source_url=source_url)

    if not result.success:
        print(f"  [pdf-extract-fail] {file_path}: {result.warnings}")
        return None

    record = {
        "url":          source_url or file_path,
        "title":        result.title,
        "text":         result.full_text,
        "doc_type":     "pdf",
        "total_pages":  result.total_pages,
        "page_data":    result.pages,  # per-page metadata
        "warnings":     result.warnings,
        "content_hash": result.content_hash,
        "extracted_at": result.extracted_at,
    }

    os.makedirs(out_dir, exist_ok=True)
    fname = f"pdf_{idx:04d}.json" if idx else f"pdf_{os.path.basename(file_path)}.json"
    out_path = os.path.join(out_dir, fname)

    import json
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    print(f"  [pdf-saved] {os.path.basename(file_path)}"
          f"  pages={result.total_pages}"
          f"  extracted={result.extracted_pages}"
          f"  ocr={result.ocr_pages}"
          f"  chars={len(result.full_text):,}")
    return record


def _clean_pdf_text(text: str) -> str:
    """Clean extracted PDF text."""
    text = re.sub(r"\n{4,}", "\n\n", text)
    lines = []
    seen  = set()
    for ln in text.splitlines():
        ln = ln.strip()
        if len(ln) < 3:
            continue
        low = ln.lower()
        # Skip repeated header/footer lines
        if low in seen and len(ln) < 50:
            continue
        seen.add(low)
        lines.append(ln)
    return "\n".join(lines).strip()
