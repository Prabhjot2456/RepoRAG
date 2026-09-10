"""
File parser — reads files and detects language/encoding.
Returns structured ParsedFile objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chardet

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Extension → Language mapping ───────────────────────────────────────────────
EXT_TO_LANGUAGE: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "c", ".h": "c",
    ".hpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala",
    ".cs": "csharp",
    ".r": "r", ".R": "r",
    ".lua": "lua",
    ".ex": "elixir", ".exs": "elixir",
    ".erl": "erlang", ".hrl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure", ".cljs": "clojure",
    ".vue": "vue",
    ".svelte": "svelte",
    ".dart": "dart",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass", ".less": "less",
    ".md": "markdown", ".mdx": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".json": "json", ".json5": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".ini": "ini", ".cfg": "ini",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "fish",
    ".bat": "batch", ".cmd": "batch",
    ".ps1": "powershell",
    ".sql": "sql",
    ".graphql": "graphql", ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform", ".tfvars": "terraform",
    ".hcl": "hcl",
    ".nix": "nix",
    ".gradle": "groovy",
    ".lock": "text",
}

FILENAME_TO_LANGUAGE: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    "docker-compose.yml": "yaml",
    "docker-compose.yaml": "yaml",
    ".gitignore": "text",
    ".dockerignore": "text",
    "Procfile": "text",
    "requirements.txt": "text",
    "pyproject.toml": "toml",
    "Cargo.toml": "toml",
    "CMakeLists.txt": "cmake",
}


@dataclass
class ParsedFile:
    path: Path
    relative_path: str
    content: str
    language: Optional[str]
    size_bytes: int
    line_count: int
    encoding: str = "utf-8"


def detect_language(file_path: Path) -> Optional[str]:
    if file_path.name in FILENAME_TO_LANGUAGE:
        return FILENAME_TO_LANGUAGE[file_path.name]
    return EXT_TO_LANGUAGE.get(file_path.suffix.lower())


def parse_file(file_path: Path, repo_root: Path) -> Optional[ParsedFile]:
    """
    Read a file and return a ParsedFile.
    Returns None if the file cannot be read as text.
    """
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        logger.warning("file_read_error", path=str(file_path), error=str(exc))
        return None

    # Detect encoding
    detection = chardet.detect(raw)
    encoding = detection.get("encoding") or "utf-8"
    confidence = detection.get("confidence", 0)

    # Fallback for very low confidence
    if confidence < 0.5:
        encoding = "utf-8"

    try:
        content = raw.decode(encoding, errors="replace")
    except (UnicodeDecodeError, LookupError):
        try:
            content = raw.decode("latin-1", errors="replace")
            encoding = "latin-1"
        except Exception:
            logger.warning("decode_failed", path=str(file_path))
            return None

    # Guard against apparent binary content (too many replacement chars)
    if content.count("\ufffd") / max(len(content), 1) > 0.05:
        logger.debug("binary_content_skipped", path=str(file_path))
        return None

    try:
        relative_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        relative_path = str(file_path).replace("\\", "/")

    return ParsedFile(
        path=file_path,
        relative_path=relative_path,
        content=content,
        language=detect_language(file_path),
        size_bytes=len(raw),
        line_count=content.count("\n") + 1,
        encoding=encoding,
    )
