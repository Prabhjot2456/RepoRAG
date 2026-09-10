"""Tests for file filtering logic."""

import tempfile
from pathlib import Path

import pytest

from app.ingestion.file_filter import should_include_file, scan_and_filter


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary fake repository structure."""
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / "requirements.txt").write_text("fastapi==0.115.0")

    # Files that should be excluded
    (tmp_path / ".env").write_text("SECRET=abc123")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "some_pkg.js").write_text("// js")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00" * 100)

    return tmp_path


def test_include_python_file(tmp_repo):
    f = tmp_repo / "main.py"
    include, reason = should_include_file(f, tmp_repo)
    assert include is True


def test_include_readme(tmp_repo):
    f = tmp_repo / "README.md"
    include, reason = should_include_file(f, tmp_repo)
    assert include is True


def test_exclude_env_file(tmp_repo):
    f = tmp_repo / ".env"
    include, reason = should_include_file(f, tmp_repo)
    assert include is False


def test_exclude_node_modules(tmp_repo):
    f = tmp_repo / "node_modules" / "some_pkg.js"
    include, reason = should_include_file(f, tmp_repo)
    assert include is False


def test_exclude_pyc(tmp_repo):
    f = tmp_repo / "__pycache__" / "main.cpython-311.pyc"
    include, reason = should_include_file(f, tmp_repo)
    assert include is False


def test_scan_and_filter_counts(tmp_repo):
    included, skipped = scan_and_filter(tmp_repo)
    included_names = [f.name for f in included]

    assert "main.py" in included_names
    assert "README.md" in included_names
    assert "requirements.txt" in included_names

    skipped_names = [f.name for f, _ in skipped]
    assert ".env" in skipped_names


def test_empty_file_excluded(tmp_repo):
    empty = tmp_repo / "empty.py"
    empty.write_text("")
    include, reason = should_include_file(empty, tmp_repo)
    assert include is False
    assert reason == "empty_file"
