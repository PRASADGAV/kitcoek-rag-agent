"""
KITCOEKAgent — conversational RAG agent

Improvements over v1:
- System prompt is helpful-first, not refusal-first.
  If data is present → give a detailed answer.
  If data is genuinely absent → admit it honestly (not a generic fallback).
- top_k read from env at call time (not at import time).
- Context block includes doc type badge (PDF / Web) for credibility.
- Live notice fetch kept for freshness queries.
- Retry logic in LLM client handles Groq network flakiness.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.retriever.retriever import HybridRetriever
from src.vectorstore.store import VectorStore
from .llm import LLMClient

# ---------------------------------------------------------------------------
# System prompt  —  helpful-first, grounded, cites sources
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are the official KITCOEK Assistant for KIT's College of Engineering, Kolhapur (KITCOEK).

YOUR ROLE:
- Answer student and visitor questions about the college using ONLY the context provided.
- Be helpful, friendly, and specific. Use bullet points for lists of facts.
- Always cite the source number [1], [2] etc. at the end of each fact.

STRICT RULES:
1. Use ONLY the information in the context below. Never add facts from your training data.
2. If the context contains partial information, give what you have and clearly note what's missing.
3. Only if the topic has ZERO mention in the context, reply exactly:
   "I don't have details about that in my current knowledge base. Please visit https://www.kitcoek.in or call the admission helpline: 7030861199."
4. Never invent names, dates, fees, phone numbers, or exam schedules.
5. For fees or admissions, remind users that figures may change yearly and to confirm with the college.
"""

# ---------------------------------------------------------------------------
# Live notice fetcher
# ---------------------------------------------------------------------------
NOTICE_URL         = "https://www.kitcoek.in/notice"
FRESHNESS_KEYWORDS = [
    "latest", "recent", "today", "new notice", "announcement",
    "current", "upcoming", "schedule", "circular", "notification",
]


def _is_freshness_query(q: str) -> bool:
    ql = q.lower()
    return any(kw in ql for kw in FRESHNESS_KEYWORDS)


def _fetch_live_notices(timeout: int = 8) -> str:
    try:
        r = requests.get(
            NOTICE_URL, timeout=timeout,
            headers={"User-Agent": "KITCOEK-RAG-Agent/1.0"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        lines = [ln.strip() for ln in soup.get_text("\n").splitlines()
                 if len(ln.strip()) > 15]
        return "\n".join(lines[:50])
    except Exception as exc:
        print(f"[agent] Live notice fetch failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Query logger
# ---------------------------------------------------------------------------

def _log(query: str, answer: str, category: str, log_dir: str = "data/logs") -> None:
    os.makedirs(log_dir, exist_ok=True)
    entry = {
        "ts":       datetime.now(timezone.utc).isoformat(),
        "query":    query,
        "category": category,
        "preview":  answer[:150],
    }
    with open(os.path.join(log_dir, "queries.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class KITCOEKAgent:
    """
    End-to-end RAG agent for KITCOEK.

    ask(query) → {answer, sources, category, retrieved_chunks, used_live_fetch}
    """

    def __init__(
        self,
        chroma_path: str | None = None,
        top_k: int | None = None,
    ) -> None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        self._chroma_path = chroma_path or os.getenv("CHROMA_DB_PATH", "data/chroma_db")
        self._top_k       = top_k       or int(os.getenv("TOP_K_RESULTS", "4"))

        print("[agent] Initialising vector store ...")
        self._vs        = VectorStore(chroma_path=self._chroma_path)
        self._retriever = HybridRetriever(self._vs)
        self._llm       = LLMClient()

        n = self._vs.count()
        if n == 0:
            print("[agent] WARNING: vector store empty — run ingest.py first.")
        else:
            print(f"[agent] Ready. {n} chunks in store.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        query: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Process a question end-to-end and return a structured response.

        Returns
        -------
        {
            "answer":           str,
            "sources":          list[{title, url, doc_type}],
            "category":         str,
            "retrieved_chunks": list,
            "used_live_fetch":  bool,
        }
        """
        t0 = time.time()

        # ---- 1. Retrieve relevant chunks --------------------------------
        top_k     = int(os.getenv("TOP_K_RESULTS", str(self._top_k)))
        retrieved = self._retriever.retrieve(query, top_k=top_k)
        category  = retrieved[0]["category"] if retrieved else "general"

        # ---- 2. Optionally inject live notice board --------------------
        live_context    = ""
        used_live_fetch = False
        if _is_freshness_query(query):
            live_text = _fetch_live_notices()
            if live_text:
                live_context    = f"\n\n[LIVE — Notice Board fetched now]\n{live_text}"
                used_live_fetch = True

        # ---- 3. Build context block ------------------------------------
        context_block = self._retriever.format_context(retrieved) + live_context

        # ---- 4. Build prompt messages ----------------------------------
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        # Keep last 6 turns (3 Q&A pairs) for multi-turn memory
        if chat_history:
            messages.extend(chat_history[-6:])

        messages.append({
            "role": "user",
            "content": (
                f"Use ONLY the following context to answer the question.\n\n"
                f"--- CONTEXT START ---\n{context_block}\n--- CONTEXT END ---\n\n"
                f"Question: {query}"
            ),
        })

        # ---- 5. Generate answer ----------------------------------------
        answer = self._llm.chat(messages, temperature=0.1, max_tokens=600)

        # ---- 6. Deduplicate sources ------------------------------------
        seen: set[str] = set()
        sources: list[dict[str, str]] = []
        for chunk in retrieved:
            url = chunk.get("source_url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append({
                    "title":    chunk.get("title", url),
                    "url":      url,
                    "doc_type": chunk.get("doc_type", "webpage"),
                })

        # ---- 7. Log ----------------------------------------------------
        _log(query, answer, category)

        elapsed = round(time.time() - t0, 2)
        print(f"[agent] {elapsed}s | cat={category} | chunks={len(retrieved)} | sources={len(sources)}")

        return {
            "answer":           answer,
            "sources":          sources,
            "category":         category,
            "retrieved_chunks": retrieved,
            "used_live_fetch":  used_live_fetch,
        }

    def is_ready(self) -> bool:
        return self._vs.count() > 0
