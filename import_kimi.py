"""
Import Kimi scraped data into the RAG vector store.

Reads C:/Users/prasa/Desktop/scrap/kitcoek_scraped_data.json,
converts each page into a clean text JSON record (same format as our
crawler output), saves to data/raw/pages/kimi_NNNN.json, then
re-ingests everything into ChromaDB.
"""

import json
import os
import re

KIMI_JSON   = r"C:\Users\prasa\Desktop\scrap\kitcoek_scraped_data.json"
KIMI_TXT    = r"C:\Users\prasa\Desktop\scrap\kitcoek_plain_text.txt"
OUT_DIR     = r"data\raw\pages"
KIMI_PREFIX = "kimi_"

# Tags in structured_text that carry real information
CONTENT_TAGS = {"[P]", "[LI]", "[H1]", "[H2]", "[H3]", "[H4]", "[H5]", "[H6]"}

# Boilerplate strings to drop
BOILERPLATE = {
    "read more ...", "read more...", "read more", "know more",
    "powered byhashinclude", "powered by", "hashinclude",
    "your kitcoek assistant", "today", "tweets by officialkitcoek",
    "admission enquiry", "kit whatsapp chatbot",
    "stay notified", "stay informed with events and news",
    "subscribe to our newsletter", "get connected with us on social networks",
    "stay social with your college",
}

# Drop lines matching these patterns
DROP_RE = [
    re.compile(r"^read more", re.I),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),          # bare date lines
    re.compile(r"^https?://"),                     # bare URLs
    re.compile(r"^[\s\-\|\.]{1,5}$"),             # punctuation-only
    re.compile(r"^.{1,6}$"),                       # very short lines
    # Marathi / garbled unicode (common in news snippets)
    re.compile(r"[\u0900-\u097F]{3,}"),
]


def _is_boilerplate(text: str) -> bool:
    t = text.lower().strip()
    if t in BOILERPLATE:
        return True
    if any(p.search(t) for p in DROP_RE):
        return True
    return False


def _structured_to_text(structured: list[str]) -> str:
    """
    Convert a list of '[TAG] content' strings into clean plain text.
    Headings become their text.  Paragraphs and list items become lines.
    Duplicate lines are removed.
    """
    lines: list[str] = []
    seen: set[str]   = set()

    for item in structured:
        # Extract tag and content
        m = re.match(r"^\[([A-Z0-9]+)\]\s*(.+)", item, re.DOTALL)
        if not m:
            continue
        tag     = f"[{m.group(1)}]"
        content = m.group(2).strip()

        if not content or _is_boilerplate(content):
            continue

        key = content.lower()
        if key in seen:
            continue
        seen.add(key)

        lines.append(content)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def import_kimi():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Remove old kimi files so we start fresh
    for f in os.listdir(OUT_DIR):
        if f.startswith(KIMI_PREFIX):
            os.remove(os.path.join(OUT_DIR, f))

    data = json.load(open(KIMI_JSON, encoding="utf-8"))
    saved = 0
    skipped = 0

    print(f"[kimi-import] Processing {len(data)} pages ...\n")

    for idx, (url, page) in enumerate(data.items(), start=1):
        title      = page.get("title", url)
        meta_desc  = page.get("meta_description", "")
        structured = page.get("structured_text", [])

        # Convert structured content to clean text
        body = _structured_to_text(structured)

        # Prepend meta description as extra context if it's informative
        if meta_desc and len(meta_desc) > 60 and not _is_boilerplate(meta_desc):
            body = meta_desc + "\n\n" + body

        if len(body) < 80:
            print(f"  [skip:thin] {url}  ({len(body)} chars)")
            skipped += 1
            continue

        saved += 1
        record = {
            "url":      url,
            "title":    title,
            "text":     body,
            "doc_type": "webpage",
            "source":   "kimi",
        }

        out_path = os.path.join(OUT_DIR, f"{KIMI_PREFIX}{saved:04d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        print(f"  [saved] ({idx}/{len(data)})  {url:<80}  {len(body):>6} chars")

    print(f"\n[kimi-import] Done. Saved={saved}, Skipped={skipped}")
    return saved


if __name__ == "__main__":
    import_kimi()
