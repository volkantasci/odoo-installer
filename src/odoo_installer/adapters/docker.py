"""Docker CLI adapter (subprocess)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from odoo_installer.exceptions import PrerequisiteError


class DockerLike(Protocol):
    """What core/ may ask of docker."""

    def engine_version(self) -> str: ...
    def compose_version(self) -> str: ...


class DockerAdapter:
    """Thin wrapper around the `docker` CLI; raises PrerequisiteError on failure."""

    def engine_version(self) -> str:
        return self._run(["docker", "version", "--format", "{{.Server.Version}}"], "docker engine")

    def compose_version(self) -> str:
        return self._run(["docker", "compose", "version", "--short"], "docker compose plugin")

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
