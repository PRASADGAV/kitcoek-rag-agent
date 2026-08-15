# KITCOEK Assistant — RAG-Based Conversational Agent for Institutional Information Retrieval

**Project-Based Learning (PBL) Assignment**
**Institution:** KIT's College of Engineering, Kolhapur (KITCOEK)
**Target Website:** https://www.kitcoek.in
**Tool:** Kiro IDE

---

## 1. Problem Statement

Students, parents, and visitors struggle to find scattered information across the KITCOEK website — admissions, fee structure, department details, exam schedules, placement records, and notices are spread across many nested pages and linked PDFs. A conversational RAG (Retrieval-Augmented Generation) agent grounded strictly in official website content and documents solves this by giving accurate, cited answers instead of requiring manual navigation.

## 2. Objective

Build a RAG-based agent that:
- Answers natural-language questions about KITCOEK (admissions, departments, academics, exams, placements, alumni, contact, etc.)
- Is grounded only in real website/document content — no hallucination
- Cites its sources (page/PDF) for every answer
- Behaves as an *agent* — routing queries intelligently and using tools, not just doing plain retrieve-and-generate

## 3. System Architecture

```
[Scraper/Loader] → [Chunking] → [Embeddings] → [Vector DB]
                                                    ↓
[User Query] → [Query Router/Agent] → [Retriever] → [Context] → [LLM] → [Answer + Sources]
```

## 4. Step-by-Step Implementation Plan

### Step 1 — Data Collection (Ingestion)
- Crawl all internal `kitcoek.in` pages using Python (`requests` + `BeautifulSoup`, or `Scrapy`); respect `robots.txt`.
- Separately extract text from linked **PDFs** (academic calendars, fee proposals, NBA/NAAC certificates, internship policies, brochures) using `PyMuPDF` or `pdfplumber` — these carry most of the concrete factual data.
- Store raw content as structured JSON:
  ```json
  {
    "url": "...",
    "title": "...",
    "text": "...",
    "doc_type": "webpage | pdf",
    "last_updated": "..."
  }
  ```

### Step 2 — Cleaning & Chunking
- Strip repeated navbar/footer boilerplate present on every page.
- Chunk text into ~500–800 tokens with ~100-token overlap using `RecursiveCharacterTextSplitter` (LangChain) or `semchunk`.
- Attach metadata to each chunk: source URL, section/category (Admissions, CSE Dept, Exam Cell, Placement, etc.), doc type.

### Step 3 — Embeddings + Vector Database
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (free, fast) or a hosted embedding API if credits are available.
- Vector store: **ChromaDB** (simple, local, no infra cost) or **FAISS** for lower-level control. Pinecone/Weaviate optional if aiming for a "production-grade" bonus.

### Step 4 — Retrieval
- Baseline: top-k cosine similarity search (k = 4–6).
- Upgrade: **hybrid search** combining BM25 (keyword) + vector similarity — important because college data has many exact terms (department names, DTE codes, dates) that pure semantic search can miss.
- Add metadata filtering — e.g., bias retrieval toward "Exam Cell" chunks when the query mentions exams/results.

### Step 5 — Generation (LLM)
- Use an LLM API (Claude/GPT) or a local open model (Llama 3, Mistral) for a no-API-cost demo.
- System prompt must enforce groundedness:
  > "Answer only from the provided context about KIT College of Engineering Kolhapur. If the answer isn't in the context, say you don't have that information — never invent it."

### Step 6 — Agent Layer
This is what elevates the project from plain RAG to an *agent*:
- **Router** — classifies each query (admissions / placement / academic calendar / general) and routes it to the right index or action.
- **Live notice tool** — re-fetches the Notice Board page for "latest" queries, since static embeddings go stale.
- **Date/deadline extractor tool** — pulls exact dates from exam timetable / academic calendar PDFs dynamically.
- **Fallback behavior** — if nothing relevant is retrieved, respond honestly and point to the relevant page/contact instead of hallucinating.

### Step 7 — Frontend
- Fast option: Streamlit chat UI.
- Polished option: small React/Next.js chat widget.
- Always display **source citations** (page/PDF link) under each answer.

### Step 8 — Evaluation
- Build a test set of 30–50 Q&A pairs covering admissions, fees, placements, departments/HODs, and contact info, with ground-truth answers taken from the site.
- Report metrics: retrieval precision@k, answer relevancy, and a hallucination check.

## 5. Features to Stand Out for Grading

- **Source citations with links** on every answer (builds trust and traceability).
- **Multilingual support** — the site publishes Marathi news content, so handling English + Marathi queries is a strong differentiator.
- **Graceful "I don't know" handling** instead of hallucinating.
- **Freshness tool** for live notices/exam dates — shows awareness of RAG's staleness limitation.
- **Analytics dashboard** — log and chart common questions asked.
- **Voice input** (optional, via Web Speech API) for extra polish.
- **Evaluation report with metrics** — most student projects skip this; including it signals rigor.

## 6. Using Kiro IDE

Kiro is spec-driven, so structure the workflow as:
1. Write an initial spec: *"Build a RAG-based chatbot for the KIT College of Engineering website with scraping, chunking, a ChromaDB vector store, hybrid retrieval, LLM generation with citations, and a Streamlit UI."*
2. Let Kiro break the spec into tasks (data pipeline, retrieval service, agent logic, UI).
3. Implement and test module by module in this order: scraper → chunker → vector store → retriever → agent → UI.
4. Keep each completed module's spec/task documented — useful directly as your project report's "development process" section.

## 7. Suggested Tech Stack Summary

| Layer | Tool |
|---|---|
| Scraping | BeautifulSoup / Scrapy |
| PDF extraction | PyMuPDF / pdfplumber |
| Chunking | LangChain RecursiveCharacterTextSplitter |
| Embeddings | sentence-transformers (MiniLM) |
| Vector DB | ChromaDB / FAISS |
| Retrieval | Hybrid (BM25 + vector) |
| LLM | Claude / GPT / local Llama-3 / Mistral |
| Frontend | Streamlit or React |
| IDE | Kiro |

---

*Prepared as an implementation plan for the KITCOEK PBL RAG Agent assignment (100 marks).*
