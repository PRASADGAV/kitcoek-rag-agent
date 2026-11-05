# Implementation Audit — KITCOEK RAG Agent

**Audited:** 2026-11-05  
**Auditor:** Kiro Agent  
**Plan reference:** KIRO_KITCOEK_RAG_PROTOTYPE_PLAN.md

---

## 1. Existing Pipeline — What Works

| Component | File | Status | Notes |
|---|---|---|---|
| BGE embeddings | `src/vectorstore/store.py` | ✅ Working | BAAI/bge-base-en-v1.5, 768-dim, MMR implemented |
| ChromaDB | `src/vectorstore/store.py` | ✅ Working | cosine space, persistent, v0.5.5 pinned |
| BM25 | `src/retriever/retriever.py` | ✅ Working | rank-bm25, lazy-built on first query |
| RRF fusion | `src/retriever/retriever.py` | ✅ Working | 0.65 vector / 0.35 BM25 weights |
| MMR diversity | `src/vectorstore/store.py` | ✅ Working | lambda=0.7 |
| Category boost | `src/retriever/retriever.py` | ✅ Working | 1.15x multiplier, not a hard filter |
| Groq LLM | `src/agent/llm.py` | ✅ Working | model=openai/gpt-oss-20b, retry x3 |
| Agent orchestration | `src/agent/agent.py` | ✅ Working | chat_history, log, sources |
| Chunker | `src/chunker/chunker.py` | ✅ Working | ~300w, category detection |
| Streamlit UI | `app.py` | ✅ Working | chat, analytics, about tabs |
| PDF extraction | `src/scraper/pdf_extractor.py` | ✅ Working | PyMuPDF |

---

## 2. Critical Weakness — The Crawler

**Current crawler (`src/scraper/crawler.py`) is NOT a recursive crawler.**

It reads a hardcoded list of ~41 URLs from `src/scraper/config.py` and fetches them.  
There is **zero link discovery**, **no recursion**, **no sitemap parsing**, and **no BFS queue**.

### Specific defects:
- `SEED_URLS` list = manual, static, 41 pages only
- No link extraction from rendered pages
- No sitemap.xml parsing
- No robots.txt checking
- No crawl depth tracking
- No crawl manifest or status recording
- No PDF discovery beyond a single page pass
- No deduplication logic
- No URL normalization
- No crawl limits enforcement
- No stop/resume capability
- Silently skips pages with <80 chars (no logging to manifest)

### Impact:
- Entire department sub-pages missed (staff, labs, activities, MOUs, etc.)
- Nested admissions year documents missed
- Most linked PDFs missed
- Knowledge base = 1,008 chunks from only 179 sources → **severely incomplete**

---

## 3. Files to Create (Phase B onwards)

### New files:
- `src/scraper/url_normalizer.py` — canonical URL + dedup logic
- `src/scraper/robots.py` — robots.txt parsing + crawl-delay
- `src/scraper/fetcher.py` — HTTP fetch with retries, streaming
- `src/scraper/playwright_fetcher.py` — JS render, DOM snapshot, safe interactions
- `src/scraper/discovery.py` — sitemap, DOM link, pagination discovery
- `src/scraper/crawl_store.py` — SQLite crawl manifest persistence
- `src/scraper/recursive_crawler.py` — BFS orchestrator (replaces crawler.py)
- `src/extractor/html_extractor.py` — main text, tables, heading hierarchy
- `src/extractor/pdf_extractor.py` — page-level, per-page metadata (replaces/extends existing)
- `src/extractor/office_extractor.py` — DOCX, PPTX, XLSX, CSV
- `src/extractor/quality_checks.py` — empty page detection, report
- `src/ingestion/classifier.py` — category/department/year detection
- `src/ingestion/metadata.py` — stable metadata schema
- `src/ingestion/deduplicator.py` — URL + content hash dedup
- `src/ingestion/chunk_pipeline.py` — metadata-aware chunking
- `src/ingestion/index_builder.py` — versioned Chroma + BM25 build

### Modified files:
- `src/scraper/config.py` — add crawler env vars, host allowlist
- `app.py` — add Crawler Dashboard tab
- `requirements.txt` — add new deps (trafilatura, python-docx, openpyxl, etc.)
- `.env.example` — add crawler config vars

### Preserved unchanged:
- `src/vectorstore/store.py` — BGE + MMR (do not touch)
- `src/retriever/retriever.py` — RRF (do not touch)
- `src/agent/agent.py` — only update prompt
- `src/agent/llm.py` — do not touch

---

## 4. Known Issues

1. ChromaDB version must stay at 0.5.5 (schema incompatibility with newer versions)
2. Groq model changes frequently — model name must be in config, not hardcoded
3. Streamlit `@st.cache_resource` prevents live config reload without server restart
4. BGE model downloads ~438MB on first run — needs network on Streamlit Cloud

---

## 5. Phase Execution Plan

- **Phase A (this doc):** ✅ Audit complete
- **Phase B:** Recursive crawler with BFS, sitemap, URL normalization, robots.txt, crawl manifest
- **Phase C:** Robust HTML + PDF + office document extraction
- **Phase D:** Deduplication, metadata schema, versioned indexing
- **Phase E:** Improved RAG prompt, citations, answer status
- **Phase F:** Streamlit Crawler Dashboard + improved student UI
- **Phase G:** Demo runbook + readiness report
