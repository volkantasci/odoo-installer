"""Container runtime CLI adapter (subprocess): Podman or Docker, compose spec.

`ComposeAdapter` shells out to exactly one runtime binary (`podman` or `docker`)
chosen at construction time. `resolve_runtime` maps the configured value to a
concrete runtime — "auto" prefers Podman and falls back to Docker. Both engines
speak the compose specification; the adapter normalizes the few JSON output
differences (podman's `ps` emits Labels as a map and Ports as a list) so core/
never has to care which runtime is underneath.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from odoo_installer.exceptions import PrerequisiteError, StackError

RuntimeName = Literal["podman", "docker"]

# Allowed `container_runtime` config values (GlobalConfig validates the literal).
RUNTIME_CHOICES: tuple[str, ...] = ("auto", "podman", "docker")


@dataclass
class ComposeContainerInfo:
    """One container belonging to a compose project (from `ps` labels)."""

    name: str
    service: str
    project: str
    working_dir: str
    image: str
    ports: str
    state: str


class ComposeLike(Protocol):
    """What core/ may ask of the container runtime."""

    runtime: RuntimeName

    def engine_version(self) -> str: ...
    def compose_version(self) -> str: ...
    def remote_socket(self) -> str | None: ...
    def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str: ...
    def compose_result(
        self, args: list[str], project_dir: Path, timeout_s: int = 300
    ) -> tuple[int, str]: ...
    def wait_healthy(self, container: str, timeout_s: int = 240, poll_s: int = 3) -> str: ...
    def logs(self, container: str, tail: int = 40) -> str: ...
    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]: ...


def resolve_runtime(
    configured: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    reachable: Callable[[RuntimeName], bool] | None = None,
) -> RuntimeName:
    """Map the configured value to a concrete runtime, verifying usability.

    Explicit values must have their binary on PATH ("auto" probes Podman first,
    then Docker; a runtime that is installed but not answering is skipped).
    """
    if configured not in RUNTIME_CHOICES:
        raise PrerequisiteError(
            f"invalid container_runtime {configured!r}: use one of {', '.join(RUNTIME_CHOICES)}"
        )
    if configured != "auto":
        if which(configured) is None:
            raise PrerequisiteError(
                f"container_runtime is {configured!r} but the {configured!r} binary is not on PATH"
            )
        return configured  # type: ignore[return-value]  # narrowed by RUNTIME_CHOICES
    probe = reachable if reachable is not None else _runtime_reachable
    candidates: tuple[RuntimeName, ...] = ("podman", "docker")
    for candidate in candidates:
        if which(candidate) is not None and probe(candidate):
            return candidate
    raise PrerequisiteError(
        "no usable container runtime found; install podman (preferred) or docker"
    )


def _runtime_reachable(runtime: RuntimeName) -> bool:
    if runtime == "podman":
        cmd = ["podman", "info", "--format", "{{.Version.Version}}"]
    else:
        cmd = ["docker", "version", "--format", "{{.Server.Version}}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


class ComposeAdapter:
    """Thin wrapper around one runtime CLI; raises PrerequisiteError on failure.

    The environment is inherited as-is, so `CONTAINER_HOST`/`DOCKER_HOST` pass
    through to the compose provider unchanged (rootless and remote sockets work).
    """

    runtime: RuntimeName

    def __init__(self, runtime: RuntimeName = "docker") -> None:
        self.runtime = runtime

    def engine_version(self) -> str:
        if self.runtime == "podman":
            return self._run(
                ["podman", "info", "--format", "{{.Version.Version}}"], "podman engine"
            )
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"], "docker engine")

    def compose_version(self) -> str:
        return self._run(
            [self.runtime, "compose", "version", "--short"], f"{self.runtime} compose provider"
        )

    def remote_socket(self) -> str | None:
        """Podman's rootless socket URI (e.g. unix:///run/user/1000/podman/podman.sock).

        An external compose provider talks to podman through this socket; when it
        is not listening, `podman compose version` still succeeds while actual
        compose operations fail. Docker returns None (the CLI and the compose
        plugin share the daemon connection, nothing extra to check).
        """
        if self.runtime != "podman":
            return None
        try:
            proc = subprocess.run(
                ["podman", "info", "--format", "{{.Host.RemoteSocket.Path}}"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None

    def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str:
        """Run `<runtime> compose <args>` inside `project_dir` (reads its .env)."""
        cmd = [self.runtime, "compose", *args]
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
            raise StackError(f"{self.runtime} compose {' '.join(args)}: timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
            raise StackError(f"{self.runtime} compose {' '.join(args)}: {detail}") from exc
        return proc.stdout.strip()

    def compose_result(
        self, args: list[str], project_dir: Path, timeout_s: int = 300
    ) -> tuple[int, str]:
        """Run a compose command without raising on non-zero exit; returns (code, output).

        Test runs EXPECT failures — the exit code is data, not an adapter error.
        """
        try:
            proc = subprocess.run(
                [self.runtime, "compose", *args],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise StackError(f"{self.runtime} compose {' '.join(args)}: timed out") from exc
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def wait_healthy(self, container: str, timeout_s: int = 240, poll_s: int = 3) -> str:
        """Poll the container healthcheck until healthy; attach logs on failure."""
        deadline = time.monotonic() + timeout_s
        last_status = "unknown"
        while time.monotonic() < deadline:
            proc = subprocess.run(
                [self.runtime, "inspect", "-f", "{{.State.Health.Status}}", container],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode != 0:
                raise self._inspect_error(container, (proc.stderr or "").strip())
            last_status = proc.stdout.strip()
            if last_status == "healthy":
                return "healthy"
            if last_status == "unhealthy":
                break
            if not last_status:
                # docker prints an empty status for containers without a
                # healthcheck instead of failing; waiting would be pointless.
                raise StackError(
                    f"container {container} has no healthcheck to wait for "
                    "(only the web service of a created stack has one)"
                )
            time.sleep(poll_s)
        raise StackError(
            f"container {container} not healthy after {timeout_s}s "
            f"(last status: {last_status}); last logs:\n{self.logs(container)}"
        )

    def _inspect_error(self, container: str, stderr: str) -> StackError:
        if "no such" in stderr.lower():
            return StackError(f"container {container} not found: {stderr}")
        # podman fails with a nil-pointer template error when the container
        # exists but defines no healthcheck; docker prints an empty status.
        return StackError(
            f"container {container} has no healthcheck to wait for "
            f"(only the web service of a created stack has one): {stderr}"
        )

    def logs(self, container: str, tail: int = 40) -> str:
        proc = subprocess.run(
            [self.runtime, "logs", "--tail", str(tail), container],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return ((proc.stdout or "") + (proc.stderr or "")).strip()

    def compose_containers(self, working_dir: Path) -> list[ComposeContainerInfo]:
        """All containers (any state) whose compose project working_dir matches."""
        cmd = [
            self.runtime,
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project.working_dir={working_dir}",
            "--format",
            "{{json .}}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            raise StackError(f"{self.runtime} ps failed: {(proc.stderr or '').strip()}")
        containers: list[ComposeContainerInfo] = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except ValueError as exc:
                raise StackError(f"unexpected {self.runtime} ps output: {line[:120]}") from exc
            labels = _normalize_labels(raw.get("Labels"))
            containers.append(
                ComposeContainerInfo(
                    name=_normalize_names(raw.get("Names", "")),
                    service=labels.get("com.docker.compose.service", ""),
                    project=labels.get("com.docker.compose.project", ""),
                    working_dir=labels.get("com.docker.compose.project.working_dir", ""),
                    image=str(raw.get("Image", "")),
                    ports=_normalize_ports(raw.get("Ports")),
                    state=str(raw.get("State", "")),
                )
            )
        return containers

    def _run(self, cmd: list[str], what: str) -> str:
        if shutil.which(cmd[0]) is None:
            raise PrerequisiteError(f"{what}: '{cmd[0]}' binary not found on PATH")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=True)
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


def _normalize_labels(value: object) -> dict[str, str]:
    """docker emits a flat string, podman a JSON map (or null)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return _parse_labels(str(value))


def _normalize_ports(value: object) -> str:
    """Normalize to docker's `host_ip:host->container/proto` string form."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    parts: list[str] = []
    for mapping in value if isinstance(value, list) else []:
        host_port = mapping.get("host_port")
        container_port = mapping.get("container_port")
        if host_port is None or container_port is None:
            continue
        host_ip = mapping.get("host_ip") or "0.0.0.0"
        protocol = mapping.get("protocol") or "tcp"
        parts.append(f"{host_ip}:{host_port}->{container_port}/{protocol}")
    return ", ".join(parts)


def _normalize_names(value: object) -> str:
    """docker emits one name string, podman a list (first entry is the name)."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def host_port_for(ports: str, container_port: int) -> int | None:
    """Host port published to `container_port` from a docker ps Ports string."""
    match = re.search(rf":(\d+)->{container_port}/tcp", ports)
    return int(match.group(1)) if match else None


# Backwards-compatible aliases for pre-0.7 integrations (DEVELOPMENT.md §3).
ComposeLike = ComposeLike
ComposeAdapter = ComposeAdapter
