"""
GitHub repository loader.
Validates URLs, queries GitHub API for metadata, and clones the repository.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import httpx
from git import GitCommandError, InvalidGitRepositoryError, Repo

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

GITHUB_URL_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[a-zA-Z0-9_\-\.]+)/(?P<repo>[a-zA-Z0-9_\-\.]+?)(?:\.git)?/?$"
)


class GitHubLoaderError(Exception):
    """Raised when loading fails."""


class GitHubRepositoryInfo:
    def __init__(
        self,
        owner: str,
        name: str,
        description: Optional[str],
        default_branch: str,
        primary_language: Optional[str],
        stars: Optional[int],
        forks: Optional[int],
        license_name: Optional[str],
        latest_commit_sha: Optional[str],
        clone_url: str,
    ) -> None:
        self.owner = owner
        self.name = name
        self.description = description
        self.default_branch = default_branch
        self.primary_language = primary_language
        self.stars = stars
        self.forks = forks
        self.license_name = license_name
        self.latest_commit_sha = latest_commit_sha
        self.clone_url = clone_url


def parse_github_url(url: str) -> Tuple[str, str]:
    """Parse owner/repo from a GitHub URL. Raises GitHubLoaderError on failure."""
    url = url.strip().rstrip("/")
    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise GitHubLoaderError(
            f"Invalid GitHub repository URL: '{url}'. "
            "Expected format: https://github.com/owner/repository"
        )
    return match.group("owner"), match.group("repo")


async def fetch_repository_info(url: str) -> GitHubRepositoryInfo:
    """Fetch repository metadata from the GitHub API."""
    owner, repo_name = parse_github_url(url)

    headers = {"Accept": "application/vnd.github.v3+json"}
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"

    api_url = f"https://api.github.com/repos/{owner}/{repo_name}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(api_url, headers=headers)
        except httpx.RequestError as exc:
            raise GitHubLoaderError(f"Network error contacting GitHub API: {exc}") from exc

        if response.status_code == 404:
            raise GitHubLoaderError(
                f"Repository '{owner}/{repo_name}' not found. "
                "It may be private, deleted, or the URL is incorrect."
            )
        if response.status_code == 403:
            raise GitHubLoaderError(
                "GitHub API rate limit exceeded or access forbidden. "
                "Add a GITHUB_TOKEN to your .env to increase rate limits."
            )
        if response.status_code != 200:
            raise GitHubLoaderError(
                f"GitHub API returned {response.status_code}: {response.text[:200]}"
            )

        data = response.json()

        if data.get("private", False) and not settings.github_token:
            raise GitHubLoaderError(
                "This repository is private. "
                "Provide a GITHUB_TOKEN with repo access in your .env."
            )

        # Fetch latest commit SHA
        default_branch = data.get("default_branch", "main")
        latest_sha: Optional[str] = None
        try:
            commits_url = f"{api_url}/commits/{default_branch}"
            commit_resp = await client.get(commits_url, headers=headers)
            if commit_resp.status_code == 200:
                latest_sha = commit_resp.json().get("sha")
        except Exception:
            pass

        license_name: Optional[str] = None
        if data.get("license") and data["license"].get("name"):
            license_name = data["license"]["name"]

        return GitHubRepositoryInfo(
            owner=owner,
            name=repo_name,
            description=data.get("description"),
            default_branch=default_branch,
            primary_language=data.get("language"),
            stars=data.get("stargazers_count"),
            forks=data.get("forks_count"),
            license_name=license_name,
            latest_commit_sha=latest_sha,
            clone_url=data.get("clone_url", f"https://github.com/{owner}/{repo_name}.git"),
        )


def clone_repository(clone_url: str, dest_dir: Path) -> Repo:
    """
    Clone a repository to dest_dir.
    Returns the Repo object.
    Raises GitHubLoaderError on failure.
    """
    if dest_dir.exists():
        cleanup_repository(dest_dir)

    if settings.github_token:
        # Embed token into clone URL for private repos
        clone_url = clone_url.replace(
            "https://", f"https://{settings.github_token}@"
        )

    logger.info("cloning_repository", url=clone_url.split("@")[-1], dest=str(dest_dir))

    try:
        repo = Repo.clone_from(
            clone_url,
            str(dest_dir),
            depth=1,  # Shallow clone for speed
            single_branch=True,
        )
        return repo
    except GitCommandError as exc:
        raise GitHubLoaderError(f"Git clone failed: {exc.stderr or str(exc)}") from exc
    except Exception as exc:
        raise GitHubLoaderError(f"Unexpected error during clone: {exc}") from exc


def cleanup_repository(dest_dir: Path) -> None:
    """Remove cloned repository directory."""
    if dest_dir.exists():
        import os
        import stat
        def remove_readonly(func, path, _):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass
        try:
            shutil.rmtree(dest_dir, onerror=remove_readonly)
            logger.info("repository_cleaned_up", path=str(dest_dir))
        except Exception as exc:
            logger.warning("cleanup_failed", path=str(dest_dir), error=str(exc))
