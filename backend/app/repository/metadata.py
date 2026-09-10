"""
Repository metadata Pydantic models.
These are stored as JSON alongside the ChromaDB collection.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.schemas import IngestionStatus


class TechInfo(BaseModel):
    name: str
    confidence: str = "detected"
    evidence: List[str] = Field(default_factory=list)


class RepoStats(BaseModel):
    total_files: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    total_lines: int = 0
    total_chunks: int = 0
    total_embeddings: int = 0


class RepositoryMetadata(BaseModel):
    repository_id: str
    name: str
    owner: str
    description: Optional[str] = None
    url: str
    default_branch: str = "main"
    primary_language: Optional[str] = None
    stars: Optional[int] = None
    forks: Optional[int] = None
    license: Optional[str] = None
    latest_commit_sha: Optional[str] = None
    technologies: List[TechInfo] = Field(default_factory=list)
    stats: RepoStats = Field(default_factory=RepoStats)
    status: IngestionStatus = IngestionStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    architecture_summary: Optional[str] = None

    def save(self, metadata_dir: Path) -> None:
        metadata_dir.mkdir(parents=True, exist_ok=True)
        path = metadata_dir / f"{self.repository_id}.json"
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, metadata_dir: Path, repository_id: str) -> Optional["RepositoryMetadata"]:
        path = metadata_dir / f"{repository_id}.json"
        if not path.exists():
            return None
        try:
            return cls.model_validate_json(path.read_text())
        except Exception:
            return None

    @classmethod
    def list_all(cls, metadata_dir: Path) -> List["RepositoryMetadata"]:
        result = []
        if not metadata_dir.exists():
            return result
        for p in metadata_dir.glob("*.json"):
            try:
                result.append(cls.model_validate_json(p.read_text()))
            except Exception:
                pass
        result.sort(key=lambda r: r.created_at, reverse=True)
        return result

    def delete(self, metadata_dir: Path) -> None:
        path = metadata_dir / f"{self.repository_id}.json"
        if path.exists():
            path.unlink()
