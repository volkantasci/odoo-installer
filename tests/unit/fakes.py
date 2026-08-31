"""Shared fakes for unit tests: stand-ins for the real adapters.

FakeDocker/FakeSystem record calls for assertions; FakeFs performs REAL filesystem
operations (tests pass paths under tmp_path, so everything stays hermetic).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from odoo_installer.exceptions import GitHubError, PrerequisiteError, StackError


class FakeDocker:
    def __init__(
        self,
        *,
        engine_version: str = "28.3.3",
        compose_version: str = "v2.39.2",
        engine_error: str | None = None,
        compose_error: str | None = None,
        healthy: bool = True,
    ) -> None:
        self._engine_version = engine_version
        self._compose_version = compose_version
        self._engine_error = engine_error
        self._compose_error = compose_error
        self._healthy = healthy
        self.compose_calls: list[tuple[tuple[str, ...], Path]] = []
        self.health_checks: list[str] = []
        self.logged: list[str] = []

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
        return f"compose {' '.join(args)} ok"

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
    def ping(self) -> str:
        return "api.github.com reachable (4999 core requests left, unauthenticated)"


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
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        if mode is not None:
            path.chmod(mode)

    def remove_tree(self, path: Path) -> None:
        if path == Path(path.anchor):
            raise StackError("refusing to remove filesystem root")
        shutil.rmtree(path, ignore_errors=True)
