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
    # Default socket the podman fakes pretend to expose (tests mark it as
    # existing on the FakeFs unless they explicitly probe the missing case).
    DEFAULT_PODMAN_SOCKET = "unix:///run/user/1000/podman/podman.sock"

    def __init__(
        self,
        *,
        runtime: str = "docker",
        engine_version: str = "28.3.3",
        compose_version: str = "v2.39.2",
        engine_error: str | None = None,
        compose_error: str | None = None,
        healthy: bool = True,
        containers: list[dict[str, str]] | None = None,
        compose_results: list[str] | None = None,
        compose_result_results: list[tuple[int, str]] | None = None,
        containers_error: Exception | None = None,
        podman_socket: str | None = DEFAULT_PODMAN_SOCKET,
    ) -> None:
        self.runtime = runtime
        self._engine_version = engine_version
        self._compose_version = compose_version
        self._engine_error = engine_error
        self._compose_error = compose_error
        self._healthy = healthy
        self._containers = containers or []
        self._containers_error = containers_error
        self._podman_socket = podman_socket
        self.compose_results = compose_results if compose_results is not None else []
        self.compose_result_results = (
            compose_result_results if compose_result_results is not None else []
        )
        self.compose_calls: list[tuple[tuple[str, ...], Path]] = []
        self.health_checks: list[str] = []
        self.logged: list[str] = []
        self.container_queries: list[Path] = []
        self.transfer_inputs: list[tuple[tuple[str, ...], Path] | None] = []

    def remote_socket(self) -> str | None:
        if self.runtime != "podman":
            return None
        return self._podman_socket

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

    def compose_transfer(
        self,
        args: list[str],
        project_dir: Path,
        *,
        stdin_path: Path | None = None,
        stdout_path: Path | None = None,
        timeout_s: int = 1800,
    ) -> None:
        self.compose_calls.append((tuple(args), Path(project_dir)))
        self.transfer_inputs.append((tuple(args), Path(stdin_path)) if stdin_path else None)
        if stdout_path is not None:
            stdout_path.write_bytes(f"fake stream for: {' '.join(args)}".encode())

    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]:
        self.container_queries.append(Path(working_dir))
        if self._containers_error is not None:
            raise self._containers_error
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

    def health_status(self, container: str) -> str:
        self.health_checks.append(container)
        if not self._healthy:
            return "unhealthy"
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
        linger: bool | None = False,
        user_units_enabled: set[str] | None = None,
    ) -> None:
        self._busy = busy_ports or set()
        self._has_git = has_git
        self._family = family
        self._docker_group_members = docker_group_members
        self._username = username
        self._binaries = binaries if binaries is not None else {"git", "docker", "sudo"}
        self._linger = linger
        self._user_units_enabled = user_units_enabled or set()
        self.installed: list[list[str]] = []
        self.enabled: list[str] = []
        self.linger_enabled_calls = 0
        self.enabled_user_units: list[str] = []

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

    def linger_enabled(self) -> bool | None:
        self.linger_enabled_calls += 1
        return self._linger

    def user_service_enabled(self, name: str) -> bool | None:
        return name in self._user_units_enabled

    def enable_linger(self) -> str:
        self._linger = True
        return "linger enabled"

    def enable_user_service(self, name: str) -> str:
        self.enabled_user_units.append(name)
        self._user_units_enabled.add(name)
        return f"enabled {name}"


class FakeGitHub:
    def __init__(
        self,
        *,
        branch_exists: bool = True,
        module_manifests: dict[str, str] | None = None,
        org_modules: dict[str, str] | None = None,
    ) -> None:
        self._branch_exists = branch_exists
        self._module_manifests = module_manifests or {}
        self._org_modules = org_modules or {}  # {module: "OCA/repo"} probed hit list
        self.branch_checks: list[tuple[str, str]] = []
        self.manifest_fetches: list[tuple[str, str, str, str]] = []
        self.module_repo_probes: list[tuple[tuple[str, ...], str, str]] = []

    def ping(self) -> str:
        return "api.github.com reachable (4999 core requests left, unauthenticated)"

    def branch_exists(self, repo: str, branch: str) -> bool:
        self.branch_checks.append((repo, branch))
        return self._branch_exists

    def fetch_module_manifest(self, owner: str, repo: str, branch: str, module: str) -> str | None:
        self.manifest_fetches.append((owner, repo, branch, module))
        scoped = self._module_manifests.get(f"{owner}/{repo}/{module}")
        if scoped is not None:
            return scoped
        return self._module_manifests.get(module)

    def find_module_repos(
        self, modules: list[str], branch: str, org: str = "OCA"
    ) -> dict[str, str]:
        self.module_repo_probes.append((tuple(sorted(modules)), branch, org))
        return {m: r for m, r in self._org_modules.items() if m in set(modules)}

    def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]:
        return []


class GitHubDown(FakeGitHub):
    def ping(self) -> str:
        raise GitHubError("api.github.com unreachable")


class FakeFs:
    def __init__(self, free_gib: float = 50.0) -> None:
        self._free_gib = free_gib
        self._known_paths: set[Path] = set()

    def remember(self, path: Path) -> None:
        """Pretend `path` exists (for socket paths outside tmp_path)."""
        self._known_paths.add(path)

    def disk_free_gib(self, path: Path) -> tuple[float, Path]:
        return self._free_gib, path

    def exists(self, path: Path) -> bool:
        return path in self._known_paths or path.exists()

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
        next_commit: str | None = None,
        existing: set[Path] | None = None,
        remote: str = "https://github.com/OCA/server-utils.git",
        branch: str | None = "19.0",
        sample_modules: tuple[str, ...] = (),
    ) -> None:
        self._commit = commit
        self._next_commit = next_commit  # commit AFTER fetch+checkout (upgrade-repos)
        self._existing = existing or set()
        self._remote = remote
        self._branch = branch
        self._sample_modules = sample_modules
        self.cloned: list[tuple[str, Path]] = []
        self.sparse_cloned: list[tuple[str, Path, list[str]]] = []
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

    def sparse_clone(self, url: str, path: Path, branch: str, dirs: list[str]) -> str:
        """Materializes ONLY the requested module dirs (mirrors a partial clone)."""
        target = Path(path)
        self.sparse_cloned.append((url, target, list(dirs)))
        target.mkdir(parents=True, exist_ok=True)
        for module in dirs:
            module_dir = target / module
            module_dir.mkdir(parents=True, exist_ok=True)
            (module_dir / "__manifest__.py").write_text("{}", encoding="utf-8")
        self._existing.add(target)
        return ""

    def checkout(self, path: Path, ref: str) -> str:
        self.checkouts.append((Path(path), ref))
        return ""

    def sparse_checkout_set(self, path: Path, dirs: list[str]) -> str:
        """Records the new cone set and materializes the dirs (like real git)."""
        self.sparse.append(list(dirs))
        target = Path(path)
        for module in dirs:
            module_dir = target / module
            module_dir.mkdir(parents=True, exist_ok=True)
            if not (module_dir / "__manifest__.py").exists():
                (module_dir / "__manifest__.py").write_text("{}", encoding="utf-8")
        return ""

    def is_repo(self, path: Path) -> bool:
        return Path(path) in self._existing

    def remote_url(self, path: Path) -> str:
        return self._remote

    def current_commit(self, path: Path) -> str:
        return self._commit

    def active_branch(self, path: Path) -> str | None:
        return self._branch

    def diff_names(self, path: Path, old: str, new: str) -> list[str]:
        if old == new or self._next_commit is None:
            return []
        return [
            f"{module}/{name}"
            for module in self._sample_modules
            for name in ("__manifest__.py", "models.py")
        ]

    def fetch(self, path: Path) -> str:
        self.fetched.append(Path(path))
        if self._next_commit is not None:
            self._commit = self._next_commit  # like origin/19.0 moving ahead
        return ""
