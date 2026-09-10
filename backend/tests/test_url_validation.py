"""Tests for GitHub URL validation."""

import pytest

from app.ingestion.github_loader import GitHubLoaderError, parse_github_url


VALID_URLS = [
    ("https://github.com/tiangolo/fastapi", "tiangolo", "fastapi"),
    ("https://github.com/pallets/flask", "pallets", "flask"),
    ("https://github.com/psf/requests", "psf", "requests"),
    ("https://github.com/user/repo.git", "user", "repo"),
    ("https://github.com/user/my-repo-123", "user", "my-repo-123"),
    ("http://github.com/user/repo", "user", "repo"),
    ("https://github.com/user/repo/", "user", "repo"),
]

INVALID_URLS = [
    "",
    "not-a-url",
    "https://gitlab.com/user/repo",
    "https://github.com/user",
    "https://github.com/",
    "ftp://github.com/user/repo",
    "https://github.com",
    "github.com/user/repo",
]


@pytest.mark.parametrize("url,expected_owner,expected_repo", VALID_URLS)
def test_valid_github_urls(url, expected_owner, expected_repo):
    owner, repo = parse_github_url(url)
    assert owner == expected_owner
    assert repo == expected_repo


@pytest.mark.parametrize("url", INVALID_URLS)
def test_invalid_github_urls(url):
    with pytest.raises(GitHubLoaderError):
        parse_github_url(url)
