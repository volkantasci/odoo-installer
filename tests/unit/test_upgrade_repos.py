"""Tests for `module upgrade-repos` (repo refresh, change detection, recreate)."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker, FakeFs, FakeGit

from odoo_installer.core.instances import load_manifest, save_manifest
from odoo_installer.core.modules import upgrade_repos_plan
from odoo_installer.schemas import InstanceManifest, RepoRecord


def make_manifest(tmp_path: Path, commit: str = "aaa000000000") -> InstanceManifest:
    repo_path = tmp_path / "stack" / "repos" / "oca-web"
    manifest = InstanceManifest(
        name="dev",
        dir=tmp_path / "stack",
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=8069,
        repos=[
            RepoRecord(
                repo="OCA/web",
                url="https://github.com/OCA/web.git",
                branch="19.0",
                commit=commit,
                host_path=repo_path,
                container_path="/mnt/oca/web",
                modules=["web_environment_ribbon"],
                sparse=True,
            )
        ],
    )
    FakeFs().ensure_dir(tmp_path / "stack")
    save_manifest(FakeFs(), manifest)
    return manifest


def test_upgrade_repos_up_to_date_skips_recreate(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    git = FakeGit(
        remote="https://github.com/OCA/web.git", commit="aaa000000000"
    )  # nothing new after fetch
    docker = FakeDocker()
    steps = upgrade_repos_plan(manifest=manifest, git=git, fs=FakeFs(), docker=docker)
    for step in steps:
        note = step.run()
        assert "already at" in note or note.startswith("skipped")
    assert docker.compose_calls == []


def test_upgrade_repos_moves_commit_records_and_recreates(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path, commit="aaa000000000")
    git = FakeGit(
        remote="https://github.com/OCA/web.git",
        commit="aaa000000000",
        next_commit="bbb111111111",
        sample_modules=("web_environment_ribbon",),
    )
    docker = FakeDocker()
    steps = upgrade_repos_plan(manifest=manifest, git=git, fs=FakeFs(), docker=docker)
    notes = [step.run() for step in steps]
    assert any("aaa000000000" in note and "bbb111111111" in note for note in notes)
    assert any("web_environment_ribbon" in note for note in notes)
    # manifest records the new commit
    current = load_manifest(FakeFs(), manifest.dir)
    assert current is not None
    assert current.repos[0].commit == "bbb111111111"
    # web recreated because a mounted module changed
    assert docker.compose_calls
    assert any("up" in " ".join(call[0]) for call in docker.compose_calls)


def test_upgrade_repos_dry_run_executes_nothing(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    git = FakeGit(remote="https://github.com/OCA/web.git", next_commit="bbb111")
    docker = FakeDocker()
    steps = upgrade_repos_plan(manifest=manifest, git=git, fs=FakeFs(), docker=docker)
    assert steps  # plan exists
    assert git.fetched == []
    assert docker.compose_calls == []
