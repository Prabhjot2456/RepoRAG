"""
Chat API endpoint:
  POST /api/repositories/{repository_id}/chat
  POST /api/repositories/{repository_id}/overview
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse, IngestionStatus
from app.rag.chain import generate_overview
from app.repository.metadata import RepositoryMetadata
from app.services.chat_service import ask_question
from app.services.ingestion_service import get_metadata_dir
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["chat"])


@router.post("/{repository_id}/chat", response_model=ChatResponse)
async def chat(repository_id: str, request: ChatRequest):
    """Ask a question about an indexed repository."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    if meta.status != IngestionStatus.READY:
        raise HTTPException(
            status_code=409,
            detail=f"Repository is not ready for queries (status: {meta.status}). "
                   "Wait for ingestion to complete.",
        )

    history = [{"role": m.role, "content": m.content} for m in request.conversation_history]

    try:
        response = await ask_question(
            repository_id=repository_id,
            question=request.question,
            conversation_history=history,
            conversation_id=request.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("chat_error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")

    return response


@router.post("/{repository_id}/overview")
async def get_overview(repository_id: str):
    """Generate a comprehensive project overview using RAG."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    if meta.status != IngestionStatus.READY:
        raise HTTPException(status_code=409, detail="Repository not ready.")

    overview = await generate_overview(
        repository_id=repository_id,
        repo_url=meta.url,
        owner=meta.owner,
        repo_name=meta.name,
        default_branch=meta.default_branch,
    )

    # Cache the overview
    meta.architecture_summary = overview
    meta.save(get_metadata_dir())

    return {"overview": overview}
