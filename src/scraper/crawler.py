"""
Playwright-based crawler for the KITCOEK website.

The site is a React/Next.js SPA — requests/BeautifulSoup only gets the
empty shell.  Playwright launches a real headless Chromium browser, waits
for JavaScript to finish rendering, then extracts the fully populated text.

This gives us the REAL page content: Director's message, department details,
placement stats, admission info, fee proposals, faculty lists, etc.
"""

import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from . import config

# ---------------------------------------------------------------------------
# Navigation / boilerplate lines to strip  (appear on every page header/footer)
# ---------------------------------------------------------------------------
NAV_LINES = {
    "about", "admissions", "departments", "academics", "exam cell",
    "alumni", "placement", "contact", "apply", "login", "logout",
    "home", "menu", "close", "search", "newsletter", "subscribe",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "powered by hashinclude", "hashinclude", "swapnil jadhav",
    "get connected with us on social networks",
    "useful links", "quick links",
    "watch video contact us", "watch video",
    "read more", "read more...", "know more", "know more...",
    "click here", "apply now", "view all", "see all",
    "back", "next", "prev", "previous",
    "kit", "kitcoek",
    "© 2025 copyright :", "© 2024 copyright :",
}

# Lines that match these patterns are dropped
DROP_PATTERNS = [
    re.compile(r"^home\s*[|›»]\s*", re.I),   # breadcrumb "Home | Page"
    re.compile(r"^\W{1,3}$"),                  # pure symbols/punctuation
    re.compile(r"^.{1,4}$"),                   # 1-4 char lines
]


def _clean(text: str) -> str:
    """
    Clean raw inner_text() from Playwright:
    - Drop nav/footer boilerplate
    - Deduplicate lines
    - Collapse whitespace
    """
    lines  = text.splitlines()
    seen:  set[str]  = set()
    clean: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        low = line.lower()

        # Exact nav boilerplate
        if low in NAV_LINES:
            continue

        # Pattern drops
        if any(p.match(line) for p in DROP_PATTERNS):
            continue

        # Skip lines that are only nav-menu items (very short, all-caps)
        if len(line) <= 6 and line.isupper():
            continue

        # Deduplicate
        if low in seen:
            continue
        seen.add(low)
        clean.append(line)

    text = "\n".join(clean)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def crawl() -> None:
    os.makedirs(config.RAW_PAGES_DIR, exist_ok=True)

    # Wipe old pages
    for f in os.listdir(config.RAW_PAGES_DIR):
        os.remove(os.path.join(config.RAW_PAGES_DIR, f))

    total   = len(config.SEED_URLS)
    saved   = 0
    pdf_links: set[str] = set()

    print(f"[crawler] Launching Playwright Chromium ...")
    print(f"[crawler] Fetching {total} pages with JS rendering ...\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Block images/fonts/media to speed up loading
        page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf,mp4,mp3,wav}",
            lambda route: route.abort(),
        )

        for idx, url in enumerate(config.SEED_URLS, start=1):
            # Skip external domains
            host = urlparse(url).netloc
            if host and host != config.ALLOWED_DOMAIN:
                print(f"  [skip:external] ({idx}/{total}) {url}")
                continue

            try:
                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=30000,
                )
                # Extra wait for slow SPAs
                page.wait_for_timeout(1500)

            except PWTimeout:
                print(f"  [timeout] ({idx}/{total}) {url} — trying domcontentloaded ...")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2000)
                except Exception as e2:
                    print(f"  [error]   ({idx}/{total}) {url} -> {e2}")
                    continue
            except Exception as exc:
                print(f"  [error] ({idx}/{total}) {url} -> {exc}")
                continue

            # Collect all PDF links on the page
            anchors = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.href)"
            )
            for href in anchors:
                if href.lower().endswith(".pdf"):
                    pdf_links.add(href)

            # Get title
            title = page.title() or url

            # Extract fully-rendered text
            try:
                raw_text = page.inner_text("body")
            except Exception:
                raw_text = page.content()   # fallback to HTML

            text = _clean(raw_text)

            if len(text) < 80:
                print(f"  [skip:empty]  ({idx}/{total}) {url}  ({len(text)} chars)")
                continue

            saved += 1
            record = {
                "url":      url,
                "title":    title,
                "text":     text,
                "doc_type": "webpage",
            }
            out_path = os.path.join(
                config.RAW_PAGES_DIR, f"page_{saved:04d}.json"
            )
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)

            print(f"  [saved] ({idx}/{total}) {url}  |  {len(text):,} chars")
            time.sleep(0.5)   # polite delay

        browser.close()

    # Save PDF link list
    os.makedirs("data/raw", exist_ok=True)
    pdf_path = os.path.join("data", "raw", "pdf_links.json")
    with open(pdf_path, "w", encoding="utf-8") as fh:
        json.dump(sorted(pdf_links)[: config.MAX_PDFS], fh, indent=2)

    print(f"\n[crawler] Done. Saved {saved}/{total} pages.")
    print(f"[crawler] Discovered {len(pdf_links)} PDF links -> {pdf_path}")


if __name__ == "__main__":
    crawl()
