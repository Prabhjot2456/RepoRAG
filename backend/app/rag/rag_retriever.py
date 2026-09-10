"""
Unified retrieval function used by both chain.py and the API layer.
Wraps the hybrid retriever so chain.py doesn't import from retriever directly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.rag.retriever import retrieve


def retrieve_for_query(
    repository_id: str,
    query: str,
    k: int = 8,
    fetch_k: int = 20,
) -> List[Dict[str, Any]]:
    return retrieve(repository_id=repository_id, query=query, k=k, fetch_k=fetch_k)
