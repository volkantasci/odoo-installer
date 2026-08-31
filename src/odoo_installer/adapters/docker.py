"""Docker CLI adapter (subprocess)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from odoo_installer.exceptions import PrerequisiteError, StackError


@dataclass
class ComposeContainerInfo:
    """One container belonging to a compose project (from docker ps labels)."""

    name: str
    service: str
    project: str
    working_dir: str
    image: str
    ports: str
    state: str


class DockerLike(Protocol):
    """What core/ may ask of docker."""

    def engine_version(self) -> str: ...
    def compose_version(self) -> str: ...
    def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str: ...
    def compose_result(
        self, args: list[str], project_dir: Path, timeout_s: int = 300
    ) -> tuple[int, str]: ...
    def wait_healthy(self, container: str, timeout_s: int = 240, poll_s: int = 3) -> str: ...
    def logs(self, container: str, tail: int = 40) -> str: ...
    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]: ...


class DockerAdapter:
    """Thin wrapper around the `docker` CLI; raises PrerequisiteError on failure."""

    def engine_version(self) -> str:
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"], "docker engine")

    def compose_version(self) -> str:
        return self._run(["docker", "compose", "version", "--short"], "docker compose plugin")

    def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str:
        """Run `docker compose <args>` inside `project_dir` (reads its .env)."""
        cmd = ["docker", "compose", *args]
        try:
            proc = subprocess.run(
                cmd,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise StackError(f"docker compose {' '.join(args)}: timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
            raise StackError(f"docker compose {' '.join(args)}: {detail}") from exc
        return proc.stdout.strip()

    def compose_result(
        self, args: list[str], project_dir: Path, timeout_s: int = 300
    ) -> tuple[int, str]:
        """Run a compose command without raising on non-zero exit; returns (code, output).

        Test runs EXPECT failures — the exit code is data, not an adapter error.
        """
        try:
            proc = subprocess.run(
                ["docker", "compose", *args],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StackError(f"docker compose {' '.join(args)}: timed out") from exc
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def wait_healthy(self, container: str, timeout_s: int = 240, poll_s: int = 3) -> str:
        """Poll the container healthcheck until healthy; attach logs on failure."""
        deadline = time.monotonic() + timeout_s
        last_status = "unknown"
        while time.monotonic() < deadline:
            proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", container],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode != 0:
                raise StackError(f"container {container} not found: {(proc.stderr or '').strip()}")
            last_status = proc.stdout.strip()
            if last_status == "healthy":
                return "healthy"
            if last_status == "unhealthy":
                break
            time.sleep(poll_s)
        raise StackError(
            f"container {container} not healthy after {timeout_s}s "
            f"(last status: {last_status}); last logs:\n{self.logs(container)}"
        )

    def logs(self, container: str, tail: int = 40) -> str:
        proc = subprocess.run(
            ["docker", "logs", "--tail", str(tail), container],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return ((proc.stdout or "") + (proc.stderr or "")).strip()

    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]:
        """All containers (any state) whose compose project working_dir matches."""
        cmd = [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project.working_dir={working_dir}",
            "--format",
            "{{json .}}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            raise StackError(f"docker ps failed: {(proc.stderr or '').strip()}")
        containers: list[ComposeContainerInfo] = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except ValueError as exc:
                raise StackError(f"unexpected docker ps output: {line[:120]}") from exc
            labels = _parse_labels(raw.get("Labels", ""))
            containers.append(
                ComposeContainerInfo(
                    name=raw.get("Names", ""),
                    service=labels.get("com.docker.compose.service", ""),
                    project=labels.get("com.docker.compose.project", ""),
                    working_dir=labels.get("com.docker.compose.project.working_dir", ""),
                    image=raw.get("Image", ""),
                    ports=raw.get("Ports", ""),
                    state=raw.get("State", ""),
                )
            )
        return containers

    def _run(self, cmd: list[str], what: str) -> str:
        if shutil.which(cmd[0]) is None:
            raise PrerequisiteError(f"{what}: '{cmd[0]}' binary not found on PATH")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
        except subprocess.TimeoutExpired as exc:
            raise PrerequisiteError(f"{what}: command timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
            raise PrerequisiteError(f"{what}: {detail}") from exc
        return proc.stdout.strip()


def _parse_labels(labels: str) -> dict[str, str]:
    """Parse docker ps's flat comma-separated `key=value` Labels string."""
    parsed: dict[str, str] = {}
    for part in labels.split(","):
        key, sep, value = part.partition("=")
        if sep:
            parsed[key.strip()] = value.strip()
    return parsed


def host_port_for(ports: str, container_port: int) -> int | None:
    """Host port published to `container_port` from a docker ps Ports string."""
    match = re.search(rf":(\d+)->{container_port}/tcp", ports)
    return int(match.group(1)) if match else None
