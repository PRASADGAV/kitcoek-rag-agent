"""
Office document extractor — DOCX, PPTX, XLSX, CSV, TXT.

Handles:
- DOCX: headings, paragraphs, tables, hyperlinks (python-docx)
- PPTX: slide number, title, text blocks, tables (python-pptx)
- XLSX/XLS: sheet name, headers, rows as readable text (openpyxl)
- CSV: headers + rows
- TXT: plain text

Each extractor returns a dict compatible with the chunker's expected format:
  {url, title, text, doc_type, page_data, warnings, content_hash, extracted_at}
"""

import csv
import hashlib
import io
import os
import re
from datetime import datetime, timezone
from typing import Any


def extract_docx(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """Extract text from a DOCX file preserving heading hierarchy and tables."""
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return _error_result(source_url, file_path, "python-docx not installed")

    warnings = []
    parts    = []

    try:
        doc = Document(file_path)
    except Exception as e:
        return _error_result(source_url, file_path, str(e))

    # Title from core properties
    title = ""
    try:
        title = doc.core_properties.title or ""
    except Exception:
        pass
    if not title:
        title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")

    # Paragraphs
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name.lower() if para.style else ""
        if "heading" in style:
            level = re.search(r"(\d)", style)
            prefix = "#" * int(level.group(1)) if level else "#"
            parts.append(f"{prefix} {text}")
        else:
            parts.append(text)

    # Tables
    for i, table in enumerate(doc.tables):
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            parts.append(f"[TABLE {i+1}]\n" + "\n".join(rows))

    full_text = "\n\n".join(parts)

    if len(full_text) < 50:
        warnings.append("insufficient_text")

    return _make_result(source_url, file_path, title, full_text, "docx", warnings)


def extract_pptx(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """Extract text from a PPTX file preserving slide structure."""
    try:
        from pptx import Presentation
    except ImportError:
        return _error_result(source_url, file_path, "python-pptx not installed")

    warnings  = []
    parts     = []
    page_data = []

    try:
        prs = Presentation(file_path)
    except Exception as e:
        return _error_result(source_url, file_path, str(e))

    title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")

    for slide_num, slide in enumerate(prs.slides, start=1):
        slide_parts = []

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                text = para.text.strip()
                if text:
                    slide_parts.append(text)

        # Tables on the slide
        for shape in slide.shapes:
            if shape.has_table:
                rows = []
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    slide_parts.append("[TABLE]\n" + "\n".join(rows))

        if slide_parts:
            slide_text = f"[Slide {slide_num}]\n" + "\n".join(slide_parts)
            parts.append(slide_text)
            page_data.append({
                "page_num": slide_num,
                "text":     "\n".join(slide_parts),
                "char_count": sum(len(p) for p in slide_parts),
            })

    full_text = "\n\n".join(parts)
    if len(full_text) < 50:
        warnings.append("insufficient_text")

    result = _make_result(source_url, file_path, title, full_text, "pptx", warnings)
    result["page_data"] = page_data
    return result


def extract_xlsx(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """Extract text from an XLSX file preserving sheet/table structure."""
    try:
        import openpyxl
    except ImportError:
        return _error_result(source_url, file_path, "openpyxl not installed")

    warnings = []
    parts    = []

    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    except Exception as e:
        return _error_result(source_url, file_path, str(e))

    title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")

    for sheet_name in wb.sheetnames:
        ws   = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(c for c in cells if c and c != "None"):
                rows.append(" | ".join(c for c in cells if c != "None"))
        if rows:
            parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows[:500]))

    wb.close()
    full_text = "\n\n".join(parts)

    if len(full_text) < 20:
        warnings.append("insufficient_text")

    return _make_result(source_url, file_path, title, full_text, "xlsx", warnings)


def extract_csv(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """Extract text from a CSV file."""
    warnings = []
    rows     = []

    try:
        with open(file_path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 1000:  # cap at 1000 rows
                    warnings.append("truncated:>1000rows")
                    break
                if any(cell.strip() for cell in row):
                    rows.append(" | ".join(cell.strip() for cell in row))
    except Exception as e:
        return _error_result(source_url, file_path, str(e))

    title     = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
    full_text = "\n".join(rows)

    if len(full_text) < 20:
        warnings.append("insufficient_text")

    return _make_result(source_url, file_path, title, full_text, "csv", warnings)


def extract_txt(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """Extract text from a plain text file."""
    warnings = []
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as e:
        return _error_result(source_url, file_path, str(e))

    title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
    if len(text) < 20:
        warnings.append("insufficient_text")

    return _make_result(source_url, file_path, title, text, "txt", warnings)


def extract_document(file_path: str, source_url: str = "") -> dict[str, Any] | None:
    """
    Auto-detect file type and extract.
    Returns None if the file type is unsupported.
    """
    ext = os.path.splitext(file_path)[1].lower()
    extractors = {
        ".docx": extract_docx,
        ".doc":  extract_docx,   # python-docx handles both
        ".pptx": extract_pptx,
        ".ppt":  extract_pptx,
        ".xlsx": extract_xlsx,
        ".xls":  extract_xlsx,
        ".csv":  extract_csv,
        ".txt":  extract_txt,
    }
    fn = extractors.get(ext)
    if fn:
        return fn(file_path, source_url)
    return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_result(
    source_url: str,
    file_path: str,
    title: str,
    text: str,
    doc_type: str,
    warnings: list[str],
) -> dict[str, Any]:
    text = _clean_text(text)
    return {
        "url":          source_url or file_path,
        "title":        title,
        "text":         text,
        "doc_type":     doc_type,
        "content_hash": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16],
        "file_size":    os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        "warnings":     warnings,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "success":      len(text) >= 50,
    }


def _error_result(source_url: str, file_path: str, error: str) -> dict[str, Any]:
    title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
    return {
        "url":      source_url or file_path,
        "title":    title,
        "text":     "",
        "doc_type": os.path.splitext(file_path)[1].lstrip("."),
        "warnings": [f"extraction_error:{error[:100]}"],
        "success":  False,
    }


def _clean_text(text: str) -> str:
    """Basic cleanup: collapse whitespace, remove blank lines."""
    text = re.sub(r"\n{4,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\t+", " ", text)
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 2]
    return "\n".join(lines).strip()
