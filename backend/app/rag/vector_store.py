"""
Pure-Python vector store using numpy for cosine similarity.
No C++ compilation required — works on all platforms.

Architecture:
  - Each repository gets its own persisted store (JSON + numpy .npz)
  - Supports add, query, delete
  - Falls back gracefully if numpy not available
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import settings
from app.ingestion.chunker import Chunk
from app.rag.embeddings import embed_texts
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Storage ──────────────────────────────────────────────────────────────────

def _store_dir(repository_id: str) -> Path:
    d = settings.chroma_persist_dir / repository_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(repository_id: str) -> Path:
    return _store_dir(repository_id) / "metadata.json"


def _vec_path(repository_id: str) -> Path:
    return _store_dir(repository_id) / "vectors.npz"


def _load_store(repository_id: str) -> tuple[List[Dict], Optional[np.ndarray]]:
    """Load metadata list and vectors array. Returns ([], None) if empty."""
    mp = _meta_path(repository_id)
    vp = _vec_path(repository_id)

    metadata: List[Dict] = []
    vectors: Optional[np.ndarray] = None

    if mp.exists():
        try:
            metadata = json.loads(mp.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("metadata_load_error", repo=repository_id, error=str(exc))

    if vp.exists() and metadata:
        try:
            data = np.load(str(vp))
            vectors = data["vectors"]
        except Exception as exc:
            logger.warning("vectors_load_error", repo=repository_id, error=str(exc))

    return metadata, vectors


def _save_store(
    repository_id: str,
    metadata: List[Dict],
    vectors: np.ndarray,
) -> None:
    mp = _meta_path(repository_id)
    vp = _vec_path(repository_id)
    mp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    np.savez_compressed(str(vp), vectors=vectors)


# ── Public API ────────────────────────────────────────────────────────────────

def collection_exists(repository_id: str) -> bool:
    return _meta_path(repository_id).exists()


def get_collection_count(repository_id: str) -> int:
    mp = _meta_path(repository_id)
    if not mp.exists():
        return 0
    try:
        return len(json.loads(mp.read_text()))
    except Exception:
        return 0


def delete_collection(repository_id: str) -> None:
    import shutil
    d = _store_dir(repository_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    logger.info("collection_deleted", repo=repository_id)


def index_chunks(repository_id: str, chunks: List[Chunk], batch_size: int = 64) -> int:
    """Embed and index all chunks. Returns number of indexed chunks."""
    if not chunks:
        return 0

    all_metadata: List[Dict] = []
    all_vectors: List[List[float]] = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c.content for c in batch]
        embeddings = embed_texts(texts)

        for chunk, emb in zip(batch, embeddings):
            # Sanitize metadata
            clean_meta: Dict[str, Any] = {"id": str(uuid.uuid4())}
            for k, v in chunk.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                elif v is None:
                    clean_meta[k] = ""
                else:
                    clean_meta[k] = str(v)
            clean_meta["_content"] = chunk.content
            all_metadata.append(clean_meta)
            all_vectors.append(emb)

        logger.debug("indexed_batch", repo=repository_id, batch=i // batch_size)

    vectors_arr = np.array(all_vectors, dtype=np.float32)
    _save_store(repository_id, all_metadata, vectors_arr)

    logger.info("indexing_complete", repo=repository_id, total=len(all_metadata))
    return len(all_metadata)


def query_collection(
    repository_id: str,
    query_embedding: List[float],
    n_results: int = 10,
    where: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Query by cosine similarity.
    Returns list of dicts: {content, metadata, score}.
    """
    metadata, vectors = _load_store(repository_id)
    if not metadata or vectors is None or len(vectors) == 0:
        return []

    q = np.array(query_embedding, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm > 0:
        q = q / q_norm

    # Compute cosine similarity (vectors are already normalized at index time)
    v_norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    v_norms = np.where(v_norms == 0, 1, v_norms)
    normed = vectors / v_norms
    scores = normed @ q  # shape: (N,)

    # Apply metadata filter if provided
    indices = list(range(len(metadata)))
    if where:
        filtered = []
        for idx in indices:
            m = metadata[idx]
            if all(m.get(k) == v for k, v in where.items()):
                filtered.append(idx)
        indices = filtered

    if not indices:
        return []

    # Sort by score
    indices.sort(key=lambda i: scores[i], reverse=True)
    top = indices[:n_results]

    results = []
    for i in top:
        m = dict(metadata[i])
        content = m.pop("_content", "")
        m.pop("id", None)
        results.append({
            "content": content,
            "metadata": m,
            "score": float(scores[i]),
        })

    return results
