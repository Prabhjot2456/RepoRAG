"""
Code-aware chunker.

Strategies per language:
  - Python  : regex-based class/function extraction
  - JS/TS   : regex-based function/class/arrow extraction
  - Java/C# : regex-based class/method extraction
  - Markdown : section-based (by headings)
  - JSON/YAML/TOML : top-level key grouping
  - Generic  : sliding-window with line-boundary preservation
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ingestion.parser import ParsedFile
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default chunk parameters
DEFAULT_CHUNK_SIZE = 1500       # characters
DEFAULT_CHUNK_OVERLAP = 200     # characters


@dataclass
class Chunk:
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def char_count(self) -> int:
        return len(self.content)


# ── Python chunker ─────────────────────────────────────────────────────────────

_PY_DEF_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<type>class|def|async def)\s+(?P<name>\w+)",
    re.MULTILINE,
)

def _chunk_python(parsed: ParsedFile) -> List[Chunk]:
    lines = parsed.content.splitlines(keepends=True)
    chunks: List[Chunk] = []

    matches = list(_PY_DEF_RE.finditer(parsed.content))
    if not matches:
        return _chunk_generic(parsed)

    # Build sections: (start_line, end_line, type, name, indent)
    sections = []
    for i, m in enumerate(matches):
        start_line = parsed.content[:m.start()].count("\n")
        if i + 1 < len(matches):
            end_line = parsed.content[:matches[i + 1].start()].count("\n")
        else:
            end_line = len(lines)

        indent = len(m.group("indent"))
        # Only capture top-level or one-level-deep definitions
        if indent <= 4:
            sections.append((start_line, end_line, m.group("type"), m.group("name"), indent))

    # Header (imports, module docstring) — everything before the first section
    if sections:
        header_end = sections[0][0]
        if header_end > 0:
            header_content = "".join(lines[:header_end]).strip()
            if header_content:
                chunks.append(Chunk(
                    content=header_content,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": parsed.language,
                        "chunk_type": "imports",
                        "start_line": 1,
                        "end_line": header_end,
                    },
                ))

    for start, end, sym_type, sym_name, indent in sections:
        section_lines = lines[start:end]
        content = "".join(section_lines).strip()
        if not content:
            continue

        chunk_type = "class" if sym_type == "class" else "function"

        # If chunk is too long, split it further
        if len(content) > DEFAULT_CHUNK_SIZE * 2:
            sub_chunks = _split_long_chunk(content, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
            for j, sc in enumerate(sub_chunks):
                chunks.append(Chunk(
                    content=sc,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": parsed.language,
                        "chunk_type": chunk_type,
                        "symbol": sym_name,
                        "start_line": start + 1,
                        "end_line": min(end, start + sc.count("\n") + 1),
                        "sub_chunk": j,
                    },
                ))
        else:
            chunks.append(Chunk(
                content=content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": parsed.language,
                    "chunk_type": chunk_type,
                    "symbol": sym_name,
                    "start_line": start + 1,
                    "end_line": end,
                },
            ))

    return chunks or _chunk_generic(parsed)


# ── JavaScript/TypeScript chunker ──────────────────────────────────────────────

_JS_FUNC_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\s+(?P<func>\w+)"
    r"|(?:const|let|var)\s+(?P<arrow>\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=\n]+)\s*=>|"
    r"class\s+(?P<cls>\w+))",
    re.MULTILINE,
)

def _chunk_js(parsed: ParsedFile) -> List[Chunk]:
    lines = parsed.content.splitlines(keepends=True)
    chunks: List[Chunk] = []
    matches = list(_JS_FUNC_RE.finditer(parsed.content))
    if not matches:
        return _chunk_generic(parsed)

    for i, m in enumerate(matches):
        start_line = parsed.content[:m.start()].count("\n")
        if i + 1 < len(matches):
            end_line = parsed.content[:matches[i + 1].start()].count("\n")
        else:
            end_line = len(lines)

        content = "".join(lines[start_line:end_line]).strip()
        if not content:
            continue

        name = m.group("func") or m.group("arrow") or m.group("cls") or "unknown"
        chunk_type = "class" if m.group("cls") else "function"

        chunks.append(Chunk(
            content=content[:DEFAULT_CHUNK_SIZE * 2],
            metadata={
                "file_path": parsed.relative_path,
                "language": parsed.language,
                "chunk_type": chunk_type,
                "symbol": name,
                "start_line": start_line + 1,
                "end_line": end_line,
            },
        ))

    return chunks or _chunk_generic(parsed)


# ── Markdown chunker ───────────────────────────────────────────────────────────

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

def _chunk_markdown(parsed: ParsedFile) -> List[Chunk]:
    lines = parsed.content.splitlines(keepends=True)
    chunks: List[Chunk] = []
    matches = list(_MD_HEADING_RE.finditer(parsed.content))

    if not matches:
        # No headings — treat as single chunk
        content = parsed.content.strip()
        if content:
            chunks.append(Chunk(
                content=content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": "markdown",
                    "chunk_type": "document",
                    "heading": parsed.relative_path,
                    "start_line": 1,
                    "end_line": len(lines),
                },
            ))
        return chunks

    for i, m in enumerate(matches):
        start_line = parsed.content[:m.start()].count("\n")
        if i + 1 < len(matches):
            end_line = parsed.content[:matches[i + 1].start()].count("\n")
        else:
            end_line = len(lines)

        content = "".join(lines[start_line:end_line]).strip()
        if not content:
            continue

        heading_level = len(m.group(1))
        heading_text = m.group(2).strip()

        if len(content) > DEFAULT_CHUNK_SIZE * 2:
            sub_chunks = _split_long_chunk(content, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
            for j, sc in enumerate(sub_chunks):
                chunks.append(Chunk(
                    content=sc,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": "markdown",
                        "chunk_type": "section",
                        "heading": heading_text,
                        "heading_level": heading_level,
                        "start_line": start_line + 1,
                        "end_line": end_line,
                        "sub_chunk": j,
                    },
                ))
        else:
            chunks.append(Chunk(
                content=content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": "markdown",
                    "chunk_type": "section",
                    "heading": heading_text,
                    "heading_level": heading_level,
                    "start_line": start_line + 1,
                    "end_line": end_line,
                },
            ))

    return chunks or _chunk_generic(parsed)


# ── Generic sliding-window chunker ─────────────────────────────────────────────

def _split_long_chunk(text: str, size: int, overlap: int) -> List[str]:
    """Split text into overlapping chunks respecting newlines."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            # Snap to nearest newline
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start:
                end = newline_pos + 1
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = max(start + 1, end - overlap)
    return chunks


def _chunk_generic(parsed: ParsedFile) -> List[Chunk]:
    """Sliding-window chunker for any file type."""
    if not parsed.content.strip():
        return []

    lines = parsed.content.splitlines(keepends=True)
    chunks: List[Chunk] = []
    chunk_lines: List[str] = []
    current_size = 0
    start_line = 1

    for line_no, line in enumerate(lines, start=1):
        chunk_lines.append(line)
        current_size += len(line)

        if current_size >= DEFAULT_CHUNK_SIZE:
            content = "".join(chunk_lines).strip()
            if content:
                chunks.append(Chunk(
                    content=content,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": parsed.language,
                        "chunk_type": "code_block",
                        "start_line": start_line,
                        "end_line": line_no,
                    },
                ))
            # Overlap: keep last N characters worth of lines
            overlap_lines: List[str] = []
            overlap_size = 0
            for l in reversed(chunk_lines):
                overlap_lines.insert(0, l)
                overlap_size += len(l)
                if overlap_size >= DEFAULT_CHUNK_OVERLAP:
                    break
            chunk_lines = overlap_lines
            current_size = overlap_size
            start_line = line_no - len(overlap_lines) + 1

    # Last chunk
    if chunk_lines:
        content = "".join(chunk_lines).strip()
        if content:
            chunks.append(Chunk(
                content=content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": parsed.language,
                    "chunk_type": "code_block",
                    "start_line": start_line,
                    "end_line": len(lines),
                },
            ))

    return chunks


# ── Main entry point ───────────────────────────────────────────────────────────

def chunk_file(parsed: ParsedFile) -> List[Chunk]:
    """
    Chunk a parsed file using the most appropriate strategy.

    Priority:
      1. AST-based chunking (tree-sitter) for supported languages
      2. Regex-based language-specific chunker
      3. Generic sliding-window chunker

    Returns a list of Chunk objects with metadata.
    """
    lang = parsed.language or ""

    # Very small files — return as single chunk
    if len(parsed.content) < DEFAULT_CHUNK_SIZE // 2:
        content = parsed.content.strip()
        if not content:
            return []
        return [Chunk(
            content=content,
            metadata={
                "file_path": parsed.relative_path,
                "language": lang,
                "chunk_type": "full_file",
                "start_line": 1,
                "end_line": parsed.line_count,
            },
        )]

    # Try AST-based chunking first (tree-sitter)
    try:
        from app.ingestion.ast_chunker import chunk_file_with_ast
        ast_chunks = chunk_file_with_ast(parsed)
        if ast_chunks is not None and len(ast_chunks) > 0:
            logger.info(
                "ast_chunking_used",
                path=parsed.relative_path,
                language=lang,
                chunks=len(ast_chunks),
            )
            return ast_chunks
    except Exception as exc:
        logger.debug("ast_chunking_fallback", path=parsed.relative_path, error=str(exc))

    # Fall back to regex-based chunkers
    if lang == "python":
        return _chunk_python(parsed)
    elif lang in ("javascript", "typescript"):
        return _chunk_js(parsed)
    elif lang == "markdown":
        return _chunk_markdown(parsed)
    else:
        return _chunk_generic(parsed)


def chunk_repository(parsed_files: List[ParsedFile]) -> List[Chunk]:
    """Chunk all files in the repository."""
    all_chunks: List[Chunk] = []
    for pf in parsed_files:
        try:
            file_chunks = chunk_file(pf)
            all_chunks.extend(file_chunks)
        except Exception as exc:
            logger.warning("chunking_error", path=pf.relative_path, error=str(exc))

    logger.info("chunking_complete", total_chunks=len(all_chunks))
    return all_chunks
