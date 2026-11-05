"""
HTML content extractor for KITCOEK pages.

Strategy (in order of preference):
1. Trafilatura — state-of-the-art boilerplate removal, main content extraction
2. Readability-style BeautifulSoup fallback — targets semantic main/article tags
3. Raw body text fallback — clean + deduplicate lines

Features:
- Extracts: title, meta description, canonical URL, headings, main text, tables,
  important links, dates, breadcrumbs
- Removes: scripts, styles, nav, footer, cookie banners, hidden elements
- Preserves: heading hierarchy, table structure (as readable text), Marathi/English text
- Flags: empty pages, navigation-only pages, very short content
- Records: extraction method, content length, warning flags
"""

import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

try:
    import trafilatura
    from trafilatura.settings import use_config as trafilatura_config
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# ── Content selectors — KITCOEK site-specific ─────────────────────────────────
# Tried in order; first match with sufficient text wins
MAIN_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".main-content",
    ".content",
    ".page-content",
    ".entry-content",
    "#content",
    "#main",
    ".container",
    "section",
]

# Boilerplate containers to remove before extraction
REMOVE_SELECTORS = [
    "script", "style", "noscript",
    "nav", "header", "footer",
    ".navbar", ".nav", ".navigation", ".breadcrumb",
    ".cookie", ".banner", ".popup", ".modal",
    ".sidebar", ".widget", ".advertisement",
    "[aria-hidden='true']",
    ".sr-only", ".visually-hidden",
    "#cookie-notice", "#cookie-banner",
    ".social-links", ".share-buttons",
    ".back-to-top", ".scroll-top",
]

# Minimum chars for a page to be considered useful
MIN_USEFUL_CHARS = 100

# KITCOEK nav boilerplate lines (appear on every page header/footer)
NAV_BOILERPLATE = {
    "about", "admissions", "departments", "academics", "exam cell",
    "alumni", "placement", "contact", "apply", "login", "home", "menu",
    "close", "search", "kit", "kitcoek", "read more", "know more",
    "click here", "apply now", "view all", "back", "next", "prev",
    "facebook", "twitter", "linkedin", "instagram", "youtube",
    "powered by hashinclude", "hashinclude",
    "get connected with us on social networks",
    "useful links", "quick links", "watch video",
    "© 2024 copyright :", "© 2025 copyright :", "© 2026 copyright :",
}

_DROP_RE = [
    re.compile(r"^home\s*[|›»>\-]", re.I),
    re.compile(r"^\W{1,4}$"),
    re.compile(r"^.{1,5}$"),
]


class HTMLExtractor:
    """
    Extracts clean, structured text from HTML pages.

    Usage:
        extractor = HTMLExtractor()
        result = extractor.extract(html, url="https://www.kitcoek.in/about")
        print(result["text"])
        print(result["warnings"])
    """

    def extract(self, html: str, url: str = "") -> dict[str, Any]:
        """
        Extract clean text and metadata from an HTML string.

        Returns:
        {
            title, meta_description, canonical_url, language,
            text, headings, tables, links, breadcrumb,
            published_date, word_count, char_count,
            extraction_method, warnings, extracted_at
        }
        """
        warnings: list[str] = []
        result = self._empty_result(url)

        if not html or len(html.strip()) < 50:
            warnings.append("empty_input")
            result["warnings"] = warnings
            return result

        soup = BeautifulSoup(html, "html.parser")

        # ── 1. Metadata ────────────────────────────────────────────────
        result["title"]            = self._get_title(soup, url)
        result["meta_description"] = self._get_meta(soup, "description")
        result["canonical_url"]    = self._get_canonical(soup, url) or url
        result["language"]         = self._get_lang(soup)
        result["breadcrumb"]       = self._get_breadcrumb(soup)
        result["published_date"]   = self._get_date(soup, html)
        result["links"]            = self._get_important_links(soup, url)
        result["headings"]         = self._get_headings(soup)
        result["tables"]           = self._get_tables(soup)

        # ── 2. Main text — try methods in order ────────────────────────
        text, method = self._extract_text(html, soup, url)

        # ── 3. Quality checks ─────────────────────────────────────────
        if len(text) < MIN_USEFUL_CHARS:
            warnings.append(f"short_content:{len(text)}chars")

        if self._is_nav_only(text):
            warnings.append("navigation_only")
            text = ""

        if len(text) > 0 and len(text) / max(len(html), 1) < 0.02:
            warnings.append("low_text_ratio")

        result["text"]               = text
        result["word_count"]         = len(text.split())
        result["char_count"]         = len(text)
        result["extraction_method"]  = method
        result["warnings"]           = warnings
        result["extracted_at"]       = datetime.now(timezone.utc).isoformat()

        return result

    # ── Extraction methods ─────────────────────────────────────────────────────

    def _extract_text(self, html: str, soup: BeautifulSoup, url: str) -> tuple[str, str]:
        """Try extraction methods in order; return (text, method_name)."""

        # Method 1: Trafilatura (best for news/article pages)
        if HAS_TRAFILATURA:
            try:
                text = trafilatura.extract(
                    html,
                    url=url,
                    include_tables=True,
                    include_links=False,
                    include_images=False,
                    no_fallback=False,
                    favor_recall=True,  # maximize recall for RAG
                )
                if text and len(text.strip()) >= MIN_USEFUL_CHARS:
                    return _clean_text(text), "trafilatura"
            except Exception:
                pass

        # Method 2: Semantic main content selectors
        text = self._extract_semantic(soup)
        if text and len(text) >= MIN_USEFUL_CHARS:
            return _clean_text(text), "semantic_selectors"

        # Method 3: Full body with boilerplate removal
        text = self._extract_body(soup)
        if text and len(text) >= MIN_USEFUL_CHARS:
            return _clean_text(text), "body_cleaned"

        # Method 4: Raw soup text as last resort
        for tag in soup(["script", "style"]):
            tag.decompose()
        raw = soup.get_text("\n", strip=True)
        return _clean_text(raw), "raw_body"

    def _extract_semantic(self, soup: BeautifulSoup) -> str:
        """Extract from semantic content containers."""
        # Remove boilerplate first
        soup_copy = BeautifulSoup(str(soup), "html.parser")
        for sel in REMOVE_SELECTORS:
            for tag in soup_copy.select(sel):
                tag.decompose()

        for sel in MAIN_SELECTORS:
            elements = soup_copy.select(sel)
            for el in elements:
                text = el.get_text("\n", strip=True)
                if len(text) >= MIN_USEFUL_CHARS:
                    return text
        return ""

    def _extract_body(self, soup: BeautifulSoup) -> str:
        """Remove all boilerplate and return body text."""
        soup_copy = BeautifulSoup(str(soup), "html.parser")
        for sel in REMOVE_SELECTORS:
            for tag in soup_copy.select(sel):
                tag.decompose()
        body = soup_copy.find("body")
        if body:
            return body.get_text("\n", strip=True)
        return soup_copy.get_text("\n", strip=True)

    # ── Metadata helpers ───────────────────────────────────────────────────────

    def _get_title(self, soup: BeautifulSoup, fallback: str = "") -> str:
        # OG title first, then <title>, then h1
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        t = soup.find("title")
        if t:
            return t.get_text(strip=True)
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return fallback

    def _get_meta(self, soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        tag = soup.find("meta", property=f"og:{name}")
        if tag and tag.get("content"):
            return tag["content"].strip()
        return ""

    def _get_canonical(self, soup: BeautifulSoup, fallback: str = "") -> str:
        tag = soup.find("link", rel="canonical")
        if tag and tag.get("href"):
            return tag["href"].strip()
        return fallback

    def _get_lang(self, soup: BeautifulSoup) -> str:
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            return html_tag["lang"].strip()[:10]
        return "en"

    def _get_breadcrumb(self, soup: BeautifulSoup) -> list[str]:
        """Extract breadcrumb navigation trail."""
        crumbs = []
        for sel in [".breadcrumb", "[aria-label='breadcrumb']", "nav.breadcrumb"]:
            el = soup.select_one(sel)
            if el:
                items = el.find_all(["li", "a", "span"])
                crumbs = [i.get_text(strip=True) for i in items if i.get_text(strip=True)]
                if crumbs:
                    return crumbs[:10]
        return crumbs

    def _get_date(self, soup: BeautifulSoup, html: str) -> str:
        """Try to find a publication/modification date."""
        # Look for time tags
        t = soup.find("time")
        if t:
            dt = t.get("datetime") or t.get_text(strip=True)
            if dt:
                return dt[:30]
        # Meta tags
        for name in ["article:published_time", "DC.date", "date", "pubdate"]:
            m = soup.find("meta", attrs={"name": name}) or soup.find("meta", property=name)
            if m and m.get("content"):
                return m["content"][:30]
        # Pattern in text
        m = re.search(
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b",
            html[:2000]
        )
        if m:
            return m.group(0)
        return ""

    def _get_headings(self, soup: BeautifulSoup) -> list[dict]:
        """Extract heading hierarchy."""
        headings = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            text = tag.get_text(strip=True)
            if text and len(text) > 3:
                headings.append({"level": int(tag.name[1]), "text": text[:200]})
        return headings[:50]

    def _get_tables(self, soup: BeautifulSoup) -> list[str]:
        """Extract tables as readable text (preserving row/column structure)."""
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                tables.append("\n".join(rows))
        return tables[:20]

    def _get_important_links(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extract links that look like important resources (PDFs, downloads, forms)."""
        important = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)[:100]
            lower = href.lower()
            # Keep document links and internal links with meaningful text
            if any(ext in lower for ext in [".pdf", ".docx", ".xlsx", ".pptx"]):
                important.append({"text": text, "href": href, "type": "document"})
            elif text and len(text) > 5 and not any(
                skip in lower for skip in ["javascript:", "mailto:", "#", "tel:"]
            ):
                important.append({"text": text, "href": href, "type": "link"})
        return important[:50]

    def _is_nav_only(self, text: str) -> bool:
        """Return True if the text is predominantly nav boilerplate."""
        if not text:
            return True
        lines = [l.strip().lower() for l in text.splitlines() if l.strip()]
        if not lines:
            return True
        nav_lines = sum(1 for l in lines if l in NAV_BOILERPLATE or len(l) <= 4)
        return nav_lines / len(lines) > 0.7

    def _empty_result(self, url: str) -> dict[str, Any]:
        return {
            "title": "", "meta_description": "", "canonical_url": url,
            "language": "en", "text": "", "headings": [], "tables": [],
            "links": [], "breadcrumb": [], "published_date": "",
            "word_count": 0, "char_count": 0,
            "extraction_method": "none", "warnings": [],
            "extracted_at": "",
        }


# ── Text cleaning utilities ────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Clean extracted text: deduplicate lines, remove boilerplate."""
    lines = text.splitlines()
    seen:  set[str]  = set()
    clean: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low in NAV_BOILERPLATE:
            continue
        if any(p.match(line) for p in _DROP_RE):
            continue
        if len(line) <= 5 and line.isupper():
            continue
        if low in seen:
            continue
        seen.add(low)
        clean.append(line)

    text = "\n".join(clean)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
