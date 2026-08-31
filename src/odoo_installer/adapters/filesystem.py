"""Filesystem adapter."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class FileSystemLike(Protocol):
    """What core/ may ask of the filesystem."""

    def disk_free_gib(self, path: Path) -> tuple[float, Path]: ...


class FileSystemAdapter:
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
