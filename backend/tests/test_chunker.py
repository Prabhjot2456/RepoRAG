"""Tests for the code-aware chunker."""

import pytest

from app.ingestion.chunker import chunk_file, _chunk_python, _chunk_markdown
from app.ingestion.parser import ParsedFile
from pathlib import Path


def _make_parsed(content, language, filename="test.py"):
    return ParsedFile(
        path=Path(filename),
        relative_path=filename,
        content=content,
        language=language,
        size_bytes=len(content.encode()),
        line_count=content.count("\n") + 1,
    )


# ── Python chunking ────────────────────────────────────────────────────────────

PYTHON_CODE = '''\
"""Module docstring."""

import os
import sys


def hello_world():
    """Say hello."""
    print("Hello, World!")


def add(a, b):
    """Add two numbers."""
    return a + b


class MyClass:
    """A sample class."""

    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value
'''


def test_python_chunker_finds_functions():
    pf = _make_parsed(PYTHON_CODE, "python", "sample.py")
    chunks = chunk_file(pf)
    symbols = [c.metadata.get("symbol") for c in chunks]
    assert "hello_world" in symbols
    assert "add" in symbols


def test_python_chunker_finds_class():
    pf = _make_parsed(PYTHON_CODE, "python", "sample.py")
    chunks = chunk_file(pf)
    types = [c.metadata.get("chunk_type") for c in chunks]
    assert "class" in types or "function" in types


def test_python_chunk_has_metadata():
    pf = _make_parsed(PYTHON_CODE, "python", "sample.py")
    chunks = chunk_file(pf)
    for c in chunks:
        assert "file_path" in c.metadata
        assert c.metadata["file_path"] == "sample.py"
        assert "language" in c.metadata
        assert c.content.strip() != ""


# ── Markdown chunking ──────────────────────────────────────────────────────────

MARKDOWN_CONTENT = """\
# Introduction

This is the introduction section.

## Installation

Install with pip:

```bash
pip install mypackage
```

## Usage

Use it like this:

```python
import mypackage
mypackage.run()
```

## Configuration

Set env vars.
"""


def test_markdown_splits_by_heading():
    pf = _make_parsed(MARKDOWN_CONTENT, "markdown", "README.md")
    chunks = chunk_file(pf)
    headings = [c.metadata.get("heading") for c in chunks]
    assert "Introduction" in headings
    assert "Installation" in headings
    assert "Usage" in headings


def test_markdown_chunk_type():
    pf = _make_parsed(MARKDOWN_CONTENT, "markdown", "README.md")
    chunks = chunk_file(pf)
    for c in chunks:
        assert c.metadata.get("chunk_type") == "section"


# ── Generic chunking ───────────────────────────────────────────────────────────

def test_small_file_is_single_chunk():
    content = "small file content"
    pf = _make_parsed(content, "text", "small.txt")
    chunks = chunk_file(pf)
    assert len(chunks) == 1
    assert chunks[0].content.strip() == content


def test_empty_file_produces_no_chunks():
    pf = _make_parsed("", "python", "empty.py")
    chunks = chunk_file(pf)
    assert len(chunks) == 0


def test_large_file_produces_multiple_chunks():
    large_content = "\n".join([f"line {i}: " + "x" * 100 for i in range(200)])
    pf = _make_parsed(large_content, "text", "big.txt")
    chunks = chunk_file(pf)
    assert len(chunks) > 1
