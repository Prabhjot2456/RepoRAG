"""
Reranker disabled to save memory (removed sentence-transformers dependency).
Returns chunks in original order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def rerank(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Reranker disabled. Returns chunks in original order up to top_k.
    """
    return chunks[:top_k] if top_k else chunks
