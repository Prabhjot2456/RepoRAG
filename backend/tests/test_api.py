"""API endpoint tests using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_list_repositories_empty():
    """Should return empty list when no repositories are indexed."""
    with patch("app.api.repositories.RepositoryMetadata.list_all", return_value=[]):
        response = client.get("/api/repositories")
        assert response.status_code == 200
        assert response.json() == []


def test_analyze_invalid_url():
    response = client.post(
        "/api/repositories/analyze",
        json={"url": "not-a-github-url"},
    )
    # Should return 400 or trigger ingestion that fails
    assert response.status_code in (200, 400, 422)


def test_analyze_missing_url():
    response = client.post(
        "/api/repositories/analyze",
        json={"url": ""},
    )
    assert response.status_code in (400, 422)


def test_get_nonexistent_repository():
    response = client.get("/api/repositories/nonexistent123")
    assert response.status_code == 404


def test_get_nonexistent_files():
    response = client.get("/api/repositories/nonexistent123/files")
    assert response.status_code == 404


def test_chat_nonexistent_repository():
    response = client.post(
        "/api/repositories/nonexistent123/chat",
        json={"question": "What is this?"},
    )
    assert response.status_code == 404


def test_delete_nonexistent_repository():
    response = client.delete("/api/repositories/nonexistent123")
    assert response.status_code == 404
