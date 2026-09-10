"""Chat service — thin wrapper that delegates to the RAG chain."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models.schemas import ChatResponse
from app.rag.chain import run_rag_chain
from app.repository.metadata import RepositoryMetadata
from app.services.ingestion_service import get_metadata_dir
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def ask_question(
    repository_id: str,
    question: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    conversation_id: Optional[str] = None,
) -> ChatResponse:
    """Run the full RAG pipeline for a question about a repository."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise ValueError(f"Repository '{repository_id}' not found.")

    return await run_rag_chain(
        repository_id=repository_id,
        query=question,
        repo_url=meta.url,
        owner=meta.owner,
        repo_name=meta.name,
        default_branch=meta.default_branch,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
    )
