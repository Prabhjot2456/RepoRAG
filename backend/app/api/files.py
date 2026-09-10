"""
Files API endpoints:
  GET /api/repositories/{repository_id}/files
  GET /api/repositories/{repository_id}/files/{path:path}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException

from app.models.schemas import FileContentResponse, FileNode
from app.repository.metadata import RepositoryMetadata
from app.services.ingestion_service import get_metadata_dir, get_repository_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["files"])


def _load_tree(repository_id: str) -> List[FileNode]:
    tree_path = get_metadata_dir() / f"{repository_id}_tree.json"
    if not tree_path.exists():
        return []
    try:
        data = json.loads(tree_path.read_text())
        return [FileNode.model_validate(n) for n in data]
    except Exception as exc:
        logger.warning("tree_load_failed", error=str(exc))
        return []


@router.get("/{repository_id}/files", response_model=List[FileNode])
async def get_file_tree(repository_id: str):
    """Return the repository's file tree structure."""
    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    return _load_tree(repository_id)


@router.get("/{repository_id}/files/{file_path:path}", response_model=FileContentResponse)
async def get_file_content(repository_id: str, file_path: str):
    """
    Return a specific file's content from the indexed vector store.
    Files are reconstructed from indexed chunks.
    """
    from app.rag.vector_store import query_collection
    from app.rag.embeddings import embed_query

    meta = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    # Sanitize path — prevent traversal
    clean_path = file_path.replace("\\", "/").lstrip("/")
    if ".." in clean_path:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    # Query with file path filter
    try:
        results = query_collection(
            repository_id=repository_id,
            query_embedding=embed_query(f"file {clean_path}"),
            n_results=50,
            where={"file_path": clean_path},
        )
    except Exception:
        results = []

    if not results:
        # Fallback: search broadly and filter manually
        try:
            all_results = query_collection(
                repository_id=repository_id,
                query_embedding=embed_query(clean_path),
                n_results=30,
            )
            results = [r for r in all_results if r.get("metadata", {}).get("file_path") == clean_path]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Storage error: {exc}")

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"File '{clean_path}' not found in the indexed repository."
        )

    # Sort by start_line and reassemble content
    results.sort(key=lambda r: r.get("metadata", {}).get("start_line") or 0)

    # Deduplicate overlapping chunks
    seen_first_lines = set()
    content_parts = []
    for r in results:
        content = r.get("content", "")
        first_line = content.split("\n")[0] if content else ""
        if first_line not in seen_first_lines:
            seen_first_lines.add(first_line)
            content_parts.append(content)

    content = "\n".join(content_parts)
    language = results[0].get("metadata", {}).get("language") if results else None

    return FileContentResponse(
        path=clean_path,
        content=content,
        language=language,
        size=len(content.encode()),
        lines=content.count("\n") + 1,
    )
