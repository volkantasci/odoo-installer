"""Git adapter (subprocess). Used only for clones owned by odoo-installer; user
checkouts passed via `module add --repo` are never mutated (DEVELOPMENT.md §6.4)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from odoo_installer.exceptions import GitError


class GitLike(Protocol):
    """What core/ may ask of git."""

    def clone(self, url: str, path: Path) -> str: ...
    def fetch(self, path: Path) -> str: ...
    def checkout(self, path: Path, ref: str) -> str: ...
    def sparse_checkout_set(self, path: Path, dirs: list[str]) -> str: ...
    def is_repo(self, path: Path) -> bool: ...
    def remote_url(self, path: Path) -> str: ...
    def current_commit(self, path: Path) -> str: ...
    def active_branch(self, path: Path) -> str | None: ...


class GitAdapter:
    """Thin wrapper around the `git` CLI; raises GitError on failure."""

    def clone(self, url: str, path: Path) -> str:
        return self._run(["git", "clone", url, str(path)], f"clone {url}", timeout_s=900)

    def fetch(self, path: Path) -> str:
        return self._run(["git", "fetch", "origin"], f"fetch {path}", cwd=path, timeout_s=300)

    def checkout(self, path: Path, ref: str) -> str:
        return self._run(["git", "checkout", ref], f"checkout {ref} in {path}", cwd=path)

    def sparse_checkout_set(self, path: Path, dirs: list[str]) -> str:
        self._run(
            ["git", "sparse-checkout", "init", "--cone"],
            f"enable sparse checkout in {path}",
            cwd=path,
        )
        return self._run(
            ["git", "sparse-checkout", "set", *dirs],
            f"sparse checkout {dirs} in {path}",
            cwd=path,
        )

    def is_repo(self, path: Path) -> bool:
        return (path / ".git").exists()

    def remote_url(self, path: Path) -> str:
        return self._run(["git", "remote", "get-url", "origin"], f"remote url of {path}", cwd=path)

    def current_commit(self, path: Path) -> str:
        return self._run(["git", "rev-parse", "HEAD"], f"HEAD of {path}", cwd=path)

    def active_branch(self, path: Path) -> str | None:
        branch = self._run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            f"branch of {path}",
            cwd=path,
        )
        return None if branch == "HEAD" else branch

    def _run(self, cmd: list[str], what: str, cwd: Path | None = None, timeout_s: int = 60) -> str:
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=True
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"{what}: timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
            raise GitError(f"{what}: {detail}") from exc
        return proc.stdout.strip()
