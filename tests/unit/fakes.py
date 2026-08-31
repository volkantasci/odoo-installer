"""Shared fakes for unit tests: stand-ins for the real adapters, fully offline."""

from __future__ import annotations

from pathlib import Path

from odoo_installer.exceptions import GitHubError, PrerequisiteError


class FakeDocker:
    def engine_version(self) -> str:
        return "28.3.3"

    def compose_version(self) -> str:
        return "v2.39.2"


class DockerEngineDown(FakeDocker):
    def engine_version(self) -> str:
        raise PrerequisiteError("docker engine: Cannot connect to the Docker daemon")


class ComposeMissing(FakeDocker):
    def compose_version(self) -> str:
        raise PrerequisiteError("docker compose plugin: 'docker' binary not found on PATH")


class FakeSystem:
    """Fake host system.

    `docker_group_members` controls the docker group state:
      - tuple of usernames → group exists with those members (default: ("alice",))
      - ()                 → group exists but has no members
      - None               → group does not exist (rootless docker scenario)
    """

    def __init__(
        self,
        *,
        busy_ports: set[int] | None = None,
        has_git: bool = True,
        family: str | None = "pacman",
        docker_group_members: tuple[str, ...] | None = ("alice",),
        username: str = "alice",
    ) -> None:
        self._busy = busy_ports or set()
        self._has_git = has_git
        self._family = family
        self._docker_group_members = docker_group_members
        self._username = username

    def which(self, binary: str) -> str | None:
        if binary == "git" and self._has_git:
            return "/usr/bin/git"
        return None

    def port_in_use(self, port: int) -> bool:
        return port in self._busy

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
