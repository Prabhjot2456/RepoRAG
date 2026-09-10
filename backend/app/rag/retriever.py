"""
Hybrid retriever — combines vector similarity search with BM25 keyword search.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from rank_bm25 import BM25Okapi

from app.config import settings
from app.rag.embeddings import embed_query
from app.rag.vector_store import query_collection
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-memory BM25 index store: repository_id → BM25Okapi
_bm25_indexes: Dict[str, Dict] = {}


def build_bm25_index(repository_id: str, chunks: List[Dict[str, Any]]) -> None:
    """Build a BM25 index from a list of chunk dicts (with 'content' and 'metadata' keys)."""
    tokenized = [_tokenize(c["content"]) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    _bm25_indexes[repository_id] = {
        "bm25": bm25,
        "chunks": chunks,
    }
    logger.info("bm25_index_built", repo=repository_id, docs=len(chunks))


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    import re
    text = text.lower()
    tokens = re.findall(r"\w+", text)
    return tokens


def retrieve(
    repository_id: str,
    query: str,
    k: int = settings.retrieval_k,
    fetch_k: int = settings.retrieval_fetch_k,
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Hybrid retrieval: combine vector search scores with BM25 scores.
    Returns top-k chunks sorted by combined score.
    """
    query_emb = embed_query(query)

    # ── Vector search ─────────────────────────────────────────────────────────
    vector_results = query_collection(repository_id, query_emb, n_results=fetch_k)
    vector_scores: Dict[str, float] = {}
    vector_chunks: Dict[str, Dict] = {}

    for r in vector_results:
        key = r["content"][:100]  # Use content prefix as dedup key
        vector_scores[key] = r["score"]
        vector_chunks[key] = r

    # ── BM25 search ───────────────────────────────────────────────────────────
    bm25_scores: Dict[str, float] = {}
    idx_data = _bm25_indexes.get(repository_id)
    if idx_data:
        bm25: BM25Okapi = idx_data["bm25"]
        bm25_chunks: List[Dict] = idx_data["chunks"]
        tokenized_query = _tokenize(query)

        raw_scores = bm25.get_scores(tokenized_query)
        max_score = max(raw_scores) if raw_scores.max() > 0 else 1.0

        # Normalize and pick top candidates
        top_indices = sorted(
            range(len(raw_scores)),
            key=lambda i: raw_scores[i],
            reverse=True,
        )[:fetch_k]

        for idx in top_indices:
            score = float(raw_scores[idx]) / max_score
            if score > 0.01:
                chunk = bm25_chunks[idx]
                key = chunk["content"][:100]
                bm25_scores[key] = score
                if key not in vector_chunks:
                    vector_chunks[key] = {
                        "content": chunk["content"],
                        "metadata": chunk["metadata"],
                        "score": 0.0,
                    }

    # ── Combine scores ────────────────────────────────────────────────────────
    all_keys = set(vector_scores.keys()) | set(bm25_scores.keys())
    scored: List[tuple] = []
    for key in all_keys:
        v_score = vector_scores.get(key, 0.0)
        b_score = bm25_scores.get(key, 0.0)
        combined = vector_weight * v_score + bm25_weight * b_score
        scored.append((combined, vector_chunks[key]))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_k = [item[1] for item in scored[:k]]

    logger.info(
        "retrieval_complete",
        repo=repository_id,
        query_len=len(query),
        vector_results=len(vector_results),
        bm25_results=len(bm25_scores),
        returned=len(top_k),
    )
    return top_k
