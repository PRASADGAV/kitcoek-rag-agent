"""
KITCOEK RAG Agent — Ingest Pipeline
====================================
Orchestrates the full data pipeline:

  Step 1 — Crawl kitcoek.in  (scraper/crawler.py)
  Step 2 — Extract PDFs       (scraper/pdf_extractor.py)
  Step 3 — Chunk documents    (chunker/chunker.py)
  Step 4 — Embed + store      (vectorstore/store.py)

Run once before launching the app:
    python ingest.py

Flags:
    --skip-crawl     Skip Step 1 (use existing data/raw files)
    --skip-pdf       Skip Step 2
    --reset          Drop and rebuild the vector store from scratch
    --raw-dir PATH   Path to raw JSON files (default: data/raw)
"""

import argparse
import os
import sys
import time


def _banner(step: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  STEP {step}: {title}")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="KITCOEK ingest pipeline")
    parser.add_argument("--skip-crawl", action="store_true", help="Skip web crawl")
    parser.add_argument("--skip-pdf",   action="store_true", help="Skip PDF extraction")
    parser.add_argument("--reset",      action="store_true", help="Reset vector store before ingesting")
    parser.add_argument("--raw-dir",    default="data/raw",  help="Directory with raw JSON files")
    args = parser.parse_args()

    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    total_start = time.time()

    # ------------------------------------------------------------------
    # STEP 1 — Web crawl
    # ------------------------------------------------------------------
    if args.skip_crawl:
        print("\n[ingest] Skipping web crawl (--skip-crawl).")
    else:
        _banner(1, "Web Crawl — kitcoek.in")
        from src.scraper.crawler import crawl
        crawl()

    # ------------------------------------------------------------------
    # STEP 2 — PDF extraction
    # ------------------------------------------------------------------
    if args.skip_pdf:
        print("\n[ingest] Skipping PDF extraction (--skip-pdf).")
    else:
        _banner(2, "PDF Extraction")
        pdf_links_path = os.path.join("data", "raw", "pdf_links.json")
        if not os.path.exists(pdf_links_path):
            print("[ingest] No pdf_links.json found — skipping PDF extraction.")
            print("[ingest] Run the crawler first (or without --skip-crawl).")
        else:
            from src.scraper.pdf_extractor import extract_pdfs
            extract_pdfs()

    # ------------------------------------------------------------------
    # STEP 3 — Chunk documents
    # ------------------------------------------------------------------
    _banner(3, "Chunking Documents")
    from src.chunker.chunker import chunk_documents

    raw_dir = args.raw_dir
    if not os.path.isdir(raw_dir):
        print(f"[ingest] ERROR: Raw directory not found: {raw_dir}")
        print("[ingest] Run the crawler first, or provide --raw-dir PATH")
        sys.exit(1)

    chunks = chunk_documents(raw_dir=raw_dir, chunk_size=600, overlap=100)

    if not chunks:
        print("[ingest] ERROR: No chunks produced. Check that raw JSON files exist.")
        sys.exit(1)

    print(f"[ingest] OK: {len(chunks)} chunks ready for embedding.")

    # ------------------------------------------------------------------
    # STEP 4 — Embed + store in ChromaDB
    # ------------------------------------------------------------------
    _banner(4, "Embedding + Storing in ChromaDB")
    from src.vectorstore.store import VectorStore

    chroma_path     = os.getenv("CHROMA_DB_PATH",       "data/chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "kitcoek")

    vs = VectorStore(chroma_path=chroma_path, collection_name=collection_name)
    vs.build(chunks, reset=args.reset)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = round(time.time() - total_start, 1)
    total_stored = vs.count()

    print(f"\n{'='*60}")
    print("  INGEST COMPLETE")
    print(f"{'='*60}")
    print(f"  Chunks processed : {len(chunks)}")
    print(f"  Chunks in store  : {total_stored}")
    print(f"  ChromaDB path    : {chroma_path}")
    print(f"  Total time       : {elapsed}s")
    print(f"{'='*60}")
    print("\nDone! Launch the app with:  streamlit run app.py\n")


if __name__ == "__main__":
    main()
