"""
Repository API endpoints:
  POST /api/repositories/analyze
  GET  /api/repositories/{repository_id}/status   (SSE)
  GET  /api/repositories/{repository_id}
  GET  /api/repositories
  DELETE /api/repositories/{repository_id}
"""

from __future__ import annotations

import asyncio
import json
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    IngestionStatus,
    RepositoryListItem,
    RepositoryMetadataSchema,
    TechnologyInfo,
)
from app.rag.vector_store import delete_collection
from app.repository.metadata import RepositoryMetadata
from app.services.ingestion_service import (
    get_metadata_dir,
    get_or_create_queue,
    get_repository_id,
    run_ingestion,
    stream_progress,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_repository(request: AnalyzeRequest):
    """Start or resume ingestion of a GitHub repository."""
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Repository URL is required.")

    repository_id = get_repository_id(url)
    logger.info("analyze_requested", url=url, repo_id=repository_id)

    try:
        rid = await run_ingestion(url, force_reindex=request.force_reindex)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return AnalyzeResponse(
        repository_id=rid,
        status=IngestionStatus.PENDING,
        message="Ingestion started. Poll /status for progress.",
    )


@router.get("/{repository_id}/status")
async def repository_status(repository_id: str):
    """
    Server-Sent Events stream of ingestion progress.
    The client should open an EventSource to this endpoint.
    """
    async def event_generator():
        async for event in stream_progress(repository_id):
            data = json.dumps({
                "status": event.status,
                "message": event.message,
                "progress": event.progress,
                "detail": event.detail,
            })
            yield f"data: {data}\n\n"
            await asyncio.sleep(0)

        # Send a final "done" ping so clients know to close
        yield "data: {\"status\": \"stream_end\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{repository_id}", response_model=RepositoryMetadataSchema)
async def get_repository(repository_id: str):
    """Get repository metadata and analysis results."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    techs = [
        TechnologyInfo(name=t.name, confidence=t.confidence, evidence=t.evidence)
        for t in meta.technologies
    ]

    from app.models.schemas import RepositoryStats
    stats = RepositoryStats(
        total_files=meta.stats.total_files,
        indexed_files=meta.stats.indexed_files,
        skipped_files=meta.stats.skipped_files,
        total_lines=meta.stats.total_lines,
        total_chunks=meta.stats.total_chunks,
        total_embeddings=meta.stats.total_embeddings,
    )

    return RepositoryMetadataSchema(
        repository_id=meta.repository_id,
        name=meta.name,
        owner=meta.owner,
        description=meta.description,
        url=meta.url,
        default_branch=meta.default_branch,
        primary_language=meta.primary_language,
        stars=meta.stars,
        forks=meta.forks,
        license=meta.license,
        latest_commit_sha=meta.latest_commit_sha,
        technologies=techs,
        stats=stats,
        status=meta.status,
        created_at=meta.created_at,
        updated_at=meta.updated_at,
        error_message=meta.error_message,
        architecture_summary=meta.architecture_summary,
    )


@router.get("", response_model=List[RepositoryListItem])
async def list_repositories():
    """List all indexed repositories."""
    repos = RepositoryMetadata.list_all(get_metadata_dir())
    return [
        RepositoryListItem(
            repository_id=r.repository_id,
            name=r.name or "Unknown",
            owner=r.owner or "Unknown",
            url=r.url,
            status=r.status,
            indexed_files=r.stats.indexed_files,
            total_chunks=r.stats.total_chunks,
            created_at=r.created_at,
        )
        for r in repos
    ]


@router.delete("/{repository_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_repository(repository_id: str):
    """Delete a repository index."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    delete_collection(repository_id)
    meta.delete(get_metadata_dir())

    # Also delete tree file
    import os
    tree_path = get_metadata_dir() / f"{repository_id}_tree.json"
    if tree_path.exists():
        os.remove(tree_path)

    logger.info("repository_deleted", repo_id=repository_id)
