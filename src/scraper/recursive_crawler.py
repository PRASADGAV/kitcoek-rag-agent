"""
Recursive BFS crawler for KITCOEK website.

Replaces the old static URL list approach with genuine recursive discovery:
- Starts from seed URLs
- Discovers all internal links recursively (BFS)
- Parses sitemaps
- Downloads documents (PDF, DOCX, etc.)
- Records every URL in crawl manifest (SQLite)
- Produces coverage report

Usage:
    from src.scraper.recursive_crawler import RecursiveCrawler
    crawler = RecursiveCrawler()
    crawler.run()

CLI:
    python -m src.scraper.recursive_crawler --mode full
    python -m src.scraper.recursive_crawler --mode discover
"""

import hashlib
import json
import os
import re
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .crawl_store import CrawlStore, _make_run_id
from .discovery import (
    extract_links_from_html,
    extract_links_from_playwright_page,
    parse_sitemap,
)
from .robots import RobotsPolicy, discover_sitemaps
from .url_normalizer import (
    normalize_url, is_allowed_host, is_document_url,
    ALLOWED_HOSTS, get_resource_type,
)

# ── Configuration (from env or defaults) ─────────────────────────────────────
ROOT_URL         = os.getenv("WEBSITE_ROOT_URL",      "https://www.kitcoek.in/")
CRAWLER_DELAY    = float(os.getenv("CRAWLER_DELAY_SECONDS",   "1.0"))
CRAWLER_TIMEOUT  = int(os.getenv("CRAWLER_TIMEOUT_SECONDS",   "30"))
MAX_DEPTH        = int(os.getenv("CRAWLER_MAX_DEPTH",         "6"))
MAX_PAGES        = int(os.getenv("CRAWLER_MAX_PAGES",         "500"))
MAX_FILES        = int(os.getenv("CRAWLER_MAX_FILES",         "300"))
MAX_FILE_MB      = int(os.getenv("CRAWLER_MAX_FILE_MB",       "50"))
RESPECT_ROBOTS   = os.getenv("CRAWLER_RESPECT_ROBOTS",        "true").lower() == "true"
USER_AGENT       = os.getenv("CRAWLER_USER_AGENT",
                              "KITCOEK-RAG-PrototypeBot/1.0")

RAW_PAGES_DIR    = os.getenv("RAW_PAGES_DIR",  "data/raw/pages")
RAW_FILES_DIR    = os.getenv("RAW_FILES_DIR",  "data/raw/pdf_files")
CRAWL_RUNS_DIR   = "data/crawl_runs"


class RecursiveCrawler:
    """
    BFS recursive crawler that discovers all public pages on kitcoek.in.

    Features:
    - robots.txt compliance
    - Sitemap discovery
    - Link extraction from rendered HTML
    - Playwright for JS-rendered pages
    - Document download (PDF, DOCX, PPTX, XLSX)
    - SQLite crawl manifest
    - Progress callback for UI
    - Stop control
    """

    def __init__(
        self,
        run_id: str = "",
        progress_callback: Callable[[dict], None] | None = None,
        mode: str = "full",  # "full" | "discover"
    ):
        self.run_id   = run_id or _make_run_id()
        self.mode     = mode
        self._stop    = threading.Event()
        self._progress_cb = progress_callback

        # Crawl manifest
        db_path    = os.path.join(CRAWL_RUNS_DIR, "crawl.db")
        self.store = CrawlStore(db_path=db_path, run_id=self.run_id)

        # Robots policy
        self.robots = RobotsPolicy(ROOT_URL, user_agent=USER_AGENT)

        # Counters
        self._html_count = 0
        self._file_count = 0
        self._start_time = 0.0

        # Playwright browser (lazy init)
        self._pw          = None
        self._browser     = None
        self._browser_ctx = None
        self._page        = None

        # Output dirs
        os.makedirs(RAW_PAGES_DIR,  exist_ok=True)
        os.makedirs(RAW_FILES_DIR,  exist_ok=True)
        os.makedirs(CRAWL_RUNS_DIR, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Run the full crawl. Returns summary stats."""
        self._start_time = time.time()
        print(f"\n{'='*60}")
        print(f"[crawler] Run ID : {self.run_id}")
        print(f"[crawler] Mode   : {self.mode}")
        print(f"[crawler] Root   : {ROOT_URL}")
        print(f"[crawler] Limits : depth={MAX_DEPTH}, pages={MAX_PAGES}, files={MAX_FILES}")
        print(f"{'='*60}\n")

        # 1. Load robots.txt
        self.robots.load()

        # 2. Start run in manifest
        self.store.start_run(seeds=1)

        # 3. Discover sitemaps
        sitemap_urls = discover_sitemaps(ROOT_URL, self.robots.sitemaps)
        self._seed_from_sitemaps(sitemap_urls)

        # 4. Seed with root URL
        seed = normalize_url(ROOT_URL)
        if seed:
            self.store.add_url(
                seed, parent_url="", depth=0,
                resource_type="html", discovery_method="manual_seed"
            )

        # 5. BFS crawl loop
        is_partial = self._bfs_crawl()

        # 6. Finalize
        self.store.finish_run(is_partial=is_partial)
        stats = self.store.get_stats()
        self._export_reports(stats)
        self._cleanup_playwright()

        elapsed = round(time.time() - self._start_time, 1)
        print(f"\n[crawler] Finished in {elapsed}s")
        print(f"[crawler] Discovered: {stats.get('discovered',0)}")
        print(f"[crawler] HTML pages: {stats.get('html_pages',0)}")
        print(f"[crawler] PDFs      : {stats.get('pdfs',0)}")
        print(f"[crawler] Extracted : {stats.get('extracted',0)}")
        print(f"[crawler] Failed    : {stats.get('failed',0)}")
        print(f"[crawler] Skipped   : {stats.get('skipped',0)}")
        print(f"[crawler] Status    : {'PARTIAL' if is_partial else 'COMPLETE'}")

        return {**stats, "run_id": self.run_id, "is_partial": is_partial, "elapsed": elapsed}

    def stop(self):
        """Signal the crawler to stop after the current page."""
        self._stop.set()
        print("[crawler] Stop requested.")

    # ── Internal ─────────────────────────────────────────────────────────────

    def _bfs_crawl(self) -> bool:
        """
        BFS crawl loop. Returns True if crawl was cut short (partial).
        """
        is_partial = False

        while not self._stop.is_set():
            if self._html_count >= MAX_PAGES:
                print(f"[crawler] Page limit reached ({MAX_PAGES})")
                is_partial = True
                break

            pending = self.store.get_next_pending(limit=1)
            if not pending:
                break  # all done

            item = pending[0]
            url      = item["canonical_url"]
            depth    = item["depth"]
            res_type = item["resource_type"]

            if depth > MAX_DEPTH:
                self.store.mark_skipped(url, f"depth>{MAX_DEPTH}")
                continue

            # Check robots
            if RESPECT_ROBOTS and not self.robots.is_allowed(url):
                self.store.mark_skipped(url, "robots.txt disallowed")
                self._emit_progress()
                continue

            self.store.mark_fetching(url)

            if res_type in ("pdf", "docx", "pptx", "xlsx", "csv", "document"):
                self._handle_document(url, depth)
            else:
                self._handle_html_page(url, depth)

            # Polite delay
            time.sleep(max(self.robots.crawl_delay, CRAWLER_DELAY))
            self._emit_progress()

        return is_partial

    def _handle_html_page(self, url: str, depth: int):
        """Fetch, extract and discover links from an HTML page."""
        try:
            result = self._fetch_with_playwright(url)
            if not result:
                result = self._fetch_with_requests(url)

            if not result:
                self.store.mark_failed(url, "fetch returned nothing")
                return

            html       = result["html"]
            text       = result["text"]
            title      = result["title"]
            final_url  = result["final_url"]
            status     = result["status"]

            if status >= 400:
                self.store.mark_failed(url, f"HTTP {status}", http_status=status)
                return

            content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

            # Save page
            if self.mode == "full" and len(text) >= 80:
                self._save_page(url, title, text, final_url)
                self._html_count += 1
                self.store.mark_extracted(url, len(text))
            elif len(text) < 80:
                self.store.mark_fetched(
                    url, url_final=final_url, http_status=status,
                    title=title, content_hash=content_hash, extracted_chars=len(text)
                )
                self.store.mark_skipped(url, f"too_short:{len(text)}chars")
            else:
                # discover mode — record but don't save
                self.store.mark_fetched(
                    url, url_final=final_url, http_status=status,
                    title=title, content_hash=content_hash, extracted_chars=len(text)
                )

            # Discover links from this page
            if depth < MAX_DEPTH:
                links = extract_links_from_html(html, url)
                self._enqueue_links(links, parent_url=url, parent_depth=depth)

            print(f"  [html] depth={depth} {url[:80]}  ({len(text):,}c  |  title={title[:40]})")

        except Exception as e:
            self.store.mark_failed(url, str(e)[:300])
            print(f"  [fail] {url}: {e}")

    def _handle_document(self, url: str, depth: int):
        """Download a document file (PDF, DOCX, etc.)."""
        if self._file_count >= MAX_FILES:
            self.store.mark_skipped(url, f"file_limit:{MAX_FILES}")
            return

        try:
            headers = {"User-Agent": USER_AGENT}
            r = requests.get(url, headers=headers, timeout=CRAWLER_TIMEOUT,
                             stream=True, allow_redirects=True)

            if r.status_code >= 400:
                self.store.mark_failed(url, f"HTTP {r.status_code}", r.status_code)
                return

            content_type = r.headers.get("content-type", "")
            size_bytes   = 0
            chunks_      = []

            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    size_bytes += len(chunk)
                    chunks_.append(chunk)
                    if size_bytes > MAX_FILE_MB * 1024 * 1024:
                        self.store.mark_skipped(url, f"too_large:>{MAX_FILE_MB}MB")
                        return

            data = b"".join(chunks_)
            content_hash = hashlib.sha256(data).hexdigest()[:16]

            # Save to disk
            if self.mode == "full":
                fname = _safe_filename(url)
                fpath = os.path.join(RAW_FILES_DIR, fname)
                with open(fpath, "wb") as f:
                    f.write(data)

            self._file_count += 1
            self.store.mark_fetched(
                url,
                url_final=r.url,
                http_status=r.status_code,
                content_type=content_type,
                content_length=size_bytes,
                content_hash=content_hash,
            )
            self.store.mark_extracted(url, size_bytes)
            print(f"  [doc]  {url[-60:]}  ({size_bytes//1024}KB  {content_type})")

        except Exception as e:
            self.store.mark_failed(url, str(e)[:300])
            print(f"  [fail-doc] {url}: {e}")

    def _fetch_with_requests(self, url: str) -> dict | None:
        """Simple HTTP fetch — for non-JS pages."""
        try:
            r = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=CRAWLER_TIMEOUT,
                allow_redirects=True,
            )
            soup  = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            title = title.get_text(strip=True) if title else url

            # Remove nav/script/style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            text = _clean_text(text)

            return {
                "html":      r.text,
                "text":      text,
                "title":     title,
                "final_url": r.url,
                "status":    r.status_code,
            }
        except Exception as e:
            print(f"  [requests-fail] {url}: {e}")
            return None

    def _fetch_with_playwright(self, url: str) -> dict | None:
        """JS-rendered fetch via Playwright."""
        try:
            self._ensure_playwright()
            page = self._page

            # Navigate
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=CRAWLER_TIMEOUT * 1000)
                page.wait_for_timeout(1500)
            except Exception:
                try:
                    response = page.goto(url, wait_until="commit", timeout=15000)
                    page.wait_for_timeout(2000)
                except Exception as e2:
                    print(f"  [pw-nav-fail] {url}: {e2}")
                    return None

            # Scroll to trigger lazy content
            try:
                page.evaluate("""
                    async () => {
                        for (let i = 0; i < 5; i++) {
                            window.scrollBy(0, window.innerHeight);
                            await new Promise(r => setTimeout(r, 300));
                        }
                        window.scrollTo(0, 0);
                    }
                """)
            except Exception:
                pass

            final_url = page.url
            status    = response.status if response else 200
            title     = page.title() or url
            html      = page.content()

            # Get text via inner_text for accuracy
            try:
                raw_text = page.inner_text("body")
            except Exception:
                raw_text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)

            text = _clean_text(raw_text)

            return {
                "html":      html,
                "text":      text,
                "title":     title,
                "final_url": final_url,
                "status":    status,
            }
        except Exception as e:
            print(f"  [pw-fail] {url}: {e}")
            return None

    def _ensure_playwright(self):
        """Lazy-init Playwright browser."""
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
            self._pw      = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._browser_ctx = self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800},
            )
            self._page = self._browser_ctx.new_page()
            # Block images/fonts to speed up
            self._page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf,mp4,mp3}",
                lambda route: route.abort(),
            )
            print("[crawler] Playwright browser started.")
        except Exception as e:
            print(f"[crawler] Playwright init failed: {e}. Falling back to requests.")
            self._browser = "failed"

    def _cleanup_playwright(self):
        try:
            if self._page:
                self._page.close()
            if self._browser_ctx:
                self._browser_ctx.close()
            if self._browser and self._browser != "failed":
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def _enqueue_links(self, links: list[dict], parent_url: str, parent_depth: int):
        """Add discovered links to the crawl queue."""
        added = 0
        for link in links:
            if not link.get("is_internal"):
                continue

            url      = link["url"]
            res_type = link["resource_type"]

            # Skip already known
            if self.store.is_known(url):
                continue

            new = self.store.add_url(
                url,
                parent_url=parent_url,
                anchor_text=link.get("anchor_text", "")[:100],
                depth=parent_depth + 1,
                resource_type=res_type,
                discovery_method=link.get("discovery_method", "content_link"),
            )
            if new:
                added += 1

        if added:
            print(f"    [discovered] +{added} new URLs from {parent_url[-50:]}")

    def _seed_from_sitemaps(self, sitemap_urls: list[str]):
        """Add all sitemap URLs to the crawl queue."""
        for sitemap_url in sitemap_urls:
            entries = parse_sitemap(sitemap_url)
            for entry in entries:
                url = entry["url"]
                if is_allowed_host(url):
                    self.store.add_url(
                        url,
                        parent_url=sitemap_url,
                        depth=0,
                        resource_type=get_resource_type(url),
                        discovery_method="sitemap",
                    )

    def _save_page(self, url: str, title: str, text: str, final_url: str):
        """Save extracted page text to data/raw/pages/"""
        existing = len([
            f for f in os.listdir(RAW_PAGES_DIR)
            if f.startswith("page_") and f.endswith(".json")
        ])
        idx      = existing + 1
        out_path = os.path.join(RAW_PAGES_DIR, f"page_{idx:04d}.json")

        record = {
            "url":      final_url or url,
            "title":    title,
            "text":     text,
            "doc_type": "webpage",
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

    def _export_reports(self, stats: dict):
        """Export CSV and JSON reports."""
        run_dir = os.path.join(CRAWL_RUNS_DIR, self.run_id)
        os.makedirs(run_dir, exist_ok=True)

        self.store.export_csv(os.path.join(run_dir, "discovered_urls.csv"))
        self.store.export_json(os.path.join(run_dir, "discovered_urls.json"))

        summary = {
            **stats,
            "run_id":     self.run_id,
            "root_url":   ROOT_URL,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_s":  round(time.time() - self._start_time, 1),
        }
        with open(os.path.join(run_dir, "crawl_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)

        print(f"[crawler] Reports saved to {run_dir}/")

    def _emit_progress(self):
        if self._progress_cb:
            try:
                stats = self.store.get_stats()
                stats["run_id"] = self.run_id
                stats["elapsed"] = round(time.time() - self._start_time, 1)
                self._progress_cb(stats)
            except Exception:
                pass


# ── Helpers ───────────────────────────────────────────────────────────────────

_NAV_LINES = {
    "about", "admissions", "departments", "academics", "exam cell",
    "alumni", "placement", "contact", "apply", "login", "logout",
    "home", "menu", "close", "search", "kit", "kitcoek",
    "read more", "know more", "click here", "apply now", "view all",
    "back", "next", "prev", "previous",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
}
_DROP_RE = [
    re.compile(r"^home\s*[|›»>\-]\s*", re.I),
    re.compile(r"^\W{1,3}$"),
    re.compile(r"^.{1,4}$"),
]


def _clean_text(text: str) -> str:
    lines  = text.splitlines()
    seen:  set[str]  = set()
    clean: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low in _NAV_LINES:
            continue
        if any(p.match(line) for p in _DROP_RE):
            continue
        if len(line) <= 6 and line.isupper():
            continue
        if low in seen:
            continue
        seen.add(low)
        clean.append(line)
    text = "\n".join(clean)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_filename(url: str) -> str:
    """Generate a safe filename from a URL."""
    name = re.sub(r"[^\w\-_.]", "_", url.split("//")[-1])
    name = re.sub(r"_+", "_", name)[:120]
    return name


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="KITCOEK Recursive Crawler")
    parser.add_argument("--mode", choices=["full", "discover"], default="full",
                        help="full=crawl+extract, discover=URLs only")
    args = parser.parse_args()

    crawler = RecursiveCrawler(mode=args.mode)
    stats   = crawler.run()
    print(json.dumps(stats, indent=2))
