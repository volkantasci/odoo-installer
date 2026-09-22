"""Backup and restore: pg_dump -Fc + filestore tar, streamed through compose exec.

Everything streams between the container and a host file through the runtime's
own stdio (`compose exec -T`), so container-uid-owned filestore bytes never need
host-side ownership fixes. Backups land in `<stack>/backups/<timestamp>/` with a
`manifest.json` carrying sha256 checksums; `verify` re-checks them and `restore`
is plan-first + `--apply --yes` gated because it replaces the database and the
filestore wholesale.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.core.dbms import list_databases
from odoo_installer.core.plan import Step
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import InstanceManifest

BACKUPS_DIR = "backups"
BACKUP_MANIFEST = "manifest.json"
DB_DUMP_NAME = "db.dump"
FILESTORE_NAME = "filestore.tar"
# see core/instances.py: the web container's compose-ordinal suffix
_CHUNK = 1 << 20


@dataclass(frozen=True)
class BackupInfo:
    """One backup directory under <stack>/backups/."""

    timestamp: str
    db: str
    path: Path
    created_at: str
    db_bytes: int
    filestore_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "db": self.db,
            "path": str(self.path),
            "created_at": self.created_at,
            "db_bytes": self.db_bytes,
            "filestore_bytes": self.filestore_bytes,
        }


def resolve_backup_db(docker: ComposeLike, manifest: InstanceManifest) -> str:
    """The db to back up: explicit elsewhere; here, the single Odoo database.

    Odoo databases are postgres databases in the stack's own db container.
    Exactly one non-system database means an unambiguous default; more than one
    requires the caller to pass --db.
    """
    system = {"postgres", "template0", "template1"}
    names = [
        info.name
        for info in list_databases(docker, manifest.dir, manifest.db_service, manifest.db_user)
        if info.name not in system
    ]
    if len(names) == 1:
        return names[0]
    if not names:
        raise StackError(f"no Odoo database in instance {manifest.name!r} yet — create one first")
    raise StackError(
        f"instance {manifest.name!r} has several databases ({', '.join(sorted(names))}); "
        "pass --db explicitly"
    )


def create_backup(
    docker: ComposeLike,
    fs: FileSystemLike,
    manifest: InstanceManifest,
    *,
    db: str,
    hook: str = "",
) -> BackupInfo:
    """Stream a consistent backup now (pg_dump is MVCC-consistent while Odoo runs)."""
    # sub-second precision: scheduled + manual backups can land in the same second
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    backup_dir = manifest.dir / BACKUPS_DIR / timestamp
    fs.ensure_dir(backup_dir)
    db_dump = backup_dir / DB_DUMP_NAME
    filestore_tar = backup_dir / FILESTORE_NAME

    docker.compose_transfer(
        [
            "exec",
            "-T",
            manifest.db_service,
            "pg_dump",
            "-U",
            manifest.db_user,
            "-Fc",
            db,
        ],
        manifest.dir,
        stdout_path=db_dump,
    )
    docker.compose_transfer(
        [
            "exec",
            "-T",
            manifest.web_service,
            "tar",
            "-cf",
            "-",
            "-C",
            "/var/lib/odoo",
            ".",
        ],
        manifest.dir,
        stdout_path=filestore_tar,
    )
    info = BackupInfo(
        timestamp=timestamp,
        db=db,
        path=backup_dir,
        created_at=datetime.now(UTC).isoformat(),
        db_bytes=db_dump.stat().st_size,
        filestore_bytes=filestore_tar.stat().st_size,
    )
    manifest_payload = {
        "tool": "odoo-installer",
        "instance": manifest.name,
        "odoo_version": manifest.odoo_version,
        "image": manifest.image,
        "pg_tag": manifest.pg_tag,
        "db": db,
        "created_at": info.created_at,
        "files": {
            DB_DUMP_NAME: _file_entry(db_dump),
            FILESTORE_NAME: _file_entry(filestore_tar),
        },
    }
    fs.write_text(backup_dir / BACKUP_MANIFEST, json.dumps(manifest_payload, indent=2) + "\n")
    if hook:
        _run_hook(hook, backup_dir)
    return info


def list_backups(fs: FileSystemLike, manifest: InstanceManifest) -> list[BackupInfo]:
    root = manifest.dir / BACKUPS_DIR
    if not fs.exists(root):
        return []
    result: list[BackupInfo] = []
    for entry in sorted(p for p in root.iterdir() if p.is_dir()):
        info = _load_backup(entry)
        if info is not None:
            result.append(info)
    return result


def find_backup(fs: FileSystemLike, manifest: InstanceManifest, timestamp: str) -> BackupInfo:
    path = manifest.dir / BACKUPS_DIR / timestamp
    info = _load_backup(path)
    if info is None:
        available = ", ".join(b.timestamp for b in list_backups(fs, manifest)) or "none"
        raise StackError(
            f"no valid backup {timestamp!r} for instance {manifest.name!r} (available: {available})"
        )
    return info


def verify_backup(backup: BackupInfo) -> list[str]:
    """Recompute checksums; returns the list of problems (empty = healthy)."""
    problems: list[str] = []
    raw = (backup.path / BACKUP_MANIFEST).read_text(encoding="utf-8")
    payload = json.loads(raw)
    for name, entry in payload.get("files", {}).items():
        target = backup.path / name
        if not target.exists():
            problems.append(f"{name}: missing")
            continue
        actual = _sha256(target)
        if actual != entry.get("sha256"):
            problems.append(f"{name}: checksum mismatch")
    return problems


def prune_backups_plan(fs: FileSystemLike, manifest: InstanceManifest, *, keep: int) -> list[Step]:
    """Plan deleting all but the newest `keep` backups (plan-first)."""
    backups = sorted(list_backups(fs, manifest), key=lambda b: b.timestamp)
    doomed = backups[:-keep] if keep > 0 else backups
    steps: list[Step] = []
    for backup in doomed:
        steps.append(
            Step(
                description=f"delete backup {backup.timestamp} ({backup.db}, "
                f"{backup.db_bytes + backup.filestore_bytes} bytes)",
                run=functools.partial(_remove_backup_dir, fs, backup.path),
            )
        )
    return steps


def restore_backup_plan(
    docker: ComposeLike,
    fs: FileSystemLike,
    manifest: InstanceManifest,
    backup: BackupInfo,
) -> list[Step]:
    """Plan restoring db + filestore from `backup` (destructive: --apply --yes)."""
    db_dump = backup.path / DB_DUMP_NAME
    filestore_tar = backup.path / FILESTORE_NAME
    for path in (db_dump, filestore_tar, backup.path / BACKUP_MANIFEST):
        if not fs.exists(path):
            raise StackError(f"backup {backup.timestamp!r} is incomplete: {path.name} missing")
    problems = verify_backup(backup)
    if problems:
        raise StackError(
            f"backup {backup.timestamp!r} failed verification: {'; '.join(problems)} "
            "(restore refused)"
        )

    def stop_web() -> str:
        return docker.compose(["stop", manifest.web_service], manifest.dir) or "stopped"

    def drop_db() -> str:
        docker.compose_transfer(
            [
                "exec",
                "-T",
                manifest.db_service,
                "psql",
                "-U",
                manifest.db_user,
                "-d",
                "postgres",
                "-c",
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{backup.db}' AND pid <> pg_backend_pid()",
            ],
            manifest.dir,
        )
        docker.compose_transfer(
            [
                "exec",
                "-T",
                manifest.db_service,
                "psql",
                "-U",
                manifest.db_user,
                "-d",
                "postgres",
                "-c",
                f"DROP DATABASE IF EXISTS {backup.db}",
            ],
            manifest.dir,
        )
        docker.compose_transfer(
            [
                "exec",
                "-T",
                manifest.db_service,
                "psql",
                "-U",
                manifest.db_user,
                "-d",
                "postgres",
                "-c",
                f"CREATE DATABASE {backup.db} OWNER {manifest.db_user}",
            ],
            manifest.dir,
        )
        return f"recreated empty database {backup.db!r}"

    def restore_db() -> str:
        docker.compose_transfer(
            [
                "exec",
                "-T",
                manifest.db_service,
                "pg_restore",
                "-U",
                manifest.db_user,
                "-d",
                backup.db,
                "--no-owner",
                "--no-privileges",
            ],
            manifest.dir,
            stdin_path=db_dump,
        )
        return f"pg_restore {db_dump.name} into {backup.db!r}"

    def restore_filestore() -> str:
        docker.compose_transfer(
            [
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "sh",
                manifest.web_service,
                "-c",
                "find /var/lib/odoo -mindepth 1 -maxdepth 1 -exec rm -rf {} + "
                "&& tar -xf - -C /var/lib/odoo",
            ],
            manifest.dir,
            stdin_path=filestore_tar,
        )
        return f"filestore restored from {filestore_tar.name}"

    def start_web() -> str:
        return docker.compose(["start", manifest.web_service], manifest.dir) or "started"

    def wait_web() -> str:
        return docker.wait_healthy(f"{manifest.name}-{manifest.web_service}-1")

    return [
        Step(description="stop the web service (Odoo must not write during restore)", run=stop_web),
        Step(description=f"drop and recreate database {backup.db!r}", run=drop_db),
        Step(description=f"restore database from {db_dump}", run=restore_db),
        Step(description=f"replace the filestore from {filestore_tar}", run=restore_filestore),
        Step(description="start the web service", run=start_web),
        Step(description="wait for the web container to become healthy", run=wait_web),
    ]


def _load_backup(path: Path) -> BackupInfo | None:
    manifest_file = path / BACKUP_MANIFEST
    if not manifest_file.exists():
        return None
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        return BackupInfo(
            timestamp=path.name,
            db=payload["db"],
            path=path,
            created_at=payload.get("created_at", ""),
            db_bytes=(path / DB_DUMP_NAME).stat().st_size if (path / DB_DUMP_NAME).exists() else 0,
            filestore_bytes=(path / FILESTORE_NAME).stat().st_size
            if (path / FILESTORE_NAME).exists()
            else 0,
        )
    except (OSError, ValueError, KeyError):
        return None


def _file_entry(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_backup_dir(fs: FileSystemLike, path: Path) -> str:
    fs.remove_tree(path)
    return "deleted"


def _run_hook(hook: str, backup_dir: Path) -> None:
    """Offsite ship hook (rclone/rsync/...): runs with OII_BACKUP_DIR set."""
    env = {**os.environ, "OII_BACKUP_DIR": str(backup_dir)}
    proc = subprocess.run(
        hook, shell=True, capture_output=True, text=True, timeout=1800, env=env, check=False
    )
    if proc.returncode != 0:
        raise StackError(
            f"backup hook failed (exit {proc.returncode}): {(proc.stderr or '').strip()}"
        )
