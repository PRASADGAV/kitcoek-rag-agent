"""
URL normalization and host policy for the KITCOEK recursive crawler.

Rules:
- Resolve relative URLs against base
- Remove fragments (keep as anchor hint)
- Normalize scheme + host to lowercase
- Remove known tracking params (utm_*, fbclid, etc.)
- Keep meaningful query params
- Normalize trailing slash consistently
- Follow canonical tags
"""

import re
from urllib.parse import (
    urlparse, urlunparse, urljoin, urlencode, parse_qs, quote, unquote
)

# Tracking query params to strip
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "_ga", "mc_cid", "mc_eid",
}

# Allowed hosts — canonical crawl scope
ALLOWED_HOSTS = {
    "www.kitcoek.in",
    "kitcoek.in",
}

# Document extensions we want to download
DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".txt"
}

# Extensions to skip entirely (images, media, fonts, etc.)
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".tar", ".gz", ".rar",
    ".exe", ".dmg", ".apk",
    ".js", ".css", ".map",
}


def normalize_url(url: str, base_url: str = "") -> str | None:
    """
    Normalize a URL for use as a canonical identifier.

    Returns None if the URL should be skipped entirely.
    """
    if not url:
        return None

    url = url.strip()

    # Skip javascript: mailto: tel: etc.
    if re.match(r"^(javascript|mailto|tel|ftp|data|#):", url, re.I):
        return None

    # Resolve relative URLs
    if base_url:
        url = urljoin(base_url, url)

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # Must have a scheme and netloc
    if not parsed.scheme or not parsed.netloc:
        return None

    # Only http/https
    if parsed.scheme.lower() not in ("http", "https"):
        return None

    # Normalize scheme and host
    scheme = "https"  # always prefer https
    host   = parsed.netloc.lower().split(":")[0]  # strip port

    # Strip www if not in allowlist but bare domain is
    if host == "kitcoek.in":
        host = "www.kitcoek.in"

    path = parsed.path or "/"

    # Decode then re-encode path safely
    path = unquote(path)
    path = quote(path, safe="/:@!$&'()*+,;=")

    # Normalize trailing slash: keep for root, remove for others
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Check extension
    lower_path = path.lower()
    ext = ""
    if "." in lower_path.split("/")[-1]:
        ext = "." + lower_path.rsplit(".", 1)[-1]

    if ext in SKIP_EXTENSIONS:
        return None

    # Clean query string — remove tracking params, keep others sorted
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=False)
        cleaned = {k: v for k, v in params.items() if k not in _STRIP_PARAMS}
        query = urlencode(sorted(cleaned.items()), doseq=True) if cleaned else ""
    else:
        query = ""

    # Reassemble — drop fragment for identity
    canonical = urlunparse((scheme, host, path, "", query, ""))
    return canonical


def is_allowed_host(url: str) -> bool:
    """Return True if URL is within the allowed host scope."""
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        return host in ALLOWED_HOSTS
    except Exception:
        return False


def get_resource_type(url: str) -> str:
    """Classify URL by expected resource type."""
    try:
        path = urlparse(url).path.lower()
        if "." in path.split("/")[-1]:
            ext = "." + path.rsplit(".", 1)[-1]
        else:
            return "html"

        if ext == ".pdf":
            return "pdf"
        if ext in {".docx", ".doc"}:
            return "docx"
        if ext in {".pptx", ".ppt"}:
            return "pptx"
        if ext in {".xlsx", ".xls"}:
            return "xlsx"
        if ext == ".csv":
            return "csv"
        if ext == ".txt":
            return "txt"
        if ext in DOCUMENT_EXTENSIONS:
            return "document"
        return "html"
    except Exception:
        return "html"


def is_document_url(url: str) -> bool:
    """Return True if URL points to a downloadable document."""
    return get_resource_type(url) in {"pdf", "docx", "pptx", "xlsx", "csv", "txt", "document"}


def extract_fragment(url: str) -> str:
    """Return the fragment (anchor) from a URL."""
    try:
        return urlparse(url).fragment
    except Exception:
        return ""
