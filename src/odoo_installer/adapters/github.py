"""GitHub API adapter (httpx)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import httpx

from odoo_installer.exceptions import GitHubError
from odoo_installer.schemas import RepoSummary


class GitHubLike(Protocol):
    """What core/ may ask of the GitHub API."""

    def ping(self) -> str: ...
    def branch_exists(self, repo: str, branch: str) -> bool: ...
    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]: ...
    def fetch_module_manifest(
        self, owner: str, repo: str, branch: str, module: str
    ) -> str | None: ...
    def find_module_repos(
        self, modules: list[str], branch: str, org: str = "OCA"
    ) -> dict[str, str]: ...


class GitHubAdapter:
    """Unauthenticated works; set the token env var (default GITHUB_TOKEN) for limits."""

    _PROBE_WORKERS = 12

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
        """True/False for 200/404; anything else is an error (DEVELOPMENT.md §6.1).

        Redirects are followed so renamed repos (OCA reshuffles names now and then)
        keep working; a 301/302 chain that still ends in 200 counts as existing.
        """
        url = f"https://api.github.com/repos/{repo}/branches/{branch}"
        try:
            response = httpx.get(
                url, headers=self._headers(), timeout=self._timeout, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"cannot check branch {branch!r} of {repo}: {exc}") from exc
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise GitHubError(f"cannot check branch {branch!r} of {repo}: HTTP {response.status_code}")

    def fetch_module_manifest(self, owner: str, repo: str, branch: str, module: str) -> str | None:
        """Fetch `<module>/__manifest__.py` content from raw.githubusercontent.com.

        Returns the file text, or None when it does not exist (404) — used to read
        module dependencies before/without cloning. Network failures raise
        GitHubError; a 404 is a normal "not present" answer, not an error.
        """
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{module}/__manifest__.py"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise GitHubError(f"cannot fetch manifest of {owner}/{repo}/{module}: {exc}") from exc
        if response.status_code == 200:
            return response.text
        if response.status_code == 404:
            return None
        raise GitHubError(
            f"cannot fetch manifest of {owner}/{repo}/{module}: HTTP {response.status_code}"
        )

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

    def find_module_repos(
        self, modules: list[str], branch: str, org: str = "OCA"
    ) -> dict[str, str]:
        """Which repos of the org provide each module — by probing raw manifests.

        Lists the org's repos once (paginated, public API), then probes every
        `<module>/__manifest__.py` on the target branch across all repos in
        parallel (raw.githubusercontent.com, so no API rate-limit cost per
        probe). Returns only the modules that were found: `{module: "org/repo"}`;
        when several repos provide the same module the alphabetically first
        repo wins (deterministic).
        """
        repos = self._org_repos(org)
        if not repos:
            return {}
        targets = sorted(set(modules))
        results: dict[str, list[str]] = {module: [] for module in targets}
        with ThreadPoolExecutor(max_workers=self._PROBE_WORKERS) as pool:
            futures = {}
            for module in targets:
                for repo in repos:
                    owner, repo_name = repo.split("/", 1)
                    futures[(module, repo)] = pool.submit(
                        self.fetch_module_manifest, owner, repo_name, branch, module
                    )
            for (module, repo), future in futures.items():
                if future.result() is not None:
                    results[module].append(repo)
        return {module: min(hits) for module, hits in results.items() if hits}

    def _org_repos(self, org: str) -> list[str]:
        """Full names of all repos of the org (paginated public listing)."""
        names: list[str] = []
        page = 1
        while True:
            data = self._get_json(
                f"https://api.github.com/orgs/{org}/repos?per_page=100&page={page}"
            )
            if not isinstance(data, list):
                break
            names.extend(item.get("full_name", "") for item in data if isinstance(item, dict))
            if len(data) < 100:
                break
            page += 1
        return sorted({name for name in names if name})

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
