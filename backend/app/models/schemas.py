"""Pydantic schemas for all API request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


# ── Enums ──────────────────────────────────────────────────────────────────────

class IngestionStatus(str, Enum):
    PENDING = "pending"
    FETCHING = "fetching"
    SCANNING = "scanning"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    SUMMARIZING = "summarizing"
    READY = "ready"
    FAILED = "failed"
    CACHED = "cached"


class QueryType(str, Enum):
    FILE_QUERY = "FILE_QUERY"
    CODE_QUERY = "CODE_QUERY"
    FUNCTION_QUERY = "FUNCTION_QUERY"
    CLASS_QUERY = "CLASS_QUERY"
    ARCHITECTURE_QUERY = "ARCHITECTURE_QUERY"
    SETUP_QUERY = "SETUP_QUERY"
    DEPENDENCY_QUERY = "DEPENDENCY_QUERY"
    SECURITY_QUERY = "SECURITY_QUERY"
    GENERAL_REPOSITORY_QUERY = "GENERAL_REPOSITORY_QUERY"
    COMPARISON_QUERY = "COMPARISON_QUERY"
    DEBUGGING_QUERY = "DEBUGGING_QUERY"


# ── Repository Schemas ─────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="GitHub repository URL")
    force_reindex: bool = Field(default=False, description="Force re-indexing even if cached")


class AnalyzeResponse(BaseModel):
    repository_id: str
    status: IngestionStatus
    message: str


class ProgressEvent(BaseModel):
    status: IngestionStatus
    message: str
    progress: int = Field(default=0, ge=0, le=100)
    detail: Optional[str] = None


class TechnologyInfo(BaseModel):
    name: str
    confidence: str  # "detected" | "inferred"
    evidence: List[str] = Field(default_factory=list)


class RepositoryStats(BaseModel):
    total_files: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    total_lines: int = 0
    total_chunks: int = 0
    total_embeddings: int = 0


class RepositoryMetadataSchema(BaseModel):
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
    technologies: List[TechnologyInfo] = Field(default_factory=list)
    stats: RepositoryStats = Field(default_factory=RepositoryStats)
    status: IngestionStatus = IngestionStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    architecture_summary: Optional[str] = None


class FileNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    size: Optional[int] = None
    language: Optional[str] = None
    children: Optional[List["FileNode"]] = None


FileNode.model_rebuild()


class FileContentResponse(BaseModel):
    path: str
    content: str
    language: Optional[str] = None
    size: int
    lines: int


# ── Chat Schemas ───────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    conversation_history: List[Message] = Field(default_factory=list)


class SourceChunk(BaseModel):
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    chunk_type: Optional[str] = None
    symbol: Optional[str] = None
    language: Optional[str] = None
    content_preview: Optional[str] = None
    github_url: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceChunk] = Field(default_factory=list)
    query_type: Optional[QueryType] = None
    conversation_id: str
    repository_id: str


# ── Repository List ────────────────────────────────────────────────────────────

class RepositoryListItem(BaseModel):
    repository_id: str
    name: str
    owner: str
    url: str
    status: IngestionStatus
    indexed_files: int
    total_chunks: int
    created_at: datetime
