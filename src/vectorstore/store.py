"""
Vector store — KITCOEK RAG Agent

Wraps ChromaDB + sentence-transformers (all-MiniLM-L6-v2, runs locally).

Key improvements over v1:
- MMR-style diversity: after cosine search, re-rank to avoid returning
  5 chunks from the same document (redundant content)
- Metadata stored as strings (ChromaDB requirement)
- Explicit cosine space on collection
- search() returns normalized 0-1 scores
"""

import os
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import numpy as np

DEFAULT_CHROMA_PATH  = os.getenv("CHROMA_DB_PATH",        "data/chroma_db")
DEFAULT_COLLECTION   = os.getenv("CHROMA_COLLECTION_NAME", "kitcoek")

# BGE models need a query prefix for retrieval tasks.
# The model is state-of-the-art for RAG — 768-dim, much better semantic understanding
# than MiniLM-L6 (384-dim). Understands paraphrases, synonyms, intent correctly.
EMBEDDING_MODEL      = "BAAI/bge-base-en-v1.5"
BGE_QUERY_PREFIX     = "Represent this sentence for searching relevant passages: "

BATCH_SIZE           = 32   # smaller batch — BGE is larger model
MMR_LAMBDA           = 0.7  # 1.0 = pure relevance, 0.0 = pure diversity


def _mmr(
    query_emb: list[float],
    candidate_embs: list[list[float]],
    candidate_docs: list[dict[str, Any]],
    top_k: int,
    lambda_: float = MMR_LAMBDA,
) -> list[dict[str, Any]]:
    """
    Maximal Marginal Relevance re-ranking.

    Selects top_k documents that are both relevant to the query AND
    diverse from each other — avoids returning many near-duplicate chunks.
    """
    if not candidate_docs:
        return []

    q  = np.array(query_emb, dtype=np.float32)
    C  = np.array(candidate_embs, dtype=np.float32)   # (n, dim)

    # Cosine similarities between query and each candidate
    q_norm  = q  / (np.linalg.norm(q)  + 1e-10)
    C_norms = C  / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-10)
    rel_scores = C_norms @ q_norm                     # (n,)

    selected_idx: list[int] = []
    remaining    = list(range(len(candidate_docs)))

    while len(selected_idx) < top_k and remaining:
        if not selected_idx:
            # First pick: highest relevance
            best = max(remaining, key=lambda i: rel_scores[i])
        else:
            # MMR score = λ·relevance − (1-λ)·max_similarity_to_selected
            sel_embs = C_norms[selected_idx]          # (k, dim)
            scores = []
            for i in remaining:
                sim_to_sel = float(np.max(C_norms[i] @ sel_embs.T))
                mmr_score  = lambda_ * rel_scores[i] - (1 - lambda_) * sim_to_sel
                scores.append((i, mmr_score))
            best = max(scores, key=lambda x: x[1])[0]

        selected_idx.append(best)
        remaining.remove(best)

    return [candidate_docs[i] for i in selected_idx]


class VectorStore:
    """
    Persistent ChromaDB vector store with MMR diversity re-ranking.

    Usage
    -----
    vs = VectorStore()
    vs.build(chunks)                    # one-time ingestion
    results = vs.search("fee structure", top_k=5)
    """

    def __init__(
        self,
        chroma_path: str = DEFAULT_CHROMA_PATH,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        self.chroma_path     = chroma_path
        self.collection_name = collection_name

        print(f"[vectorstore] Loading embedding model: {EMBEDDING_MODEL}")
        self._embedder = SentenceTransformer(EMBEDDING_MODEL)

        os.makedirs(chroma_path, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=chroma_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def build(self, chunks: list[dict[str, Any]], reset: bool = False) -> None:
        """Embed all chunks and upsert into ChromaDB."""
        if reset:
            print(f"[vectorstore] Resetting collection '{self.collection_name}'")
            self._client.delete_collection(self.collection_name)
            self._col = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

        total = len(chunks)
        print(f"[vectorstore] Embedding {total} chunks ...")

        for start in range(0, total, BATCH_SIZE):
            batch = chunks[start: start + BATCH_SIZE]
            texts      = [c["text"] for c in batch]
            ids        = [c["chunk_id"] for c in batch]
            # All metadata values must be str/int/float — no None, no lists
            metadatas  = [
                {
                    "source_url":   str(c.get("source_url",   "")),
                    "title":        str(c.get("title",         "")),
                    "doc_type":     str(c.get("doc_type",      "webpage")),
                    "category":     str(c.get("category",      "general")),
                    "chunk_index":  int(c.get("chunk_index",   0)),
                    "total_chunks": int(c.get("total_chunks",  1)),
                }
                for c in batch
            ]
            embeddings = self._embedder.encode(
                texts, show_progress_bar=False, batch_size=32
            ).tolist()

            self._col.upsert(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            print(f"[vectorstore]   {min(start + BATCH_SIZE, total)}/{total}")

        print(f"[vectorstore] Build complete — {self._col.count()} chunks stored.")

    # ------------------------------------------------------------------
    # Semantic search with MMR diversity
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        fetch_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Embed query → cosine search → MMR diversity re-ranking → top_k results.

        BGE models perform best when queries are prefixed with a retrieval instruction.
        Documents are stored as-is (no prefix) — only the query gets the prefix.
        """
        if fetch_k is None:
            fetch_k = min(top_k * 4, self._col.count())
        fetch_k = max(fetch_k, top_k)

        # BGE query prefix — critical for retrieval quality
        prefixed_query = BGE_QUERY_PREFIX + query
        query_emb = self._embedder.encode([prefixed_query])[0]

        results = self._col.query(
            query_embeddings=[query_emb.tolist()],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances", "embeddings"],
        )

        if not results["ids"] or not results["ids"][0]:
            return []

        candidates: list[dict[str, Any]] = []
        cand_embs:  list[list[float]]    = []

        for i, cid in enumerate(results["ids"][0]):
            dist = results["distances"][0][i]
            meta = results["metadatas"][0][i]
            text = results["documents"][0][i]
            emb  = results["embeddings"][0][i]

            candidates.append({
                "chunk_id":   cid,
                "text":       text,
                "source_url": meta.get("source_url", ""),
                "title":      meta.get("title", ""),
                "doc_type":   meta.get("doc_type", "webpage"),
                "category":   meta.get("category", "general"),
                "score":      round(1.0 - dist, 4),
            })
            cand_embs.append(emb)

        # MMR re-rank for diversity
        diverse = _mmr(
            query_emb.tolist(), cand_embs, candidates,
            top_k=top_k, lambda_=MMR_LAMBDA,
        )
        return diverse

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self._col.count()

    def get_all_chunks(self) -> list[dict[str, Any]]:
        """Return all stored chunks (text + metadata) — used by BM25 index."""
        result = self._col.get(include=["documents", "metadatas"])
        out = []
        for i, cid in enumerate(result["ids"]):
            meta = result["metadatas"][i]
            out.append({
                "chunk_id":   cid,
                "text":       result["documents"][i],
                "source_url": meta.get("source_url", ""),
                "title":      meta.get("title", ""),
                "doc_type":   meta.get("doc_type", "webpage"),
                "category":   meta.get("category", "general"),
            })
        return out
