"""
File filter — determines which files should be indexed.

Ignores:
  - Binary/compiled files
  - Generated files (node_modules, dist, __pycache__, etc.)
  - Files exceeding size limits
  - Known secrets files (.env)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Set

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Directories to ignore ──────────────────────────────────────────────────────
IGNORED_DIRS: Set[str] = {
    ".git",
    "node_modules",
    ".npm",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    "out",
    "output",
    "coverage",
    ".nyc_output",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "vendor",
    "bower_components",
    ".idea",
    ".vscode",
    ".eggs",
    "*.egg-info",
    "site-packages",
    "Pods",
    "DerivedData",
    "__MACOSX",
    ".DS_Store",
    "tmp",
    "temp",
    "logs",
    "log",
    ".cache",
    "cache",
}

# ── File extensions to include ─────────────────────────────────────────────────
ALLOWED_EXTENSIONS: Set[str] = {
    # Source code
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".java",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".swift",
    ".kt", ".kts",
    ".scala",
    ".cs",
    ".r", ".R",
    ".lua",
    ".ex", ".exs",
    ".erl", ".hrl",
    ".hs",
    ".clj", ".cljs",
    ".vue",
    ".svelte",
    ".dart",
    # Markup / Config
    ".html", ".htm",
    ".css", ".scss", ".sass", ".less",
    ".md", ".mdx", ".rst", ".txt",
    ".json", ".json5",
    ".yaml", ".yml",
    ".toml",
    ".xml",
    ".ini", ".cfg",
    ".env.example", ".env.sample", ".env.template",
    ".properties",
    ".gradle",
    ".makefile",
    ".sh", ".bash", ".zsh", ".fish",
    ".bat", ".cmd", ".ps1",
    ".sql",
    ".graphql", ".gql",
    ".proto",
    ".tf", ".tfvars",
    ".hcl",
    ".nix",
    ".lock",
}

# ── Specific filenames to always include ──────────────────────────────────────
ALWAYS_INCLUDE_FILENAMES: Set[str] = {
    "README",
    "readme",
    "Makefile",
    "makefile",
    "Dockerfile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".gitignore",
    ".dockerignore",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "CMakeLists.txt",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    ".env.example",
    ".env.sample",
    "Procfile",
    "Pipfile",
    "poetry.lock",
}

# ── File suffixes/patterns to ALWAYS ignore ───────────────────────────────────
IGNORED_SUFFIXES: Set[str] = {
    # Compiled
    ".pyc", ".pyo", ".class", ".jar", ".war", ".ear",
    ".o", ".obj", ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".out", ".bin",
    # Archives
    ".zip", ".tar", ".tar.gz", ".tgz", ".rar", ".7z", ".gz", ".bz2", ".xz",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".tif", ".tiff",
    # Audio/Video
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flv", ".wmv",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # DB / binary
    ".db", ".sqlite", ".sqlite3",
    ".pkl", ".pickle", ".npy", ".npz",
    # Docs (binary)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Lock files (verbose but not useful for RAG)
    # We allow package.json but skip lock files individually below
}

# ── Ignored exact filenames ────────────────────────────────────────────────────
IGNORED_FILENAMES: Set[str] = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".DS_Store",
    "Thumbs.db",
    ".gitkeep",
    ".keep",
}


def should_include_file(file_path: Path, repo_root: Path) -> tuple[bool, str]:
    """
    Determine whether a file should be indexed.

    Returns (include: bool, reason: str).
    """
    # Check file size
    try:
        size = file_path.stat().st_size
    except OSError:
        return False, "cannot_stat"

    if size == 0:
        return False, "empty_file"

    if size > settings.max_file_size_bytes:
        return False, f"too_large ({size // 1024}KB > {settings.max_file_size_mb}MB)"

    # Check ignored filenames
    if file_path.name in IGNORED_FILENAMES:
        return False, "ignored_filename"

    # Check if the file is in an ignored directory
    try:
        rel = file_path.relative_to(repo_root)
        for part in rel.parts[:-1]:  # All directory parts
            if part in IGNORED_DIRS or part.endswith((".egg-info",)):
                return False, f"ignored_dir ({part})"
    except ValueError:
        pass

    # Check ignored suffixes
    suffix = file_path.suffix.lower()
    if suffix in IGNORED_SUFFIXES:
        return False, f"ignored_extension ({suffix})"

    # Check if filename is explicitly included
    if file_path.name in ALWAYS_INCLUDE_FILENAMES or file_path.stem in ALWAYS_INCLUDE_FILENAMES:
        return True, "always_include"

    # Check allowed extension
    if suffix in ALLOWED_EXTENSIONS:
        return True, "allowed_extension"

    # No extension — include small text files (Makefiles, etc.)
    if not suffix and size < 50_000:
        return True, "no_extension_small"

    return False, f"unknown_extension ({suffix})"


def scan_and_filter(
    repo_root: Path,
    max_files: int = settings.max_files_per_repo,
) -> tuple[List[Path], List[tuple[Path, str]]]:
    """
    Walk the repository and return (included_files, skipped_files_with_reason).
    """
    included: List[Path] = []
    skipped: List[tuple[Path, str]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        current_dir = Path(dirpath)

        # Prune ignored directories in-place so os.walk won't recurse
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS and not d.endswith((".egg-info",))
        ]

        for filename in filenames:
            if len(included) >= max_files:
                skipped.append((current_dir / filename, "max_files_reached"))
                continue

            file_path = current_dir / filename
            include, reason = should_include_file(file_path, repo_root)
            if include:
                included.append(file_path)
            else:
                skipped.append((file_path, reason))

    logger.info(
        "file_scan_complete",
        included=len(included),
        skipped=len(skipped),
    )
    return included, skipped
