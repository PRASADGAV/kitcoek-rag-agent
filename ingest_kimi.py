"""
Ingest Kimi external scraped data into the vector store.
Reads external_scrap/kitcoek_scraped_data.json, converts each URL's
full_text into a clean JSON record, and adds it to data/raw/pages/.
Then re-runs chunking + embedding.

Usage:
    python ingest_kimi.py
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Boilerplate lines to strip from Kimi's scraped output
# ---------------------------------------------------------------------------
STRIP_EXACT = {
    "kit", "your kitcoek assistant", "today", "powered by", "hashinclude",
    "powered byhashinclude", "see more", "what's in", "here ➥", "here",
    "read more", "read less", "read more ...", "read more...",
    "play testimonial", "social media connect",
    "construct astunning", "construct a", "stunning", "career perspective",
    "placement news & congratulations",
    "quick links", "our initiatives",
}

STRIP_STARTS = [
    "subscribe", "admission", "enquiry", "brochure", "download",
    "tweets by", "follow us", "join now",
]


def clean_kimi_text(text: str) -> str:
    """Remove boilerplate from Kimi full_text and return clean content."""
    lines = text.splitlines()
    seen: set[str] = set()
    clean: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        low = line.lower()

        if low in STRIP_EXACT:
            continue
        if any(low.startswith(s) for s in STRIP_STARTS):
            continue
        if len(line) <= 3:
            continue
        if re.fullmatch(r"[\W\d]+", line):
            continue

        # dedup
        if low in seen:
            continue
        seen.add(low)
        clean.append(line)

    text = "\n".join(clean)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    kimi_json = os.path.join("external_scrap", "kitcoek_scraped_data.json")
    if not os.path.exists(kimi_json):
        print(f"ERROR: {kimi_json} not found.")
        sys.exit(1)

    with open(kimi_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs("data/raw/pages", exist_ok=True)

    # Find the next available page number
    existing = [
        f for f in os.listdir("data/raw/pages")
        if f.startswith("kimi_") and f.endswith(".json")
    ]
    # Remove old kimi files to avoid duplicates
    for f in existing:
        os.remove(os.path.join("data/raw/pages", f))

    saved = 0
    for url, page_data in data.items():
        full_text = page_data.get("full_text", "").strip()
        if not full_text:
            continue

        text = clean_kimi_text(full_text)
        if len(text) < 80:
            print(f"  [skip:thin] {url}")
            continue

        title = page_data.get("title", "") or url
        # Clean up title
        if title in ("No Title", "Facebook", ""):
            # Try to get a meaningful title from the URL slug
            slug = url.rstrip("/").split("/")[-1]
            slug = slug.replace("-", " ").replace("_", " ").title()
            title = f"KITCOEK - {slug}" if slug else url

        record = {
            "url":      url,
            "title":    title,
            "text":     text,
            "doc_type": "webpage",
        }
        saved += 1
        out_path = os.path.join("data", "raw", "pages", f"kimi_{saved:04d}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print(f"  [saved] kimi_{saved:04d}.json | {len(text):,} chars | {url}")

    print(f"\n[kimi] Saved {saved} pages from Kimi scrape.")
    print("[kimi] Now re-running ingest (chunk + embed)...\n")

    # Re-run ingest
    from src.chunker.chunker import chunk_documents
    from src.vectorstore.store import VectorStore

    chunks = chunk_documents(raw_dir="data/raw", chunk_size=300, overlap=50)
    if not chunks:
        print("ERROR: No chunks produced.")
        sys.exit(1)

    print(f"[kimi] {len(chunks)} total chunks ready for embedding.")
    vs = VectorStore()
    vs.build(chunks, reset=True)

    print(f"\n[kimi] DONE. {vs.count()} chunks stored in ChromaDB.")
    print("[kimi] Launch the app:  streamlit run app.py")


if __name__ == "__main__":
    main()
