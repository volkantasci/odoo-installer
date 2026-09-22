"""Backup subsystem tests (fake runtime; real files under tmp_path)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs

from odoo_installer.core.backup import (
    create_backup,
    find_backup,
    list_backups,
    prune_backups_plan,
    resolve_backup_db,
    restore_backup_plan,
    verify_backup,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import InstanceManifest


def make_manifest(tmp_path: Path) -> InstanceManifest:
    return InstanceManifest(
        name="dev",
        dir=tmp_path / "stack",
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=8069,
    )


def seeded_docker(db_names: list[str]) -> FakeDocker:
    # list_databases output: psql -At rows "name|size"
    listing = "\n".join(f"{name}|8 MB" for name in db_names)
    return FakeDocker(compose_results=[listing])


def test_resolve_backup_db_defaults_to_single_odoo_db() -> None:
    assert (
        resolve_backup_db(seeded_docker(["postgres", "odoo"]), make_manifest(Path("/tmp")))
        == "odoo"
    )


def test_resolve_backup_db_requires_explicit_choice_when_several() -> None:
    with pytest.raises(StackError, match="pass --db"):
        resolve_backup_db(seeded_docker(["postgres", "one", "two"]), make_manifest(Path("/tmp")))


def test_resolve_backup_db_fails_without_any_odoo_db() -> None:
    with pytest.raises(StackError, match="no Odoo database"):
        resolve_backup_db(seeded_docker(["postgres"]), make_manifest(Path("/tmp")))


def test_create_backup_writes_files_and_manifest(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    docker = FakeDocker()
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    info = create_backup(docker, fs, manifest, db="odoo")
    assert (info.path / "db.dump").exists()
    assert (info.path / "filestore.tar").exists()
    assert (info.path / "manifest.json").exists()
    assert info.db == "odoo"
    # streamed through the runtime, never via host-side file access
    dump_call = next(c for c in docker.compose_calls if "pg_dump" in c[0])
    assert dump_call[0][:3] == ("exec", "-T", "db")
    tar_call = next(c for c in docker.compose_calls if "tar" in c[0])
    assert tar_call[0][:3] == ("exec", "-T", "web")
    # verification passes on the fresh backup
    assert verify_backup(info) == []


def test_verify_backup_detects_corruption(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    info = create_backup(FakeDocker(), fs, manifest, db="odoo")
    (info.path / "db.dump").write_bytes(b"corrupted")
    problems = verify_backup(info)
    assert any("db.dump" in problem for problem in problems)


def test_list_and_find_backups(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    stamps = []
    for _ in range(3):
        stamps.append(create_backup(FakeDocker(), fs, manifest, db="odoo").timestamp)
    assert [b.timestamp for b in list_backups(fs, manifest)] == sorted(stamps)
    assert find_backup(fs, manifest, stamps[0]).timestamp == stamps[0]
    with pytest.raises(StackError, match="no valid backup"):
        find_backup(fs, manifest, "19990101T000000")


def test_prune_plan_keeps_newest(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    for _ in range(5):
        create_backup(FakeDocker(), fs, manifest, db="odoo")
    steps = prune_backups_plan(fs, manifest, keep=3)
    assert len(steps) == 2
    apply_steps(steps)
    remaining = [b.timestamp for b in list_backups(fs, manifest)]
    assert len(remaining) == 3
    # idempotent: nothing left to prune
    assert prune_backups_plan(fs, manifest, keep=3) == []


def test_restore_plan_refuses_corrupted_backup(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    info = create_backup(FakeDocker(), fs, manifest, db="odoo")
    (info.path / "filestore.tar").write_bytes(b"broken")
    with pytest.raises(StackError, match="failed verification"):
        restore_backup_plan(FakeDocker(), fs, manifest, info)


def test_restore_plan_applies_in_safe_order(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    fs = FakeFs()
    fs.ensure_dir(manifest.dir)
    docker = FakeDocker()
    info = create_backup(docker, fs, manifest, db="odoo")
    docker.compose_calls.clear()
    steps = restore_backup_plan(docker, fs, manifest, info)
    descriptions = [s.description for s in steps]
    assert descriptions[0].startswith("stop the web service")
    assert "wait for the web container" in descriptions[-1]
    apply_steps(steps, on_step=lambda *a: None)
    args = [c[0] for c in docker.compose_calls]
    # web stops before any psql, pg_restore streams the dump, tar restores the
    # filestore via a throwaway container (web is down), then web starts again
    assert ("stop", "web") in args
    assert any("pg_restore" in a for a in args)
    restore_stdin = [
        entry for entry in docker.transfer_inputs if entry and "pg_restore" in entry[0]
    ]
    assert restore_stdin and restore_stdin[0][1].name == "db.dump"
    # filestore restore runs via a throwaway container (web is down at that point)
    tar_stdin = [
        entry
        for entry in docker.transfer_inputs
        if entry and entry[0][0] == "run" and any("tar -xf" in part for part in entry[0])
    ]
    assert tar_stdin and tar_stdin[0][1].name == "filestore.tar"
    assert docker.health_checks == ["dev-web-1"]
