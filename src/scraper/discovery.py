"""
Link discovery from rendered HTML pages.

Extracts all internal links from:
- Navigation menus
- Main content <a href> tags
- Sitemap XML files
- Pagination links
- Download (document) links
"""

import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .url_normalizer import (
    normalize_url, is_allowed_host, is_document_url,
    DOCUMENT_EXTENSIONS, ALLOWED_HOSTS
)

USER_AGENT = "KITCOEK-RAG-PrototypeBot/1.0"


def extract_links_from_html(
    html: str,
    page_url: str,
    allowed_hosts: set[str] = ALLOWED_HOSTS,
) -> list[dict]:
    """
    Extract all relevant links from raw or rendered HTML.

    Returns list of dicts:
      {url, anchor_text, resource_type, discovery_method, is_document}
    """
    results = []
    seen    = set()

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return results

    # ── All <a href> tags ──────────────────────────────────────────────
    for tag in soup.find_all("a", href=True):
        href        = tag.get("href", "").strip()
        anchor_text = tag.get_text(" ", strip=True)[:200]

        canonical = normalize_url(href, page_url)
        if not canonical:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)

        host = urlparse(canonical).netloc
        is_internal = host in allowed_hosts or not host

        if not is_internal:
            # External link — record as reference only
            results.append({
                "url":              canonical,
                "anchor_text":      anchor_text,
                "resource_type":    "external",
                "discovery_method": "content_link",
                "is_document":      False,
                "is_internal":      False,
            })
            continue

        is_doc      = is_document_url(canonical)
        res_type    = "pdf" if canonical.lower().endswith(".pdf") else (
                      "document" if is_doc else "html")

        # Determine discovery method from tag context
        method = _classify_link_method(tag)

        results.append({
            "url":              canonical,
            "anchor_text":      anchor_text,
            "resource_type":    res_type,
            "discovery_method": method,
            "is_document":      is_doc,
            "is_internal":      True,
        })

    # ── Canonical tag ─────────────────────────────────────────────────
    canonical_tag = soup.find("link", rel="canonical")
    if canonical_tag and canonical_tag.get("href"):
        canon = normalize_url(canonical_tag["href"], page_url)
        if canon and canon not in seen:
            results.append({
                "url":              canon,
                "anchor_text":      "",
                "resource_type":    "html",
                "discovery_method": "canonical_tag",
                "is_document":      False,
                "is_internal":      is_allowed_host(canon),
            })

    return results


def _classify_link_method(tag) -> str:
    """Guess discovery method from the tag's ancestors."""
    parents = [p.name for p in tag.parents if p.name]

    if any(p in ("nav", "header") for p in parents):
        return "navigation"
    if any(p in ("footer",) for p in parents):
        return "footer"
    if any(p in ("aside", "sidebar") for p in parents):
        return "sidebar"
    # Look for breadcrumb class
    for parent in tag.parents:
        cls = " ".join(parent.get("class", []))
        if "breadcrumb" in cls.lower():
            return "breadcrumb"
        if "pagination" in cls.lower() or "pager" in cls.lower():
            return "pagination"
    return "content_link"


def parse_sitemap(sitemap_url: str, timeout: int = 15) -> list[dict]:
    """
    Fetch and parse an XML sitemap or sitemap index.

    Returns list of {url, lastmod} dicts.
    """
    results = []
    try:
        r = requests.get(
            sitemap_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        if r.status_code != 200:
            print(f"[discovery] Sitemap fetch failed: {sitemap_url} ({r.status_code})")
            return results

        content = r.text
        # Handle sitemap index (contains <sitemap> elements)
        if "<sitemapindex" in content:
            root = ET.fromstring(content)
            ns   = _get_ns(root)
            for elem in root.findall(f"{ns}sitemap"):
                loc = elem.findtext(f"{ns}loc", "").strip()
                if loc:
                    # Recursively parse child sitemaps
                    child_results = parse_sitemap(loc, timeout)
                    results.extend(child_results)
        elif "<urlset" in content:
            root = ET.fromstring(content)
            ns   = _get_ns(root)
            for elem in root.findall(f"{ns}url"):
                loc     = elem.findtext(f"{ns}loc", "").strip()
                lastmod = elem.findtext(f"{ns}lastmod", "").strip()
                if loc:
                    canonical = normalize_url(loc)
                    if canonical:
                        results.append({
                            "url":     canonical,
                            "lastmod": lastmod,
                        })
        print(f"[discovery] Sitemap {sitemap_url}: {len(results)} URLs")
    except Exception as e:
        print(f"[discovery] Sitemap parse error {sitemap_url}: {e}")

    return results


def _get_ns(root) -> str:
    """Extract XML namespace from root element."""
    tag = root.tag
    if tag.startswith("{"):
        return tag.split("}")[0] + "}"
    return ""


def extract_links_from_playwright_page(page, page_url: str) -> list[dict]:
    """
    Extract links from a live Playwright page object.

    Uses JavaScript evaluation for maximum accuracy with SPAs.
    """
    results = []
    seen    = set()

    try:
        links = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(el => ({
                href: el.href,
                text: (el.innerText || el.textContent || '').trim().substring(0, 200),
                tagName: el.tagName
            }))"""
        )
    except Exception as e:
        print(f"[discovery] Playwright link extraction failed: {e}")
        return results

    for link in links:
        href   = (link.get("href") or "").strip()
        anchor = (link.get("text") or "").strip()

        canonical = normalize_url(href, page_url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)

        is_doc      = is_document_url(canonical)
        is_internal = is_allowed_host(canonical)
        res_type    = "pdf" if canonical.lower().endswith(".pdf") else (
                      "document" if is_doc else (
                      "html" if is_internal else "external"))

        results.append({
            "url":              canonical,
            "anchor_text":      anchor,
            "resource_type":    res_type,
            "discovery_method": "dom_link",
            "is_document":      is_doc,
            "is_internal":      is_internal,
        })

    return results
