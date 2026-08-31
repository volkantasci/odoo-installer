"""Host system adapter: PATH lookups, port probing, groups, distro family, packages."""

from __future__ import annotations

import grp
import os
import pwd
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Protocol

from odoo_installer.exceptions import PrerequisiteError

_PACMAN_IDS = {"arch", "manjaro", "omarchy", "endeavouros"}
_APT_IDS = {"debian", "ubuntu", "linuxmint", "pop"}


class SystemLike(Protocol):
    """What core/ may ask of the host system."""

    def which(self, binary: str) -> str | None: ...
    def port_in_use(self, port: int) -> bool: ...
    def current_username(self) -> str: ...
    def group_members(self, group: str) -> list[str] | None: ...
    def package_manager(self) -> str | None: ...
    def install_packages(self, packages: list[str]) -> str: ...
    def enable_service(self, name: str) -> str: ...


class SystemAdapter:
    """Linux-only host queries; no side effects beyond probing sockets."""

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)

    def port_in_use(self, port: int) -> bool:
        """A plain bind on 0.0.0.0 fails if anything listens on the port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                return True
        return False

    def current_username(self) -> str:
        return pwd.getpwuid(os.getuid()).pw_name

    def group_members(self, group: str) -> list[str] | None:
        """Usernames configured in /etc/group, or None if the group does not exist.

        Configured membership is the honest signal: process credentials
        (os.getgroups()) can be stale or restricted (e.g. under sandboxes) even when
        the user is a member and `docker ps` works.
        """
        try:
            return list(grp.getgrnam(group).gr_mem)
        except KeyError:
            return None

    def install_packages(self, packages: list[str]) -> str:
        """Install packages via the distro package manager (requires sudo)."""
        family = self.package_manager()
        if family == "apt":
            cmd = ["sudo", "apt-get", "install", "-y", *packages]
        elif family == "pacman":
            cmd = ["sudo", "pacman", "-S", "--noconfirm", *packages]
        else:
            raise PrerequisiteError(
                "unknown package manager; install manually: " + ", ".join(packages)
            )
        return self._sudo_run(cmd, f"install {', '.join(packages)}")

    def enable_service(self, name: str) -> str:
        return self._sudo_run(
            ["sudo", "systemctl", "enable", "--now", name], f"enable service {name}"
        )

    def _sudo_run(self, cmd: list[str], what: str) -> str:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        except subprocess.TimeoutExpired as exc:
            raise PrerequisiteError(f"{what}: command timed out") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").strip() or f"exit code {exc.returncode}"
            raise PrerequisiteError(f"{what}: {detail}") from exc
        return proc.stdout.strip() or "done"

    def package_manager(self) -> str | None:
        """Map the running distro to pacman/apt, or None if unknown."""
        fields = _read_os_release()
        if not fields:
            return None
        distro_id = fields.get("ID", "")
        id_like = fields.get("ID_LIKE", "").split()
        if distro_id in _PACMAN_IDS or "arch" in id_like:
            return "pacman"
        if distro_id in _APT_IDS or "debian" in id_like:
            return "apt"
        return None


def _read_os_release() -> dict[str, str]:
    try:
        content = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for line in content.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip('"')
    return fields
