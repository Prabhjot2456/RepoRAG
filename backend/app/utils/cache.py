"""Repository cache — avoids re-indexing unchanged repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_FILE = Path("./data/repo_cache.json")


def _load_cache() -> Dict[str, str]:
    """Load the URL → commit_sha cache from disk."""
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict[str, str]) -> None:
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(cache, indent=2))


def get_cached_sha(repo_url: str) -> Optional[str]:
    """Return the cached commit SHA for the URL, or None if not cached."""
    cache = _load_cache()
    return cache.get(repo_url)


def set_cached_sha(repo_url: str, sha: str) -> None:
    cache = _load_cache()
    cache[repo_url] = sha
    _save_cache(cache)
    logger.info("cache_updated", repo_url=repo_url, sha=sha[:8])


def invalidate_cache(repo_url: str) -> None:
    cache = _load_cache()
    if repo_url in cache:
        del cache[repo_url]
        _save_cache(cache)
        logger.info("cache_invalidated", repo_url=repo_url)
