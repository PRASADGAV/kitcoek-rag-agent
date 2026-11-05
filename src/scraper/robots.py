"""
robots.txt fetcher and parser for the KITCOEK crawler.

Fetches robots.txt, parses Disallow/Allow/Crawl-delay/Sitemap directives,
and provides is_allowed(url) checks and sitemap URL discovery.
"""

import re
import time
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "KITCOEK-RAG-PrototypeBot/1.0"
DEFAULT_CRAWL_DELAY = 1.0  # seconds


class RobotsPolicy:
    """
    Fetches and caches robots.txt for one host.
    Exposes is_allowed() and discovered sitemap URLs.
    """

    def __init__(self, base_url: str, user_agent: str = USER_AGENT, timeout: int = 10):
        self.base_url    = base_url
        self.user_agent  = user_agent
        self.timeout     = timeout
        self._parser     = RobotFileParser()
        self._sitemaps: list[str] = []
        self._crawl_delay: float  = DEFAULT_CRAWL_DELAY
        self._loaded     = False
        self._raw_text   = ""

    def load(self) -> bool:
        """Fetch and parse robots.txt. Returns True on success."""
        parsed   = urlparse(self.base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        try:
            r = requests.get(
                robots_url,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
            )
            if r.status_code == 200:
                self._raw_text = r.text
                self._parser.set_url(robots_url)
                self._parser.parse(r.text.splitlines())
                self._sitemaps   = self._extract_sitemaps(r.text)
                self._crawl_delay = self._extract_delay(r.text)
                self._loaded = True
                print(f"[robots] Loaded robots.txt from {robots_url}")
                print(f"[robots] Found {len(self._sitemaps)} sitemap(s)")
                print(f"[robots] Crawl-delay: {self._crawl_delay}s")
                return True
            else:
                print(f"[robots] {robots_url} returned {r.status_code} — assuming unrestricted")
                self._loaded = True
                return False
        except Exception as e:
            print(f"[robots] Failed to fetch {robots_url}: {e} — assuming unrestricted")
            self._loaded = True
            return False

    def is_allowed(self, url: str) -> bool:
        """Check if crawling this URL is allowed per robots.txt."""
        if not self._loaded:
            self.load()
        try:
            return self._parser.can_fetch(self.user_agent, url)
        except Exception:
            return True  # fail open

    @property
    def crawl_delay(self) -> float:
        return self._crawl_delay

    @property
    def sitemaps(self) -> list[str]:
        return self._sitemaps

    @property
    def raw_text(self) -> str:
        return self._raw_text

    def _extract_sitemaps(self, text: str) -> list[str]:
        """Extract Sitemap: directives from robots.txt."""
        sitemaps = []
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^Sitemap:\s*(.+)$", line, re.I)
            if m:
                sitemaps.append(m.group(1).strip())
        return sitemaps

    def _extract_delay(self, text: str) -> float:
        """Extract Crawl-delay from robots.txt."""
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r"^Crawl-delay:\s*([\d.]+)$", line, re.I)
            if m:
                try:
                    delay = float(m.group(1))
                    return max(delay, DEFAULT_CRAWL_DELAY)  # never go below 1s
                except ValueError:
                    pass
        return DEFAULT_CRAWL_DELAY


def discover_sitemaps(base_url: str, known_sitemaps: list[str], timeout: int = 10) -> list[str]:
    """
    Try to find sitemap URLs from:
    1. Already known sitemaps (from robots.txt)
    2. Conventional endpoints: /sitemap.xml, /sitemap_index.xml
    """
    candidates = list(known_sitemaps)
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]:
        url = root + path
        if url not in candidates:
            candidates.append(url)

    found = []
    for url in candidates:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200 and ("xml" in r.headers.get("content-type", "") or
                                          "<urlset" in r.text or "<sitemapindex" in r.text):
                found.append(url)
                print(f"[robots] Valid sitemap: {url}")
            else:
                print(f"[robots] Not a sitemap: {url} ({r.status_code})")
        except Exception as e:
            print(f"[robots] Sitemap check failed for {url}: {e}")

    return found
