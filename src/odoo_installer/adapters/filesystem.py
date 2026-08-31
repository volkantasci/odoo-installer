"""Filesystem adapter."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from odoo_installer.exceptions import StackError


class FileSystemLike(Protocol):
    """What core/ may ask of the filesystem."""

    def disk_free_gib(self, path: Path) -> tuple[float, Path]: ...
    def exists(self, path: Path) -> bool: ...
    def ensure_dir(self, path: Path) -> None: ...
    def read_text(self, path: Path) -> str | None: ...
    def write_text(self, path: Path, content: str, mode: int | None = None) -> None: ...
    def remove_tree(self, path: Path) -> None: ...


class FileSystemAdapter:
    """All writes are atomic (temp file + rename); secrets get restrictive modes."""

    def disk_free_gib(self, path: Path) -> tuple[float, Path]:
        """Free space in GiB at `path`; walks up to the nearest existing ancestor."""
        probe = path
        while not probe.exists():
            parent = probe.parent
            if parent == probe:
                raise FileNotFoundError(f"no existing ancestor directory for {path}")
            probe = parent
        usage = shutil.disk_usage(probe)
        return usage.free / 2**30, probe

    def exists(self, path: Path) -> bool:
        return path.exists()

    def ensure_dir(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StackError(f"cannot create directory {path}: {exc}") from exc

    def read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StackError(f"cannot read {path}: {exc}") from exc

    def write_text(self, path: Path, content: str, mode: int | None = None) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_name, path)
            if mode is not None:
                path.chmod(mode)
        except OSError as exc:
            raise StackError(f"cannot write {path}: {exc}") from exc

    def remove_tree(self, path: Path) -> None:
        if path == Path(path.anchor):
            raise StackError(f"refusing to remove filesystem root {path}")
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise StackError(f"cannot remove {path}: {exc}") from exc
