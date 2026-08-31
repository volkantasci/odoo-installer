"""GitHub API adapter (httpx)."""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from odoo_installer.exceptions import GitHubError
from odoo_installer.schemas import RepoSummary


class GitHubLike(Protocol):
    """What core/ may ask of the GitHub API."""

    def ping(self) -> str: ...
    def branch_exists(self, repo: str, branch: str) -> bool: ...
    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]: ...


class GitHubAdapter:
    """Unauthenticated works; set the token env var (default GITHUB_TOKEN) for limits."""

    def __init__(self, token_env: str = "GITHUB_TOKEN", timeout: float = 10.0) -> None:
        self._token_env = token_env
        self._timeout = timeout

    def ping(self) -> str:
        data = self._get_json("https://api.github.com/rate_limit")
        if not isinstance(data, dict):
            raise GitHubError("unexpected /rate_limit payload")
        try:
            remaining = data["resources"]["core"]["remaining"]
        except (KeyError, TypeError) as exc:
            raise GitHubError("unexpected /rate_limit payload") from exc
        auth = "authenticated" if self._token() else "unauthenticated"
        return f"api.github.com reachable ({remaining} core requests left, {auth})"

    def branch_exists(self, repo: str, branch: str) -> bool:
        """True/False for 200/404; anything else is an error (DEVELOPMENT.md §6.1)."""
        url = f"https://api.github.com/repos/{repo}/branches/{branch}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise GitHubError(f"cannot check branch {branch!r} of {repo}: {exc}") from exc
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise GitHubError(f"cannot check branch {branch!r} of {repo}: HTTP {response.status_code}")

    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]:
        from urllib.parse import quote

        url = (
            "https://api.github.com/search/repositories"
            f"?q={quote(f'{query} org:OCA')}&per_page={limit}&sort=stars"
        )
        data = self._get_json(url)
        items = data.get("items", []) if isinstance(data, dict) else []
        return [
            RepoSummary(
                full_name=item.get("full_name", ""),
                description=item.get("description") or "",
                default_branch=item.get("default_branch", ""),
            )
            for item in items
        ]

    def _token(self) -> str | None:
        return os.environ.get(self._token_env)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_json(self, url: str) -> object:
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise GitHubError(f"api.github.com unreachable: {exc}") from exc
        if response.status_code != 200:
            raise GitHubError(f"{url} returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubError(f"{url} returned non-JSON payload") from exc
