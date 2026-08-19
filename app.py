"""
KITCOEK RAG Assistant — UI
A proper RAG bot interface that visually shows:
  - The retrieval pipeline (query → chunks → answer)
  - Retrieved source chunks with relevance scores
  - Source cards with links
  - Chat history with role avatars
"""

import json
import os
import base64
from collections import Counter
from datetime import datetime

import streamlit as st


def _get_bg_b64() -> str:
    """Return base64-encoded background image string for CSS."""
    img_dir = "static"
    for f in os.listdir(img_dir) if os.path.isdir(img_dir) else []:
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            path = os.path.join(img_dir, f)
            ext  = f.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            return f"data:image/{mime};base64,{b64}"
    return ""

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KITCOEK RAG Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
_BG = _get_bg_b64()
_BG_CSS = f"""
/* ── Background image with low opacity ── */
.stApp {{
    position: relative;
}}
.stApp::before {{
    content: "";
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background-image: url('{_BG}');
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    background-attachment: fixed;
    opacity: 0.10;
    z-index: 0;
    pointer-events: none;
}}
.stApp > * {{ position: relative; z-index: 1; }}
""" if _BG else ""

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}

{_BG_CSS}

/* ── Main background — semi-transparent white so text stays readable ── */
.main .block-container {{
    padding-top: 1.5rem;
    padding-bottom: 2rem;
    max-width: 1100px;
    background: rgba(255,255,255,0.82);
    border-radius: 12px;
    backdrop-filter: blur(2px);
}}

/* ── Sidebar ── */
section[data-testid="stSidebar"] {{
    background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%);
}}
section[data-testid="stSidebar"] * {{ color: #e2e8f0 !important; }}
section[data-testid="stSidebar"] .stButton > button {{
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    color: #e2e8f0 !important;
    border-radius: 8px;
    width: 100%;
    text-align: left;
    padding: 8px 12px;
    font-size: 0.85rem;
    transition: all 0.2s;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(99,102,241,0.3);
    border-color: rgba(99,102,241,0.5);
}}

/* ── Chat messages ── */
.user-msg-wrap {{
    display: flex; justify-content: flex-end;
    margin: 12px 0;
}}
.user-bubble {{
    background: linear-gradient(135deg, #4f46e5, #7c3aed);
    color: white;
    border-radius: 18px 18px 4px 18px;
    padding: 12px 18px;
    max-width: 72%;
    font-size: 0.95rem;
    line-height: 1.5;
    box-shadow: 0 2px 12px rgba(79,70,229,0.3);
}}
.bot-msg-wrap {{
    display: flex; justify-content: flex-start;
    margin: 12px 0;
}}
.bot-bubble {{
    background: rgba(255,255,255,0.95);
    color: #1e293b;
    border-radius: 18px 18px 18px 4px;
    padding: 14px 18px;
    max-width: 72%;
    font-size: 0.95rem;
    line-height: 1.6;
    border: 1px solid #e2e8f0;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}}

/* ── Pipeline step badge ── */
.pipeline-step {{
    display: inline-flex; align-items: center; gap: 6px;
    background: #f1f5f9; border: 1px solid #e2e8f0;
    border-radius: 20px; padding: 3px 12px;
    font-size: 0.75rem; font-weight: 600; color: #475569;
    margin: 2px 3px;
}}
.pipeline-step.done {{
    background: #f0fdf4; border-color: #bbf7d0; color: #16a34a;
}}

/* ── Source card ── */
.source-card {{
    background: rgba(248,250,252,0.95);
    border: 1px solid #e2e8f0;
    border-left: 3px solid #6366f1;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 6px 0;
    font-size: 0.82rem;
}}
.source-card:hover {{ border-left-color: #4f46e5; background: #f1f5f9; }}
.source-title {{ font-weight: 600; color: #1e293b; }}
.source-url   {{ color: #6366f1; font-size: 0.78rem; }}
.source-snippet {{ color: #64748b; margin-top: 4px; font-size: 0.80rem; line-height: 1.4; }}

/* ── Score bar ── */
.score-bar-wrap {{ display: flex; align-items: center; gap: 8px; margin-top: 4px; }}
.score-bar {{
    height: 4px; border-radius: 2px;
    background: linear-gradient(90deg, #6366f1, #a855f7);
}}
.score-label {{ font-size: 0.72rem; color: #94a3b8; }}

/* ── Category badge ── */
.cat-badge {{
    display: inline-block;
    background: #ede9fe; color: #6d28d9;
    border-radius: 6px; padding: 1px 8px;
    font-size: 0.72rem; font-weight: 600;
    margin-right: 4px;
}}
.live-badge {{
    display: inline-block;
    background: #dcfce7; color: #15803d;
    border-radius: 6px; padding: 1px 8px;
    font-size: 0.72rem; font-weight: 600;
}}

/* ── RAG pipeline visual ── */
.rag-pipeline {{
    background: #0f172a;
    border-radius: 12px;
    padding: 12px 16px;
    margin: 6px 0 10px 0;
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
    font-size: 0.78rem;
}}
.pipe-node {{
    background: rgba(99,102,241,0.15);
    border: 1px solid rgba(99,102,241,0.3);
    color: #a5b4fc;
    border-radius: 6px; padding: 4px 10px;
    font-weight: 500;
}}
.pipe-arrow {{ color: #475569; font-size: 0.9rem; }}
.pipe-node.highlight {{
    background: rgba(99,102,241,0.35);
    border-color: #6366f1; color: #e0e7ff;
}}

/* ── Welcome screen ── */
.welcome-card {{
    background: rgba(240,244,255,0.92);
    border: 1px solid #ddd6fe;
    border-radius: 16px;
    padding: 32px;
    text-align: center;
    margin: 20px 0;
    backdrop-filter: blur(4px);
}}
.welcome-title {{ font-size: 1.6rem; font-weight: 700; color: #1e293b; margin-bottom: 8px; }}
.welcome-sub {{ color: #64748b; font-size: 0.95rem; margin-bottom: 20px; }}
.feature-grid {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 16px; }}
.feature-chip {{
    background: white; border: 1px solid #e2e8f0;
    border-radius: 20px; padding: 6px 14px;
    font-size: 0.82rem; color: #4f46e5; font-weight: 500;
}}

/* ── Chunk preview card ── */
.chunk-card {{
    background: rgba(255,255,255,0.95);
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 4px 0;
    font-size: 0.80rem;
    color: #334155;
    line-height: 1.5;
}}
.chunk-meta {{ color: #94a3b8; font-size: 0.72rem; margin-bottom: 4px; }}
</style>
""", unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────────────────────
def _init():
    for k, v in {
        "messages":    [],   # {role, content, meta}
        "agent":       None,
        "ready":       False,
        "err":         None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── Agent loader ───────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _load_agent():
    # Load secrets from Streamlit Cloud OR local .env
    import os
    try:
        # Streamlit Cloud: read from st.secrets
        secrets = st.secrets
        os.environ.setdefault("GROQ_API_KEY",            secrets.get("GROQ_API_KEY", ""))
        os.environ.setdefault("LLM_PROVIDER",            secrets.get("LLM_PROVIDER", "groq"))
        os.environ.setdefault("LLM_MODEL",               secrets.get("LLM_MODEL", "llama-3.3-70b-versatile"))
        os.environ.setdefault("CHROMA_DB_PATH",          secrets.get("CHROMA_DB_PATH", "data/chroma_db"))
        os.environ.setdefault("CHROMA_COLLECTION_NAME",  secrets.get("CHROMA_COLLECTION_NAME", "kitcoek"))
        os.environ.setdefault("TOP_K_RESULTS",           secrets.get("TOP_K_RESULTS", "5"))
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Auto-setup database on first run
    from setup_database import check_database_exists, setup_database
    if not check_database_exists():
        import streamlit as st
        with st.spinner("⚠️ Vector database not found. Creating from pre-scraped data (2-3 minutes)..."):
            try:
                success = setup_database()
                if not success:
                    st.error("❌ Failed to initialize database. Check deployment logs for details.")
                    st.error("You may need to run `python ingest.py` locally and include the database in Git LFS.")
                    st.stop()
                st.success("✅ Database initialized successfully!")
                st.rerun()  # Reload to use the new database
            except Exception as e:
                st.error(f"❌ Error during database setup: {e}")
                import traceback
                st.code(traceback.format_exc())
                st.stop()
    
    from src.agent.agent import KITCOEKAgent
    return KITCOEKAgent()


def _get_agent():
    if st.session_state["agent"] is None:
        with st.spinner("🔄 Loading KITCOEK RAG Agent..."):
            try:
                a = _load_agent()
                st.session_state["agent"] = a
                st.session_state["ready"] = a.is_ready()
            except Exception as e:
                st.session_state["err"] = str(e)
    return st.session_state["agent"]


# ── Helpers ───────────────────────────────────────────────────────────────────
CATEGORY_ICONS = {
    "admissions":  "📋",
    "fees":        "💰",
    "academics":   "📚",
    "exams":       "📝",
    "placements":  "💼",
    "departments": "🏛️",
    "research":    "🔬",
    "campus":      "🏫",
    "contact":     "📞",
    "notices":     "📢",
    "naac_nba":    "🏆",
    "people":      "👤",
    "general":     "💬",
}

def _cat_icon(cat: str) -> str:
    return CATEGORY_ICONS.get(cat.lower(), "💬")


def _score_color(score: float) -> str:
    if score >= 0.05:   return "#16a34a"
    if score >= 0.03:   return "#d97706"
    return "#dc2626"


def _render_user(content: str):
    st.markdown(f"""
    <div class="user-msg-wrap">
        <div class="user-bubble">👤 &nbsp;{content}</div>
    </div>""", unsafe_allow_html=True)


def _render_bot(content: str, meta: dict):
    cat  = meta.get("category", "general")
    live = meta.get("used_live_fetch", False)
    icon = _cat_icon(cat)

    badges = f'<span class="cat-badge">{icon} {cat.capitalize()}</span>'
    if live:
        badges += ' <span class="live-badge">🔴 Live data</span>'

    st.markdown(f"""
    <div class="bot-msg-wrap">
        <div class="bot-bubble">
            <div style="margin-bottom:8px">{badges}</div>
            {content}
        </div>
    </div>""", unsafe_allow_html=True)


def _render_rag_pipeline(chunks: list, query: str):
    """Show the RAG pipeline visually — Query → Embed → Retrieve → Generate → Answer"""
    n_chunks = len(chunks)
    st.markdown(f"""
    <div class="rag-pipeline">
        <span class="pipe-node">🔤 Query</span>
        <span class="pipe-arrow">→</span>
        <span class="pipe-node">🧠 BGE Embed</span>
        <span class="pipe-arrow">→</span>
        <span class="pipe-node highlight">🔍 Retrieved {n_chunks} chunks</span>
        <span class="pipe-arrow">→</span>
        <span class="pipe-node">⚡ Groq LLM</span>
        <span class="pipe-arrow">→</span>
        <span class="pipe-node">✅ Answer</span>
    </div>""", unsafe_allow_html=True)


def _render_source_cards(sources: list, chunks: list):
    """Render retrieved source chunks with relevance scores."""
    if not sources and not chunks:
        return

    with st.expander(f"📂 Retrieved Context — {len(chunks)} chunks used", expanded=False):
        # Pipeline visual
        if chunks:
            _render_rag_pipeline(chunks, "")

        # Chunk details
        if chunks:
            st.markdown("**🔍 Retrieved Chunks (ranked by relevance):**")
            for i, chunk in enumerate(chunks, 1):
                score    = chunk.get("score", 0)
                cat      = chunk.get("category", "general")
                doc_type = chunk.get("doc_type", "webpage")
                title    = chunk.get("title", chunk.get("source_url", ""))[:60]
                text     = chunk.get("text", "")[:220]
                bar_w    = min(int(score * 1000), 100)
                bar_color = _score_color(score)
                doc_icon = "📄" if doc_type == "pdf" else "🌐"

                st.markdown(f"""
                <div class="chunk-card">
                    <div class="chunk-meta">
                        {doc_icon} Chunk {i} &nbsp;·&nbsp;
                        <span class="cat-badge">{_cat_icon(cat)} {cat}</span>
                        &nbsp;·&nbsp; {title}
                    </div>
                    <div class="score-bar-wrap">
                        <div class="score-bar" style="width:{bar_w}%; background:linear-gradient(90deg,{bar_color},{bar_color}aa);"></div>
                        <span class="score-label">relevance: {score:.4f}</span>
                    </div>
                    <div style="margin-top:6px;color:#334155">{text}{'...' if len(chunk.get('text','')) > 220 else ''}</div>
                </div>""", unsafe_allow_html=True)

        # Source links
        if sources:
            st.markdown("**🔗 Sources:**")
            for src in sources:
                url      = src.get("url", "#")
                title    = src.get("title", url)[:70]
                doc_type = src.get("doc_type", "webpage")
                icon     = "📄" if doc_type == "pdf" else "🌐"
                st.markdown(f"""
                <div class="source-card">
                    <div class="source-title">{icon} {title}</div>
                    <div class="source-url"><a href="{url}" target="_blank">{url[:80]}</a></div>
                </div>""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
def _sidebar():
    with st.sidebar:
        # Logo + title
        st.markdown("""
        <div style="text-align:center;padding:16px 0 8px 0">
            <div style="font-size:2.5rem">🎓</div>
            <div style="font-size:1.1rem;font-weight:700;color:#e2e8f0">KITCOEK</div>
            <div style="font-size:0.78rem;color:#94a3b8;margin-top:2px">RAG Assistant</div>
        </div>""", unsafe_allow_html=True)

        st.divider()

        # RAG info box
        agent = st.session_state.get("agent")
        chunk_count = agent._vs.count() if agent else 0
        st.markdown(f"""
        <div style="background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.2);
                    border-radius:10px;padding:12px;margin-bottom:12px">
            <div style="font-size:0.75rem;font-weight:600;color:#a5b4fc;margin-bottom:6px">
                ⚡ RAG PIPELINE STATUS
            </div>
            <div style="font-size:0.78rem;color:#94a3b8;line-height:1.8">
                🧠 Model: <b style="color:#c7d2fe">BGE-base-en-v1.5</b><br>
                📦 Embeddings: <b style="color:#c7d2fe">768-dim</b><br>
                🗄️ Chunks: <b style="color:#c7d2fe">{chunk_count:,}</b><br>
                🔍 Search: <b style="color:#c7d2fe">Hybrid (Semantic + BM25)</b><br>
                ⚡ LLM: <b style="color:#c7d2fe">Groq llama-3.1-8b</b>
            </div>
        </div>""", unsafe_allow_html=True)

        st.markdown("**💡 Quick Questions**")
        quick = [
            ("🎓", "What departments are offered?"),
            ("👤", "Who is the HOD of AIML?"),
            ("💼", "Placement stats — packages and companies"),
            ("💰", "What scholarships are available?"),
            ("📋", "Admission process for B.Tech"),
            ("🏆", "NAAC and NBA accreditation status"),
            ("👨‍💼", "Who is the director of KITCOEK?"),
            ("📞", "Contact numbers and address"),
            ("📚", "CSE department details"),
            ("🔬", "Research centres and PhD programs"),
        ]
        for icon, q in quick:
            if st.button(f"{icon}  {q}", key=f"q_{q[:25]}"):
                _submit(q)

        st.divider()

        # Session stats
        msgs  = st.session_state["messages"]
        asked = sum(1 for m in msgs if m["role"] == "user")
        if asked:
            cats = [m["meta"].get("category","") for m in msgs if m["role"]=="assistant" and m.get("meta")]
            top  = Counter(cats).most_common(1)[0][0].capitalize() if cats else "—"
            c1, c2 = st.columns(2)
            c1.metric("Asked", asked)
            c2.metric("Top topic", top)

        if asked:
            if st.button("🗑️  Clear chat", use_container_width=True):
                st.session_state["messages"] = []
                st.rerun()

        st.markdown("""
        <div style="margin-top:16px;font-size:0.72rem;color:#475569;text-align:center;line-height:1.6">
            Data sourced from kitcoek.in<br>
            Verify critical info with college directly
        </div>""", unsafe_allow_html=True)


# ── Submit query ──────────────────────────────────────────────────────────────
def _submit(query: str):
    query = query.strip()
    if not query:
        return

    st.session_state["messages"].append({"role": "user", "content": query, "meta": {}})

    agent = _get_agent()
    if agent is None:
        st.session_state["messages"].append({
            "role": "assistant", "content": "⚠️ Could not load agent.", "meta": {}
        })
        st.rerun()
        return

    if not st.session_state["ready"]:
        st.session_state["messages"].append({
            "role": "assistant",
            "content": "⚠️ Knowledge base is empty. Run `python ingest.py` first.",
            "meta": {}
        })
        st.rerun()
        return

    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state["messages"][:-1]
        if m["role"] in ("user", "assistant")
    ]

    with st.spinner("🔍 Retrieving relevant chunks..."):
        try:
            result = agent.ask(query, chat_history=history)
            st.session_state["messages"].append({
                "role":    "assistant",
                "content": result["answer"],
                "meta": {
                    "sources":          result["sources"],
                    "category":         result["category"],
                    "used_live_fetch":  result["used_live_fetch"],
                    "retrieved_chunks": result["retrieved_chunks"],
                }
            })
        except Exception as e:
            st.session_state["messages"].append({
                "role": "assistant",
                "content": f"⚠️ Error: {e}",
                "meta": {}
            })
    st.rerun()


# ── Analytics tab ─────────────────────────────────────────────────────────────
def _analytics():
    st.markdown("## 📊 Query Analytics")
    log_path = "data/logs/queries.jsonl"
    if not os.path.exists(log_path):
        st.info("No queries logged yet. Start chatting!")
        return

    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except:
                pass

    if not entries:
        st.info("Log file is empty.")
        return

    # Metrics row
    c1, c2, c3, c4 = st.columns(4)
    cats = [e.get("category","general") for e in entries]
    c1.metric("Total Queries", len(entries))
    c2.metric("Unique Categories", len(set(cats)))
    c3.metric("Top Category", Counter(cats).most_common(1)[0][0].capitalize())
    c4.metric("Latest Query", entries[-1]["ts"][:10] if entries else "—")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Queries by Category")
        import pandas as pd
        df = pd.DataFrame({"Category": list(Counter(cats).keys()),
                           "Count":    list(Counter(cats).values())}) \
               .sort_values("Count", ascending=False)
        st.bar_chart(df.set_index("Category"))

    with col2:
        st.subheader("Recent Queries")
        recent = entries[-15:][::-1]
        df2 = pd.DataFrame([{
            "Time":     e.get("ts","")[:16].replace("T"," "),
            "Category": e.get("category",""),
            "Query":    e.get("query","")[:60],
        } for e in recent])
        st.dataframe(df2, use_container_width=True, hide_index=True)


# ── About tab ─────────────────────────────────────────────────────────────────
def _about():
    st.markdown("""
## 🤖 About KITCOEK RAG Assistant

This is a **Retrieval-Augmented Generation (RAG)** chatbot built as a PBL project
for KIT's College of Engineering, Kolhapur.

### 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DATA INGESTION PIPELINE                      │
│                                                                  │
│  Website (41 pages)  ──┐                                        │
│  PDFs (98 files)     ──┤──► Chunker (300w) ──► BGE Embed ──►   │
│  Kimi scrape (33pg)  ──┘         ↓              768-dim         │
│                              ChromaDB                           │
└─────────────────────────────────────────────────────────────────┘
          ↓ (stored)
┌─────────────────────────────────────────────────────────────────┐
│                     QUERY PIPELINE                               │
│                                                                  │
│  User Query ──► BGE Embed ──► ChromaDB (cosine) ──┐            │
│                                                     ├─► RRF    │
│              ──► BM25 tokenized search ────────────┘    Fusion │
│                                                         ↓       │
│                                          MMR Diversity          │
│                                              ↓                  │
│                                     Top-K Chunks                │
│                                         ↓                       │
│                              System Prompt + Context            │
│                                         ↓                       │
│                               Groq LLM (llama-3.1-8b)          │
│                                         ↓                       │
│                               Answer + Sources                  │
└─────────────────────────────────────────────────────────────────┘
```

### 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Scraping | **Playwright** (headless Chrome — handles JS SPAs) |
| PDF Extraction | **PyMuPDF** + OCR fallback |
| Chunking | Custom 300-word paragraph-aware splitter |
| Embedding Model | **BAAI/bge-base-en-v1.5** (768-dim, semantic) |
| Vector DB | **ChromaDB** (cosine similarity, HNSW index) |
| Sparse Search | **BM25** (rank-bm25) |
| Retrieval Fusion | **RRF** (Reciprocal Rank Fusion) + **MMR** diversity |
| LLM | **Groq** (llama3-8b-8192) |
| UI | **Streamlit** |

### 📦 Data Sources
- **36 web pages** scraped with Playwright (JS-rendered)
- **98 PDFs** — syllabi, NIRF reports, NAAC certificates, brochure
- **33 pages** from Kimi deep scrape (HODs, board, TNP stats)
- **10 curated topic files** — placement stats, admission requirements, HOD list

### ⚡ Why BGE > MiniLM?
`BAAI/bge-base-en-v1.5` uses a **retrieval-specific query prefix** to embed questions
differently from documents, leading to much better semantic matching.
"Who leads the AI department?" → finds "Dr. Uma P. Gurav HOD" correctly.
""")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    _sidebar()

    # Ensure agent is loaded
    if st.session_state["agent"] is None:
        _get_agent()

    # Error banner
    if st.session_state["err"]:
        st.error(f"⚠️ {st.session_state['err']}")

    # Tabs
    tab_chat, tab_analytics, tab_about = st.tabs(["💬  Chat", "📊  Analytics", "ℹ️  About"])

    # ── CHAT ─────────────────────────────────────────────────────────────────
    with tab_chat:
        # Header
        st.markdown("""
        <div style="margin-bottom:16px">
            <h2 style="color:#1e293b;margin:0;font-size:1.6rem;font-weight:700">
                🎓 KITCOEK RAG Assistant
            </h2>
            <p style="color:#64748b;margin:4px 0 0 0;font-size:0.9rem">
                Powered by semantic search (BGE-768) + Groq LLM · Ask anything about KITCOEK
            </p>
        </div>""", unsafe_allow_html=True)

        # Not ready warning
        if st.session_state["agent"] and not st.session_state["ready"]:
            st.warning("Knowledge base is empty. Run `python ingest.py` first.")

        # ── Chat history ────────────────────────────────────────────────
        msgs = st.session_state["messages"]

        if not msgs:
            st.markdown("""
            <div class="welcome-card">
                <div class="welcome-title">👋 Welcome to KITCOEK RAG Assistant</div>
                <div class="welcome-sub">
                    A Retrieval-Augmented Generation bot that searches 1,000+ chunks<br>
                    from the official KITCOEK website, PDFs, and documents to answer your questions.
                </div>
                <div style="background:#0f172a;border-radius:10px;padding:12px 16px;
                            display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap">
                    <span style="color:#6366f1;font-size:0.78rem;font-weight:600">RAG PIPELINE:</span>
                    <span style="color:#94a3b8;font-size:0.78rem">Your Query</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#a5b4fc;font-size:0.78rem">BGE Embed</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#a5b4fc;font-size:0.78rem">Semantic Search</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#a5b4fc;font-size:0.78rem">BM25 Search</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#a5b4fc;font-size:0.78rem">RRF Fusion</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#86efac;font-size:0.78rem">Groq LLM</span>
                    <span style="color:#475569">→</span>
                    <span style="color:#6ee7b7;font-size:0.78rem">Answer</span>
                </div>
                <div class="feature-grid">
                    <span class="feature-chip">📋 Admissions</span>
                    <span class="feature-chip">👤 HODs & Faculty</span>
                    <span class="feature-chip">💼 Placements</span>
                    <span class="feature-chip">📚 Syllabus</span>
                    <span class="feature-chip">💰 Fees & Scholarships</span>
                    <span class="feature-chip">🏛️ Departments</span>
                    <span class="feature-chip">🔬 Research</span>
                    <span class="feature-chip">🏆 NAAC/NBA</span>
                </div>
            </div>""", unsafe_allow_html=True)
        else:
            for msg in msgs:
                if msg["role"] == "user":
                    _render_user(msg["content"])
                else:
                    _render_bot(msg["content"], msg.get("meta", {}))
                    meta = msg.get("meta", {})
                    chunks  = meta.get("retrieved_chunks", [])
                    sources = meta.get("sources", [])
                    if chunks or sources:
                        _render_source_cards(sources, chunks)

        # ── Input row ────────────────────────────────────────────────────
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        col_in, col_btn = st.columns([8, 1])
        with col_in:
            user_input = st.text_input(
                label="chat",
                placeholder="Ask about departments, HODs, placements, fees, admissions...",
                label_visibility="collapsed",
                key="chat_input",
            )
        with col_btn:
            send = st.button("Send ➤", type="primary", use_container_width=True)

        if send and user_input:
            _submit(user_input)

    # ── ANALYTICS ───────────────────────────────────────────────────────
    with tab_analytics:
        _analytics()

    # ── ABOUT ───────────────────────────────────────────────────────────
    with tab_about:
        _about()


if __name__ == "__main__":
    main()
