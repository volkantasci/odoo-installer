"""Shared fakes for unit tests: stand-ins for the real adapters.

FakeDocker/FakeSystem record calls for assertions; FakeFs performs REAL filesystem
operations (tests pass paths under tmp_path, so everything stays hermetic).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from odoo_installer.adapters.docker import ComposeContainerInfo
from odoo_installer.exceptions import GitHubError, PrerequisiteError, StackError
from odoo_installer.schemas import RepoSummary


class FakeDocker:
    def __init__(
        self,
        *,
        engine_version: str = "28.3.3",
        compose_version: str = "v2.39.2",
        engine_error: str | None = None,
        compose_error: str | None = None,
        healthy: bool = True,
        containers: list[dict[str, str]] | None = None,
        compose_results: list[str] | None = None,
        compose_result_results: list[tuple[int, str]] | None = None,
    ) -> None:
        self._engine_version = engine_version
        self._compose_version = compose_version
        self._engine_error = engine_error
        self._compose_error = compose_error
        self._healthy = healthy
        self._containers = containers or []
        self.compose_results = compose_results if compose_results is not None else []
        self.compose_result_results = (
            compose_result_results if compose_result_results is not None else []
        )
        self.compose_calls: list[tuple[tuple[str, ...], Path]] = []
        self.health_checks: list[str] = []
        self.logged: list[str] = []
        self.container_queries: list[Path] = []

    def engine_version(self) -> str:
        if self._engine_error is not None:
            raise PrerequisiteError(self._engine_error)
        return self._engine_version

    def compose_version(self) -> str:
        if self._compose_error is not None:
            raise PrerequisiteError(self._compose_error)
        return self._compose_version

    def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str:
        self.compose_calls.append((tuple(args), Path(project_dir)))
        if self.compose_results:
            return self.compose_results.pop(0)
        return f"compose {' '.join(args)} ok"

    def compose_result(
        self, args: list[str], project_dir: Path, timeout_s: int = 300
    ) -> tuple[int, str]:
        self.compose_calls.append((tuple(args), Path(project_dir)))
        if self.compose_result_results:
            return self.compose_result_results.pop(0)
        return 0, f"compose {' '.join(args)} ok"

    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]:
        self.container_queries.append(Path(working_dir))
        return [
            ComposeContainerInfo(
                name=c["name"],
                service=c.get("service", ""),
                project=c.get("project", ""),
                working_dir=str(working_dir),
                image=c.get("image", ""),
                ports=c.get("ports", ""),
                state=c.get("state", "running"),
            )
            for c in self._containers
        ]

    def wait_healthy(self, container: str, timeout_s: int = 240, poll_s: int = 3) -> str:
        self.health_checks.append(container)
        if not self._healthy:
            raise StackError(f"container {container} not healthy")
        return "healthy"

    def logs(self, container: str, tail: int = 40) -> str:
        self.logged.append(container)
        return f"logs of {container}"


class FakeSystem:
    def __init__(
        self,
        *,
        busy_ports: set[int] | None = None,
        has_git: bool = True,
        family: str | None = "pacman",
        docker_group_members: tuple[str, ...] | None = ("alice",),
        username: str = "alice",
        binaries: set[str] | None = None,
    ) -> None:
        self._busy = busy_ports or set()
        self._has_git = has_git
        self._family = family
        self._docker_group_members = docker_group_members
        self._username = username
        self._binaries = binaries if binaries is not None else {"git", "docker", "sudo"}
        self.installed: list[list[str]] = []
        self.enabled: list[str] = []

    def which(self, binary: str) -> str | None:
        if binary == "git" and not self._has_git:
            return None
        if binary in self._binaries:
            return f"/usr/bin/{binary}"
        return None

    def port_in_use(self, port: int) -> bool:
        return port in self._busy

    def block_port(self, port: int) -> None:
        """Simulate a port becoming busy after construction (e.g. our own container)."""
        self._busy.add(port)

    def current_username(self) -> str:
        return self._username

    def group_members(self, group: str) -> list[str] | None:
        if group == "docker":
            if self._docker_group_members is None:
                return None
            return list(self._docker_group_members)
        return None

    def package_manager(self) -> str | None:
        return self._family

    def install_packages(self, packages: list[str]) -> str:
        self.installed.append(list(packages))
        return f"installed {packages}"

    def enable_service(self, name: str) -> str:
        self.enabled.append(name)
        return f"enabled {name}"


class FakeGitHub:
    def __init__(self, *, branch_exists: bool = True) -> None:
        self._branch_exists = branch_exists
        self.branch_checks: list[tuple[str, str]] = []

    def ping(self) -> str:
        return "api.github.com reachable (4999 core requests left, unauthenticated)"

    def branch_exists(self, repo: str, branch: str) -> bool:
        self.branch_checks.append((repo, branch))
        return self._branch_exists

    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]:
        return []


class GitHubDown(FakeGitHub):
    def ping(self) -> str:
        raise GitHubError("api.github.com unreachable")


class FakeFs:
    def __init__(self, free_gib: float = 50.0) -> None:
        self._free_gib = free_gib

    def disk_free_gib(self, path: Path) -> tuple[float, Path]:
        return self._free_gib, path

    def exists(self, path: Path) -> bool:
        return path.exists()

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write_text(self, path: Path, content: str, mode: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous_mode = path.stat().st_mode & 0o777 if path.exists() else None
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        final_mode = mode if mode is not None else (previous_mode or 0o644)
        path.chmod(final_mode)

    def remove_tree(self, path: Path) -> None:
        if path == Path(path.anchor):
            raise StackError("refusing to remove filesystem root")
        shutil.rmtree(path, ignore_errors=True)

    def subdirectories(self, path: Path) -> list[Path]:
        try:
            entries = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")]
        except OSError as exc:
            raise StackError(f"cannot list {path}: {exc}") from exc
        return sorted(entries, key=lambda p: p.name)


class FakeGit:
    """Records git operations; `existing` paths behave as cloned repositories.

    `clone` materializes `sample_modules` (dirs with __manifest__.py) so module
    discovery works against the real filesystem of FakeFs.
    """

    def __init__(
        self,
        *,
        commit: str = "abc1234def5678",
        existing: set[Path] | None = None,
        remote: str = "https://github.com/OCA/server-utils.git",
        branch: str | None = "19.0",
        sample_modules: tuple[str, ...] = (),
    ) -> None:
        self._commit = commit
        self._existing = existing or set()
        self._remote = remote
        self._branch = branch
        self._sample_modules = sample_modules
        self.cloned: list[tuple[str, Path]] = []
        self.fetched: list[Path] = []
        self.checkouts: list[tuple[Path, str]] = []
        self.sparse: list[list[str]] = []
        self.clone_opts: list[tuple[str | None, int | None]] = []

    def clone(
        self, url: str, path: Path, branch: str | None = None, depth: int | None = None
    ) -> str:
        self.clone_opts.append((branch, depth))
        target = Path(path)
        self.cloned.append((url, target))
        target.mkdir(parents=True, exist_ok=True)
        for module in self._sample_modules:
            module_dir = target / module
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "__manifest__.py").write_text("{}", encoding="utf-8")
        self._existing.add(target)
        return ""

    def fetch(self, path: Path) -> str:
        self.fetched.append(Path(path))
        return ""

    def checkout(self, path: Path, ref: str) -> str:
        self.checkouts.append((Path(path), ref))
        return ""

    def sparse_checkout_set(self, path: Path, dirs: list[str]) -> str:
        self.sparse.append(list(dirs))
        return ""

    def is_repo(self, path: Path) -> bool:
        return Path(path) in self._existing

    def remote_url(self, path: Path) -> str:
        return self._remote

    def current_commit(self, path: Path) -> str:
        return self._commit

    def active_branch(self, path: Path) -> str | None:
        return self._branch
