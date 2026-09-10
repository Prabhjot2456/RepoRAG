"""
Ingestion service — orchestrates the full repository ingestion pipeline.
Runs in a background asyncio task and emits progress events via a queue.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

from app.config import settings
from app.ingestion.chunker import chunk_repository
from app.ingestion.file_filter import scan_and_filter
from app.ingestion.github_loader import (
    GitHubLoaderError,
    cleanup_repository,
    clone_repository,
    fetch_repository_info,
    parse_github_url,
)
from app.ingestion.parser import parse_file
from app.models.schemas import IngestionStatus, ProgressEvent
from app.rag.embeddings import get_embedding_model
from app.rag.retriever import build_bm25_index
from app.rag.vector_store import delete_collection, index_chunks
from app.repository.analyzer import detect_technologies
from app.repository.metadata import RepositoryMetadata, RepoStats
from app.repository.structure import build_file_tree
from app.utils.cache import get_cached_sha, set_cached_sha
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-memory store: repository_id → asyncio.Queue[ProgressEvent]
_progress_queues: Dict[str, asyncio.Queue] = {}

# Metadata storage path
METADATA_DIR = Path("./data/metadata")


def get_repository_id(url: str) -> str:
    """Derive a stable repository ID from the GitHub URL."""
    url = url.strip().rstrip("/").lower()
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def get_metadata_dir() -> Path:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    return METADATA_DIR


def get_or_create_queue(repository_id: str) -> asyncio.Queue:
    if repository_id not in _progress_queues:
        _progress_queues[repository_id] = asyncio.Queue()
    return _progress_queues[repository_id]


async def stream_progress(repository_id: str) -> AsyncGenerator[ProgressEvent, None]:
    """Yield progress events for a repository ingestion."""
    queue = get_or_create_queue(repository_id)
    while True:
        try:
            event: ProgressEvent = await asyncio.wait_for(queue.get(), timeout=60.0)
            yield event
            if event.status in (IngestionStatus.READY, IngestionStatus.FAILED, IngestionStatus.CACHED):
                break
        except asyncio.TimeoutError:
            break


async def _emit(queue: asyncio.Queue, status: IngestionStatus, message: str, progress: int, detail: Optional[str] = None) -> None:
    await queue.put(ProgressEvent(status=status, message=message, progress=progress, detail=detail))


_background_tasks = set()

async def run_ingestion(url: str, force_reindex: bool = False) -> str:
    """
    Start ingestion for a GitHub repository.
    Returns the repository_id. The actual work runs in a background task.
    """
    repository_id = get_repository_id(url)
    queue = get_or_create_queue(repository_id)

    # Check if already running
    metadata = RepositoryMetadata.load(get_metadata_dir(), repository_id)
    if metadata and metadata.status == IngestionStatus.READY and not force_reindex:
        # Check if there's a new commit
        try:
            info = await fetch_repository_info(url)
            cached_sha = get_cached_sha(url)
            if cached_sha and info.latest_commit_sha == cached_sha:
                await _emit(queue, IngestionStatus.CACHED, "Repository already indexed and up-to-date.", 100)
                return repository_id
        except Exception:
            pass

    # Launch background task
    task = asyncio.create_task(_ingest_repository(url, repository_id, queue, force_reindex))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return repository_id


async def _ingest_repository(
    url: str,
    repository_id: str,
    queue: asyncio.Queue,
    force_reindex: bool,
) -> None:
    """Background ingestion task."""
    repo_dir: Optional[Path] = None
    metadata = RepositoryMetadata(
        repository_id=repository_id,
        name="",
        owner="",
        url=url,
        status=IngestionStatus.PENDING,
    )
    metadata.save(get_metadata_dir())

    try:
        # ── Step 1: Validate & fetch metadata ─────────────────────────────────
        await _emit(queue, IngestionStatus.FETCHING, "Validating repository URL...", 5)

        try:
            info = await fetch_repository_info(url)
        except GitHubLoaderError as exc:
            await _emit(queue, IngestionStatus.FAILED, str(exc), 0)
            metadata.status = IngestionStatus.FAILED
            metadata.error_message = str(exc)
            metadata.save(get_metadata_dir())
            return

        owner, repo_name = parse_github_url(url)
        metadata.name = info.name
        metadata.owner = info.owner
        metadata.description = info.description
        metadata.default_branch = info.default_branch
        metadata.primary_language = info.primary_language
        metadata.stars = info.stars
        metadata.forks = info.forks
        metadata.license = info.license_name
        metadata.latest_commit_sha = info.latest_commit_sha

        await _emit(queue, IngestionStatus.FETCHING, f"Repository found: {info.owner}/{info.name}", 10)

        # ── Step 2: Clone ─────────────────────────────────────────────────────
        await _emit(queue, IngestionStatus.FETCHING, "Cloning repository (shallow)...", 15)

        settings.repos_dir.mkdir(parents=True, exist_ok=True)
        repo_dir = settings.repos_dir / repository_id

        if repo_dir.exists():
            cleanup_repository(repo_dir)

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, clone_repository, info.clone_url, repo_dir)
        except GitHubLoaderError as exc:
            await _emit(queue, IngestionStatus.FAILED, str(exc), 0)
            metadata.status = IngestionStatus.FAILED
            metadata.error_message = str(exc)
            metadata.save(get_metadata_dir())
            return

        await _emit(queue, IngestionStatus.SCANNING, "Repository cloned. Scanning files...", 25)

        # ── Step 3: Scan & filter ─────────────────────────────────────────────
        included_files, skipped_files = scan_and_filter(repo_dir)

        await _emit(
            queue,
            IngestionStatus.SCANNING,
            f"{len(included_files)} files selected ({len(skipped_files)} skipped)",
            35,
        )

        metadata.stats.total_files = len(included_files) + len(skipped_files)
        metadata.stats.skipped_files = len(skipped_files)
        metadata.stats.indexed_files = len(included_files)

        # Build file tree and save it
        file_tree = build_file_tree(included_files, repo_dir)
        # Save file tree as JSON
        import json
        tree_path = get_metadata_dir() / f"{repository_id}_tree.json"
        tree_path.write_text(json.dumps([n.model_dump() for n in file_tree], indent=2))

        # ── Step 4: Parse files ───────────────────────────────────────────────
        await _emit(queue, IngestionStatus.PARSING, "Parsing file contents...", 42)

        parsed_files = []
        file_contents: Dict[str, str] = {}
        total_lines = 0

        for fp in included_files:
            pf = parse_file(fp, repo_dir)
            if pf:
                parsed_files.append(pf)
                total_lines += pf.line_count
                # Store content sample for tech detection (first 2KB)
                file_contents[pf.relative_path] = pf.content[:2048]

        metadata.stats.total_lines = total_lines

        await _emit(queue, IngestionStatus.PARSING, f"Parsed {len(parsed_files)} files ({total_lines:,} lines)", 50)

        # ── Step 5: Detect technologies ───────────────────────────────────────
        tech_infos = detect_technologies(
            [pf.relative_path for pf in parsed_files],
            file_contents,
        )
        metadata.technologies = tech_infos

        # ── Step 6: Chunk ─────────────────────────────────────────────────────
        await _emit(queue, IngestionStatus.CHUNKING, "Creating semantic chunks...", 55)

        chunks = chunk_repository(parsed_files)
        metadata.stats.total_chunks = len(chunks)

        await _emit(queue, IngestionStatus.CHUNKING, f"Created {len(chunks):,} chunks", 62)

        # ── Step 7: Embed & index ─────────────────────────────────────────────
        await _emit(queue, IngestionStatus.EMBEDDING, "Generating embeddings (this may take a moment)...", 65)

        # Pre-load model
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, get_embedding_model)

        if force_reindex:
            delete_collection(repository_id)

        # Index in executor to avoid blocking the event loop
        total_indexed = await loop.run_in_executor(
            None, index_chunks, repository_id, chunks
        )
        metadata.stats.total_embeddings = total_indexed

        await _emit(queue, IngestionStatus.INDEXING, f"Indexed {total_indexed:,} embeddings into vector store", 80)

        # ── Step 8: Build BM25 index ──────────────────────────────────────────
        bm25_data = [{"content": c.content, "metadata": c.metadata} for c in chunks]
        await loop.run_in_executor(None, build_bm25_index, repository_id, bm25_data)

        await _emit(queue, IngestionStatus.INDEXING, "BM25 keyword index built", 85)

        # ── Step 9: Update cache ──────────────────────────────────────────────
        if info.latest_commit_sha:
            set_cached_sha(url, info.latest_commit_sha)

        # ── Step 10: Finalize ─────────────────────────────────────────────────
        await _emit(queue, IngestionStatus.SUMMARIZING, "Finalizing repository...", 92)

        metadata.status = IngestionStatus.READY
        metadata.updated_at = datetime.utcnow()
        metadata.save(get_metadata_dir())

        await _emit(queue, IngestionStatus.READY, "Repository ready! You can now ask questions.", 100)
        logger.info("ingestion_complete", repo=repository_id, chunks=total_indexed)

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("ingestion_failed", repo=repository_id, error=str(exc), traceback=tb)
        await _emit(queue, IngestionStatus.FAILED, f"Ingestion failed: {exc}", 0)
        metadata.status = IngestionStatus.FAILED
        metadata.error_message = str(exc)
        metadata.save(get_metadata_dir())

    finally:
        # Clean up cloned repository to save disk space
        if repo_dir and repo_dir.exists():
            cleanup_repository(repo_dir)
