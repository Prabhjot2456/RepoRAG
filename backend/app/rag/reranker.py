"""
Optional cross-encoder reranker.
Downloads cross-encoder/ms-marco-MiniLM-L-6-v2 from HuggingFace on first use.
Can be disabled via ENABLE_RERANKER=false in .env.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_reranker = None
_reranker_loaded = False


def _get_reranker():
    global _reranker, _reranker_loaded
    if not _reranker_loaded:
        _reranker_loaded = True
        if settings.enable_reranker:
            try:
                from sentence_transformers import CrossEncoder
                logger.info("loading_reranker", model=settings.reranker_model)
                _reranker = CrossEncoder(settings.reranker_model, max_length=512)
                logger.info("reranker_loaded")
            except Exception as exc:
                logger.warning("reranker_load_failed", error=str(exc))
                _reranker = None
    return _reranker


def rerank(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Rerank retrieved chunks using a cross-encoder.
    Falls back to original order if reranker is disabled or unavailable.
    """
    if not settings.enable_reranker:
        return chunks[:top_k] if top_k else chunks

    reranker = _get_reranker()
    if reranker is None:
        logger.debug("reranker_unavailable_using_original_order")
        return chunks[:top_k] if top_k else chunks

    if not chunks:
        return chunks

    try:
        pairs = [(query, c["content"][:500]) for c in chunks]
        scores = reranker.predict(pairs)

        scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        reranked = [item[1] for item in scored]

        if top_k:
            reranked = reranked[:top_k]

        logger.info("reranking_complete", input=len(chunks), output=len(reranked))
        return reranked

    except Exception as exc:
        logger.warning("reranking_failed", error=str(exc))
        return chunks[:top_k] if top_k else chunks
