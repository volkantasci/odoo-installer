"""GitHub API adapter (httpx)."""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from odoo_installer.exceptions import GitHubError


class GitHubLike(Protocol):
    """What core/ may ask of the GitHub API."""

    def ping(self) -> str: ...


class GitHubAdapter:
    """Unauthenticated works; set the token env var (default GITHUB_TOKEN) for limits."""

    def __init__(self, token_env: str = "GITHUB_TOKEN", timeout: float = 5.0) -> None:
        self._token_env = token_env
        self._timeout = timeout

    def ping(self) -> str:
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get(self._token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = httpx.get(
                "https://api.github.com/rate_limit", headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"api.github.com unreachable: {exc}") from exc
        if response.status_code != 200:
            raise GitHubError(f"api.github.com returned HTTP {response.status_code}")
        try:
            remaining = response.json()["resources"]["core"]["remaining"]
        except (KeyError, ValueError) as exc:
            raise GitHubError("unexpected /rate_limit payload") from exc
        auth = "authenticated" if token else "unauthenticated"
        return f"api.github.com reachable ({remaining} core requests left, {auth})"
