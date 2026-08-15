"""
Hybrid Retriever — KITCOEK RAG Agent

Dense (semantic) + Sparse (BM25) fusion via Reciprocal Rank Fusion (RRF).

Key fixes over v1:
- Category pre-filter REMOVED — it was cutting relevant results.
  Category hint is now only used for score boosting, never filtering.
- top_k read correctly from env at call time, not module load time.
- BM25 index rebuilt automatically after re-ingest (invalidate_bm25).
- format_context: 200-word cap per chunk, numbered sources.
"""

import re
from typing import Any

from rank_bm25 import BM25Okapi

from src.vectorstore.store import VectorStore

RRF_K           = 60
VECTOR_WEIGHT   = 0.65
BM25_WEIGHT     = 1.0 - VECTOR_WEIGHT
# Bonus multiplier for chunks whose category matches the query hint
CATEGORY_BOOST  = 1.15
# Max words per chunk when formatting context for LLM
MAX_CONTEXT_WORDS_PER_CHUNK = 200


# ---------------------------------------------------------------------------
# Query → category hint  (boost only, never filter)
# ---------------------------------------------------------------------------
QUERY_HINTS: dict[str, list[str]] = {
    "admissions":  ["admission", "admit", "dte", "cap", "cutoff", "apply",
                    "eligibility", "jee", "mht-cet", "lateral", "fy", "first year"],
    "fees":        ["fee", "fees", "tuition", "cost", "scholarship", "payment",
                    "fee structure", "charges", "freeship", "concession"],
    "academics":   ["syllabus", "course", "semester", "curriculum", "timetable",
                    "academic calendar", "nep", "structure", "credit"],
    "exams":       ["exam", "examination", "result", "marks", "grade", "cgpa",
                    "sgpa", "backlog", "hall ticket", "revaluation", "paper",
                    "question paper"],
    "placements":  ["placement", "placed", "recruit", "campus drive", "company",
                    "package", "lpa", "internship", "tnp", "hiring", "ctc"],
    "departments": ["department", "cse", "it", "mechanical", "civil",
                    "electrical", "entc", "hod", "faculty", "biotechnology",
                    "environmental", "aiml", "csbs", "basic science"],
    "notices":     ["notice", "circular", "announcement", "latest", "update",
                    "new", "today", "upcoming", "schedule"],
    "contact":     ["contact", "phone", "email", "address", "reach",
                    "location", "helpline", "mobile"],
    "naac_nba":    ["naac", "nba", "accreditation", "ranking", "nirf",
                    "grade", "autonomous"],
    "people":      ["director", "principal", "hod", "professor", "dean",
                    "staff", "trustee", "board", "vanarotti", "shinde",
                    "who is", "name of"],
}


def _category_hint(query: str) -> str | None:
    q = query.lower()
    scores = {
        cat: sum(1 for kw in kws if kw in q)
        for cat, kws in QUERY_HINTS.items()
    }
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else None


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _rrf(rank: int, k: int = RRF_K) -> float:
    return 1.0 / (k + rank)


class HybridRetriever:
    """
    Dense semantic search (ChromaDB/MiniLM) + BM25 keyword search,
    fused with RRF and optional category score boost.
    """

    def __init__(self, vector_store: VectorStore) -> None:
        self._vs             = vector_store
        self._bm25: BM25Okapi | None = None
        self._corpus: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # BM25 index
    # ------------------------------------------------------------------

    def _ensure_bm25(self) -> None:
        if self._bm25 is not None:
            return
        print("[retriever] Building BM25 index ...")
        self._corpus = self._vs.get_all_chunks()
        if not self._corpus:
            print("[retriever] WARNING: vector store is empty — run ingest first.")
            return
        self._bm25 = BM25Okapi([_tokenize(c["text"]) for c in self._corpus])
        print(f"[retriever] BM25 ready ({len(self._corpus)} docs).")

    def invalidate_bm25(self) -> None:
        """Call after re-ingesting to force BM25 rebuild on next query."""
        self._bm25   = None
        self._corpus = []

    # ------------------------------------------------------------------
    # Core retrieve
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Return top_k most relevant chunks for query.

        Pipeline:
        1. Dense search via MMR-enabled VectorStore (fetches top_k*3 candidates)
        2. BM25 keyword search over all chunks
        3. RRF fusion of both ranked lists
        4. Category boost for chunks matching the query topic
        5. Return top_k results
        """
        self._ensure_bm25()

        hint    = _category_hint(query)
        fetch_k = top_k * 3

        # ---- Dense retrieval (no category filter — use full corpus) ----
        dense = self._vs.search(query, top_k=fetch_k, fetch_k=fetch_k * 2)

        # ---- BM25 retrieval -------------------------------------------
        bm25_hits: list[dict[str, Any]] = []
        if self._bm25 and self._corpus:
            tokens = _tokenize(query)
            scores = self._bm25.get_scores(tokens)
            top_idx = sorted(range(len(scores)),
                             key=lambda i: scores[i], reverse=True)[:fetch_k]
            for rank, idx in enumerate(top_idx):
                if scores[idx] > 0:
                    chunk = dict(self._corpus[idx])
                    chunk["_bm25_rank"] = rank
                    bm25_hits.append(chunk)

        # ---- RRF fusion -----------------------------------------------
        rrf_scores: dict[str, float]       = {}
        chunk_data: dict[str, dict]        = {}

        for rank, hit in enumerate(dense):
            cid = hit["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + VECTOR_WEIGHT * _rrf(rank)
            chunk_data[cid] = hit

        for hit in bm25_hits:
            cid  = hit["chunk_id"]
            rank = hit["_bm25_rank"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + BM25_WEIGHT * _rrf(rank)
            if cid not in chunk_data:
                chunk_data[cid] = hit

        # ---- Category boost -------------------------------------------
        if hint:
            for cid, chunk in chunk_data.items():
                if chunk.get("category") == hint:
                    rrf_scores[cid] *= CATEGORY_BOOST

        # ---- Sort and return top_k ------------------------------------
        ranked = sorted(rrf_scores, key=lambda c: rrf_scores[c], reverse=True)[:top_k]

        results: list[dict[str, Any]] = []
        for cid in ranked:
            c = dict(chunk_data[cid])
            c["score"] = round(rrf_scores[cid], 6)
            # Clean up internal keys
            c.pop("_bm25_rank", None)
            results.append({
                "chunk_id":   c.get("chunk_id",   cid),
                "text":       c.get("text",        ""),
                "source_url": c.get("source_url",  ""),
                "title":      c.get("title",        ""),
                "doc_type":   c.get("doc_type",    "webpage"),
                "category":   c.get("category",    "general"),
                "score":      c["score"],
            })

        return results

    # ------------------------------------------------------------------
    # Context formatter
    # ------------------------------------------------------------------

    def format_context(self, results: list[dict[str, Any]]) -> str:
        """
        Format retrieved chunks into a numbered context block for the LLM.

        Each chunk is capped at MAX_CONTEXT_WORDS_PER_CHUNK (200) words
        so the total context fits within Groq's free-tier TPM limit even
        with 4–5 chunks.
        """
        if not results:
            return "No relevant information found in the knowledge base."

        parts: list[str] = []
        for i, r in enumerate(results, start=1):
            source = r.get("title") or r.get("source_url") or "KITCOEK"
            words  = r["text"].split()
            text   = (" ".join(words[:MAX_CONTEXT_WORDS_PER_CHUNK])
                      + (" ..." if len(words) > MAX_CONTEXT_WORDS_PER_CHUNK else ""))
            parts.append(f"[{i}] {source}\n{text}")

        return "\n\n".join(parts)
