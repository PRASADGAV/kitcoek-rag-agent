"""
Phase C page pipeline — fetches + extracts all pages from the crawl store.

This is the main entry point that:
1. Reads pending URLs from the crawl manifest (SQLite)
2. Fetches each page (Playwright for JS / requests for static)
3. Extracts clean text with HTMLExtractor
4. Saves to data/raw/pages/ in the chunker-compatible JSON format
5. Updates crawl manifest with status + extracted_chars
6. Produces extraction quality report

Usage:
    python -m src.extractor.page_pipeline
    python -m src.extractor.page_pipeline --mode sitemap   # only from sitemap
    python -m src.extractor.page_pipeline --mode all       # full crawl then extract
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from .html_extractor   import HTMLExtractor
from .pdf_extractor    import PDFExtractor
from .office_extractor import extract_document
from .quality_checks   import QualityChecker
from ..scraper.url_normalizer import get_resource_type, is_document_url

RAW_PAGES_DIR = "data/raw/pages"
RAW_FILES_DIR = "data/raw/pdf_files"
RAW_PDFS_DIR  = "data/raw/pdfs"
CRAWL_DELAY   = float(os.getenv("CRAWLER_DELAY_SECONDS", "1.5"))
USER_AGENT    = os.getenv("CRAWLER_USER_AGENT", "KITCOEK-RAG-PrototypeBot/1.0")


class PagePipeline:
    """
    Fetches, extracts and saves pages from a list of URLs.
    Progress callback receives dict with counts for UI updates.
    """

    def __init__(self, progress_callback=None):
        self.html_extractor = HTMLExtractor()
        self.pdf_extractor  = PDFExtractor(ocr_enabled=True)
        self._progress_cb   = progress_callback
        self._stop          = False
        self._pw            = None
        self._browser       = None
        self._page          = None

        os.makedirs(RAW_PAGES_DIR,  exist_ok=True)
        os.makedirs(RAW_FILES_DIR,  exist_ok=True)
        os.makedirs(RAW_PDFS_DIR,   exist_ok=True)

    def process_url_list(self, urls: list[str]) -> dict:
        """
        Fetch and extract a list of URLs.
        Returns stats: {ok, failed, skipped, total_chars}
        """
        stats = {"ok": 0, "failed": 0, "skipped": 0,
                 "total_chars": 0, "total": len(urls)}

        for i, url in enumerate(urls):
            if self._stop:
                break

            res_type = get_resource_type(url)
            print(f"  [{i+1}/{len(urls)}] {res_type.upper():<6} {url[:75]}")

            try:
                if res_type == "pdf":
                    success = self._process_pdf_url(url)
                elif res_type in {"docx", "pptx", "xlsx", "csv"}:
                    success = self._process_office_url(url)
                else:
                    result = self._fetch_and_extract_html(url)
                    success = result is not None and result.get("char_count", 0) > 100
                    if success:
                        stats["total_chars"] += result["char_count"]

                if success:
                    stats["ok"] += 1
                else:
                    stats["failed"] += 1

            except Exception as e:
                print(f"    [ERROR] {e}")
                stats["failed"] += 1

            if self._progress_cb:
                self._progress_cb({**stats, "current_url": url, "index": i})

            time.sleep(CRAWL_DELAY)

        self._cleanup_playwright()
        return stats

    def process_from_sitemap(self) -> dict:
        """Fetch all URLs from the sitemap and extract them."""
        from ..scraper.discovery  import parse_sitemap
        from ..scraper.robots     import discover_sitemaps, RobotsPolicy

        robots  = RobotsPolicy("https://www.kitcoek.in/")
        robots.load()
        sitmaps = discover_sitemaps("https://www.kitcoek.in/", robots.sitemaps)

        urls = []
        for sm in sitmaps:
            entries = parse_sitemap(sm)
            urls.extend(e["url"] for e in entries)

        urls = list(dict.fromkeys(urls))   # deduplicate preserving order
        print(f"[pipeline] Processing {len(urls)} URLs from sitemap")
        return self.process_url_list(urls)

    def stop(self):
        self._stop = True

    # ── Fetch + extract ───────────────────────────────────────────────────────

    def _fetch_and_extract_html(self, url: str) -> dict | None:
        """Fetch a page and extract clean text. Save to data/raw/pages/."""
        # Try requests first (faster)
        html = None
        final_url = url
        try:
            r = requests.get(url, timeout=20,
                             headers={"User-Agent": USER_AGENT},
                             allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 500:
                html      = r.text
                final_url = r.url
        except Exception:
            pass

        # Playwright fallback for JS-heavy pages
        if not html or self._looks_empty(html):
            pw_result = self._fetch_playwright(url)
            if pw_result:
                html      = pw_result["html"]
                final_url = pw_result["final_url"]

        if not html:
            return None

        result = self.html_extractor.extract(html, url=final_url)

        if result["char_count"] < 80:
            return None

        # Save to data/raw/pages/
        record = self._make_page_record(result, url, final_url)
        self._save_page(record)
        print(f"    -> {result['extraction_method']} | "
              f"{result['word_count']}w | "
              f"{result['title'][:50]}")
        return result

    def _process_pdf_url(self, url: str) -> bool:
        """Download and extract a PDF from a URL."""
        try:
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": USER_AGENT},
                             stream=True)
            if r.status_code != 200:
                return False

            # Save to temp file
            fname    = _safe_filename(url)
            tmp_path = os.path.join(RAW_FILES_DIR, fname)
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            # Extract
            result = self.pdf_extractor.extract_file(tmp_path, source_url=url)
            if not result.success:
                print(f"    -> PDF extraction failed: {result.warnings}")
                return False

            # Save as JSON for chunker
            idx      = self._next_pdf_idx()
            out_path = os.path.join(RAW_PDFS_DIR, f"pdf_{idx:04d}.json")
            record   = {
                "url":          url,
                "title":        result.title,
                "text":         result.full_text,
                "doc_type":     "pdf",
                "total_pages":  result.total_pages,
                "page_data":    result.pages,
                "warnings":     result.warnings,
                "crawled_at":   datetime.now(timezone.utc).isoformat(),
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

            print(f"    -> PDF: {result.total_pages}pg | "
                  f"{result.extracted_pages}extracted | "
                  f"{len(result.full_text):,}c")
            return True

        except Exception as e:
            print(f"    -> PDF error: {e}")
            return False

    def _process_office_url(self, url: str) -> bool:
        """Download and extract an office document from a URL."""
        try:
            r = requests.get(url, timeout=30,
                             headers={"User-Agent": USER_AGENT},
                             stream=True)
            if r.status_code != 200:
                return False

            ext      = url.rsplit(".", 1)[-1].lower()
            fname    = _safe_filename(url)
            tmp_path = os.path.join(RAW_FILES_DIR, fname)

            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            result = extract_document(tmp_path, source_url=url)
            if not result or not result.get("success"):
                return False

            idx      = self._next_pdf_idx()
            out_path = os.path.join(RAW_PDFS_DIR, f"doc_{idx:04d}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"    -> {ext.upper()} | {len(result.get('text',''))}c")
            return True

        except Exception as e:
            print(f"    -> Office doc error: {e}")
            return False

    # ── Playwright ────────────────────────────────────────────────────────────

    def _fetch_playwright(self, url: str) -> dict | None:
        """Use Playwright to fetch JS-rendered page."""
        try:
            self._ensure_playwright()
            if self._browser == "failed":
                return None

            page = self._page
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(1500)
            except Exception:
                try:
                    resp = page.goto(url, wait_until="commit", timeout=15000)
                    page.wait_for_timeout(2000)
                except Exception:
                    return None

            # Scroll for lazy content
            try:
                page.evaluate("""
                    async () => {
                        for (let i = 0; i < 4; i++) {
                            window.scrollBy(0, window.innerHeight);
                            await new Promise(r => setTimeout(r, 300));
                        }
                        window.scrollTo(0, 0);
                    }
                """)
            except Exception:
                pass

            return {
                "html":      page.content(),
                "final_url": page.url,
                "status":    resp.status if resp else 200,
            }
        except Exception as e:
            print(f"    [pw] {e}")
            return None

    def _ensure_playwright(self):
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            ctx           = self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800},
            )
            self._page    = ctx.new_page()
            self._page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,mp4,mp3}",
                lambda route: route.abort(),
            )
        except Exception as e:
            print(f"[pipeline] Playwright unavailable: {e}")
            self._browser = "failed"

    def _cleanup_playwright(self):
        try:
            if self._page:    self._page.close()
            if self._browser and self._browser != "failed":
                self._browser.close()
            if self._pw:      self._pw.stop()
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_page_record(self, result: dict, orig_url: str, final_url: str) -> dict:
        return {
            "url":        final_url or orig_url,
            "title":      result.get("title", ""),
            "text":       result.get("text", ""),
            "doc_type":   "webpage",
            "headings":   result.get("headings", []),
            "tables":     result.get("tables", []),
            "breadcrumb": result.get("breadcrumb", []),
            "date":       result.get("published_date", ""),
            "word_count": result.get("word_count", 0),
            "warnings":   result.get("warnings", []),
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save_page(self, record: dict):
        """Save a page record as JSON in data/raw/pages/."""
        existing = [
            f for f in os.listdir(RAW_PAGES_DIR)
            if f.startswith("page_") and f.endswith(".json")
        ]
        idx      = len(existing) + 1
        out_path = os.path.join(RAW_PAGES_DIR, f"page_{idx:04d}.json")
        # Avoid duplicate filenames if they already exist
        while os.path.exists(out_path):
            idx += 1
            out_path = os.path.join(RAW_PAGES_DIR, f"page_{idx:04d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    def _next_pdf_idx(self) -> int:
        existing = [
            f for f in os.listdir(RAW_PDFS_DIR)
            if f.endswith(".json")
        ]
        return len(existing) + 1

    def _looks_empty(self, html: str) -> bool:
        """Heuristic: does the HTML contain very little visible text?"""
        import re
        # Strip tags
        text = re.sub(r"<[^>]+>", " ", html)
        text = " ".join(text.split())
        return len(text) < 200


def _safe_filename(url: str) -> str:
    import re
    name = re.sub(r"[^\w\-_.]", "_", url.split("//")[-1])
    name = re.sub(r"_+", "_", name)[:120]
    return name


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["sitemap", "all"], default="sitemap")
    args = parser.parse_args()

    pipeline = PagePipeline()

    if args.mode == "sitemap":
        stats = pipeline.process_from_sitemap()
    else:
        from src.scraper.recursive_crawler import RecursiveCrawler
        crawler = RecursiveCrawler(mode="full")
        crawler.run()
        stats = pipeline.process_from_sitemap()

    print(json.dumps(stats, indent=2))
