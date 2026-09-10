"""
Application configuration — loaded from .env / environment variables.
Uses pydantic-settings for automatic validation and type coercion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GitHub ──────────────────────────────────────────────────────────────
    github_token: str = Field(default="", description="GitHub personal access token")

    # ── LLM ─────────────────────────────────────────────────────────────────
    llm_provider: str = Field(default="ollama", description="ollama | openai")
    llm_model: str = Field(default="qwen3:0.6b")
    ollama_base_url: str = Field(default="http://localhost:11434")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")

    # ── Embeddings ───────────────────────────────────────────────────────────
    embedding_model: str = Field(default="all-MiniLM-L6-v2")
    embedding_device: str = Field(default="cpu")

    # ── Vector DB ────────────────────────────────────────────────────────────
    vector_db: str = Field(default="chroma")
    chroma_persist_dir: Path = Field(default=Path("./data/chroma"))

    # ── Retrieval ────────────────────────────────────────────────────────────
    retrieval_k: int = Field(default=8)
    retrieval_fetch_k: int = Field(default=20)
    enable_reranker: bool = Field(default=True)
    reranker_model: str = Field(default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    reranker_top_k: int = Field(default=5)

    # ── Repository Limits ────────────────────────────────────────────────────
    max_repository_size_mb: int = Field(default=500)
    max_file_size_mb: int = Field(default=2)
    max_files_per_repo: int = Field(default=2000)

    # ── Data Storage ─────────────────────────────────────────────────────────
    repos_dir: Path = Field(default=Path("./data/repositories"))

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:5500", "http://localhost:5500"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: object) -> List[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [s.strip() for s in v.split(",")]
        return v  # type: ignore[return-value]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_repository_size_bytes(self) -> int:
        return self.max_repository_size_mb * 1024 * 1024


settings = Settings()
