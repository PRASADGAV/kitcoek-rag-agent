"""
Extraction quality checker for KITCOEK RAG — Phase C.

Runs automated checks on all extracted pages/documents and produces:
- extraction_quality_report.csv  — one row per page/document
- quality_summary.json           — aggregate stats
- warnings for: empty pages, nav-only, low text ratio, table issues, etc.

Usage:
    from src.extractor.quality_checks import QualityChecker
    checker = QualityChecker()
    report  = checker.run(raw_dir="data/raw")
    checker.save_report(report, out_dir="data/crawl_runs")

CLI:
    python -m src.extractor.quality_checks
"""

import csv
import glob
import json
import os
import re
from datetime import datetime, timezone
from typing import Any


# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_CHARS          = 100      # below this = too short
NAV_RATIO_THRESHOLD = 0.7     # if >70% lines are nav boilerplate → nav_only
DUPLICATE_THRESHOLD = 0.95    # cosine-like text similarity for near-duplicate detection
MIN_TABLE_COLS     = 2        # tables with 1 col probably broken

# KITCOEK nav boilerplate (same as html_extractor)
NAV_BOILERPLATE = {
    "about", "admissions", "departments", "academics", "exam cell",
    "alumni", "placement", "contact", "apply", "login", "home", "menu",
    "close", "search", "kit", "kitcoek", "read more", "know more",
    "click here", "apply now", "view all", "back", "next", "prev",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
}


class QualityChecker:
    """
    Checks all JSON files in data/raw/ for extraction quality issues.
    """

    def run(self, raw_dir: str = "data/raw") -> list[dict[str, Any]]:
        """
        Run quality checks on all extracted JSON files.
        Returns a list of report rows.
        """
        json_files = sorted(glob.glob(
            os.path.join(raw_dir, "**", "*.json"), recursive=True
        ))
        json_files = [f for f in json_files if "pdf_links" not in f]

        report_rows = []
        seen_hashes: dict[str, str] = {}  # hash → first file

        for file_path in json_files:
            row = self._check_file(file_path, seen_hashes)
            report_rows.append(row)

        return report_rows

    def _check_file(
        self,
        file_path: str,
        seen_hashes: dict[str, str],
    ) -> dict[str, Any]:
        """Run all checks on a single extracted JSON file."""
        row = {
            "file":          os.path.basename(file_path),
            "path":          file_path,
            "url":           "",
            "title":         "",
            "doc_type":      "",
            "char_count":    0,
            "word_count":    0,
            "content_hash":  "",
            "status":        "ok",
            "warnings":      [],
        }

        # ── Load file ──────────────────────────────────────────────────
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            row["status"]   = "error"
            row["warnings"] = [f"json_load_error:{str(e)[:80]}"]
            return row

        text     = data.get("text", "").strip()
        title    = data.get("title", "")
        url      = data.get("url", "")
        doc_type = data.get("doc_type", "unknown")

        row["url"]      = url
        row["title"]    = title[:120]
        row["doc_type"] = doc_type
        row["char_count"] = len(text)
        row["word_count"] = len(text.split())

        warnings = list(data.get("warnings", []))

        # ── Check 1: Empty or nearly empty ───────────────────────────
        if len(text) == 0:
            warnings.append("empty")
            row["status"] = "empty"
        elif len(text) < MIN_CHARS:
            warnings.append(f"too_short:{len(text)}chars")
            row["status"] = "warning"

        # ── Check 2: Navigation-only content ─────────────────────────
        if text and self._is_nav_only(text):
            warnings.append("navigation_only")
            row["status"] = "warning"

        # ── Check 3: Missing title ────────────────────────────────────
        if not title:
            warnings.append("missing_title")

        # ── Check 4: Missing URL ──────────────────────────────────────
        if not url:
            warnings.append("missing_url")

        # ── Check 5: Content hash and duplicate detection ─────────────
        content_hash = _hash_text(text)
        row["content_hash"] = content_hash

        if content_hash in seen_hashes:
            warnings.append(f"duplicate_of:{seen_hashes[content_hash]}")
            if row["status"] == "ok":
                row["status"] = "duplicate"
        elif text:
            seen_hashes[content_hash] = os.path.basename(file_path)

        # ── Check 6: PDF-specific checks ─────────────────────────────
        if doc_type == "pdf":
            total_pages     = data.get("total_pages", 0)
            extracted_pages = data.get("extracted_pages", 0)
            if total_pages > 0 and extracted_pages == 0:
                warnings.append("pdf_zero_extracted_pages")
                row["status"] = "warning"
            page_data = data.get("page_data", [])
            if page_data:
                blank = sum(1 for p in page_data if p.get("status") == "blank")
                if blank > 0:
                    warnings.append(f"pdf_blank_pages:{blank}")

        # ── Check 7: Low word count for non-empty ────────────────────
        if 0 < row["word_count"] < 30 and row["status"] == "ok":
            warnings.append("very_few_words")
            row["status"] = "warning"

        row["warnings"] = warnings
        if warnings and row["status"] == "ok":
            row["status"] = "warning"

        return row

    def _is_nav_only(self, text: str) -> bool:
        """Return True if text is predominantly nav boilerplate."""
        lines = [l.strip().lower() for l in text.splitlines() if l.strip()]
        if not lines:
            return True
        nav_count = sum(1 for l in lines if l in NAV_BOILERPLATE or len(l) <= 4)
        return nav_count / len(lines) > NAV_RATIO_THRESHOLD

    def save_report(
        self,
        rows: list[dict[str, Any]],
        out_dir: str = "data/crawl_runs",
    ) -> dict[str, Any]:
        """Save CSV report and JSON summary. Returns summary dict."""
        os.makedirs(out_dir, exist_ok=True)

        # ── CSV ────────────────────────────────────────────────────────
        csv_path = os.path.join(out_dir, "extraction_quality_report.csv")
        if rows:
            fieldnames = list(rows[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    # Flatten warnings list to string for CSV
                    r = dict(row)
                    r["warnings"] = "; ".join(r["warnings"]) if r["warnings"] else ""
                    writer.writerow(r)

        # ── Summary ────────────────────────────────────────────────────
        total      = len(rows)
        ok         = sum(1 for r in rows if r["status"] == "ok")
        empty      = sum(1 for r in rows if r["status"] == "empty")
        warnings   = sum(1 for r in rows if r["status"] == "warning")
        duplicates = sum(1 for r in rows if r["status"] == "duplicate")
        errors     = sum(1 for r in rows if r["status"] == "error")
        total_words = sum(r["word_count"] for r in rows)
        total_chars = sum(r["char_count"] for r in rows)

        summary = {
            "generated_at":  datetime.now(timezone.utc).isoformat(),
            "total_files":   total,
            "ok":            ok,
            "warnings":      warnings,
            "empty":         empty,
            "duplicates":    duplicates,
            "errors":        errors,
            "total_words":   total_words,
            "total_chars":   total_chars,
            "avg_chars":     total_chars // total if total else 0,
            "pass_rate":     f"{ok/total*100:.1f}%" if total else "0%",
        }

        summary_path = os.path.join(out_dir, "quality_summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        print(f"\n[quality] Report saved to {csv_path}")
        print(f"[quality] Total: {total}  OK: {ok}  Warn: {warnings}  "
              f"Empty: {empty}  Dup: {duplicates}  Error: {errors}")
        print(f"[quality] Total words: {total_words:,}  Avg chars/doc: {summary['avg_chars']:,}")

        return summary


# ── Helpers ────────────────────────────────────────────────────────────────────

def _hash_text(text: str) -> str:
    """SHA-256 hash of normalized text for deduplication."""
    import hashlib
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    checker = QualityChecker()
    rows    = checker.run(raw_dir="data/raw")
    summary = checker.save_report(rows, out_dir="data/crawl_runs")
    print(json.dumps(summary, indent=2))
