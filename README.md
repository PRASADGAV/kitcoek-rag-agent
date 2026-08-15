# 🎓 KITCOEK RAG Assistant

A **Retrieval-Augmented Generation (RAG)** chatbot built for **KIT's College of Engineering, Kolhapur**. This project uses semantic search (BGE embeddings) + Groq LLM to answer questions about admissions, placements, departments, faculty, fees, and more.

**🔗 Live Demo:** [Coming soon on Streamlit Cloud]

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    DATA INGESTION PIPELINE                        │
│                                                                   │
│  Website (36 pages)  ──┐                                         │
│  PDFs (98 files)     ──┤──► Chunker (300w) ──► BGE Embed ──►    │
│  Kimi scrape (33pg)  ──┘         ↓              768-dim          │
│                               ChromaDB                            │
└──────────────────────────────────────────────────────────────────┘
           ↓ (1008 chunks stored)
┌──────────────────────────────────────────────────────────────────┐
│                      QUERY PIPELINE                               │
│                                                                   │
│  User Query ──► BGE Embed ──► ChromaDB (cosine) ──┐             │
│                                                     ├─► RRF       │
│              ──► BM25 tokenized search ────────────┘    Fusion   │
│                                                         ↓         │
│                                          MMR Diversity            │
│                                              ↓                    │
│                                     Top-K Chunks                  │
│                                         ↓                         │
│                              System Prompt + Context              │
│                                         ↓                         │
│                               Groq LLM (llama-3.1-8b)            │
│                                         ↓                         │
│                               Answer + Sources                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Scraping** | Playwright (headless Chrome — JS rendering) |
| **PDF Extraction** | PyMuPDF + OCR fallback |
| **Chunking** | Custom 300-word paragraph-aware splitter |
| **Embedding Model** | **BAAI/bge-base-en-v1.5** (768-dim, semantic) |
| **Vector DB** | ChromaDB (cosine similarity, HNSW index) |
| **Sparse Search** | BM25 (rank-bm25) |
| **Retrieval Fusion** | RRF (Reciprocal Rank Fusion) + MMR diversity |
| **LLM** | Groq (llama-3.1-8b-instant) |
| **UI** | Streamlit |

---

## 📦 Data Sources

- **36 web pages** scraped with Playwright (JS-rendered content)
- **98 PDFs** — syllabi, NIRF reports, NAAC certificates, brochure
- **33 pages** from Kimi deep scrape (HODs, board members, TNP stats)
- **10 curated topic files** — placement stats, admission requirements, HOD list

**Total:** 1,008 chunks covering the entire KITCOEK knowledge base.

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Groq API key (free at [console.groq.com](https://console.groq.com))

### Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/kitcoek-rag-agent.git
cd kitcoek-rag-agent

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set up environment variables
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### Run Data Ingestion

```bash
# Scrape website + extract PDFs + embed everything
python ingest.py

# This takes ~5-10 minutes and creates:
# - data/raw/pages/ (scraped web pages)
# - data/raw/pdfs/ (extracted PDF text)
# - data/chroma_db/ (vector embeddings)
```

### Launch the App

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## 🎯 Features

✅ **Semantic Search** — understands questions even with different wording  
✅ **Hybrid Retrieval** — combines semantic (BGE) + keyword (BM25) search  
✅ **Source Attribution** — every answer shows where data came from  
✅ **Category Detection** — auto-tags queries (admissions, placements, etc.)  
✅ **RAG Pipeline Visualization** — see exactly what chunks were retrieved  
✅ **Query Analytics** — track question patterns and popular topics  
✅ **Responsive UI** — works on mobile, tablet, desktop  

---

## 📂 Project Structure

```
kitcoek-rag-agent/
├── app.py                  # Streamlit UI (main entry point)
├── ingest.py               # Data pipeline (scrape → chunk → embed)
├── requirements.txt        # Python dependencies
├── packages.txt            # System dependencies (for Streamlit Cloud)
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
│
├── src/
│   ├── agent/
│   │   └── agent.py        # Main RAG agent logic
│   ├── vectorstore/
│   │   └── store.py        # ChromaDB + BGE embeddings
│   ├── retriever/
│   │   └── retriever.py    # Hybrid RRF + MMR retrieval
│   ├── scraper/
│   │   └── scraper.py      # Playwright web scraper
│   ├── chunker/
│   │   └── chunker.py      # Smart text chunking
│   └── pdf_extractor/
│       └── extractor.py    # PyMuPDF PDF parser
│
├── data/
│   ├── raw/
│   │   ├── pages/          # Scraped web pages (JSON)
│   │   └── pdfs/           # Extracted PDF text (JSON)
│   ├── chroma_db/          # Vector embeddings (auto-generated)
│   └── logs/               # Query logs (JSONL)
│
└── static/
    └── kit_gate.webp       # Background image
```

---

## 🔧 Configuration

Edit `.env` to customize:

```bash
# LLM settings
GROQ_API_KEY=your_groq_api_key_here
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-8b-instant

# Vector store
CHROMA_DB_PATH=data/chroma_db
CHROMA_COLLECTION_NAME=kitcoek
TOP_K_RESULTS=5

# Web scraper
WEBSITE_BASE_URL=https://www.kitcoek.in
PLAYWRIGHT_HEADLESS=true
```

---

## 🚢 Deploy on Streamlit Cloud

1. **Push to GitHub:**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/kitcoek-rag-agent.git
   git push -u origin main
   ```

2. **Go to [share.streamlit.io](https://share.streamlit.io)**

3. **Click "New app" → Connect GitHub repo**

4. **Add secrets in Streamlit dashboard:**
   ```toml
   GROQ_API_KEY = "your_groq_api_key"
   LLM_PROVIDER = "groq"
   LLM_MODEL = "llama-3.1-8b-instant"
   CHROMA_DB_PATH = "data/chroma_db"
   CHROMA_COLLECTION_NAME = "kitcoek"
   TOP_K_RESULTS = "5"
   ```

5. **Deploy!** 🎉

---

## 🤔 How It Works

### Why BGE > MiniLM?

`BAAI/bge-base-en-v1.5` is the current state-of-the-art embedding model for retrieval. It uses:

- **768-dimensional embeddings** (vs 384 for MiniLM)
- **Query-specific prefix** — queries embed differently from documents
- **Better semantic understanding** — "Who leads the AI department?" correctly finds "Dr. Uma P. Gurav HOD"

### Why Hybrid Search (Semantic + BM25)?

- **Semantic search** (BGE): great for paraphrases, synonyms, intent
- **BM25**: great for exact keywords, acronyms, names
- **RRF fusion**: combines both intelligently

Example:
- Query: "Who is the HOD of AIML?"
- BGE finds: documents about "department heads", "leaders", "faculty"
- BM25 finds: exact matches for "HOD", "AIML"
- RRF combines both → best result

---

## 📊 Data Quality

| Metric | Value |
|---|---|
| Total chunks | 1,008 |
| Source files | 177 (36 webpages + 98 PDFs + 43 curated) |
| Avg chunk size | ~300 words |
| Embedding dimensions | 768 |
| ChromaDB size | ~45MB |

---

## 🐛 Troubleshooting

**Issue:** `ImportError: cannot import name 'DEFAULT_EXCLUDED_CONTENT_TYPES'`  
**Fix:** Update starlette — `pip install "starlette>=0.46.0,<1.4.0"`

**Issue:** Playwright browsers not found  
**Fix:** Run `playwright install chromium`

**Issue:** Groq rate limit exceeded  
**Fix:** Wait 60s or upgrade to Groq Dev Tier

**Issue:** Knowledge base empty  
**Fix:** Run `python ingest.py` first

---

## 📝 License

MIT License — free for educational use.

---

## 👥 Credits

Built as a **Problem-Based Learning (PBL)** project for:

**KIT's College of Engineering, Kolhapur**  
R.S.No.199B/1-3, Gokul Shirgaon, Kolhapur - 416 234, Maharashtra, INDIA  
🌐 [kitcoek.in](https://www.kitcoek.in)

**Team:**
- Developer: [Your Name]
- Guide: [Guide Name]
- Department: Computer Science & Engineering

---

## 🙏 Acknowledgments

- **KITCOEK** for providing data and support
- **Groq** for free LLM API
- **HuggingFace** for BGE embeddings
- **Streamlit** for the amazing UI framework
