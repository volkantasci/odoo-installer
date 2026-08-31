"""CLI tests for `doctor` (deps patched with fakes; fully offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem, GitHubDown
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()

ENGINE_DOWN = "docker engine: Cannot connect to the Docker daemon"


def make_container(
    tmp_path: Path,
    docker: FakeDocker | None = None,
    system: FakeSystem | None = None,
    github: FakeGitHub | None = None,
    fs: FakeFs | None = None,
) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        git=FakeGit(),
        docker=docker or FakeDocker(),
        system=system or FakeSystem(),
        github=github or FakeGitHub(),
        fs=fs or FakeFs(),
    )


@pytest.fixture
def patch_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_doctor_json_all_ok(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    statuses = {check["name"]: check["status"] for check in json.loads(result.output)}
    assert set(statuses) == {
        "docker engine",
        "docker compose",
        "docker permissions",
        "git",
        "disk space",
        "ports",
        "github api",
    }
    assert set(statuses.values()) == {"ok"}


def test_doctor_table_renders_without_json(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "docker engine" in result.output
    assert "7 checks" in result.output


def test_doctor_exit_4_on_critical_failure(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, docker=FakeDocker(engine_error=ENGINE_DOWN)))
    assert runner.invoke(app, ["doctor"]).exit_code == 4
    assert runner.invoke(app, ["doctor", "--json"]).exit_code == 4


def test_doctor_warns_do_not_change_exit_code(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, system=FakeSystem(busy_ports={8069}), github=GitHubDown()))
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    statuses = {check["name"]: check["status"] for check in json.loads(result.output)}
    assert statuses["ports"] == "warn"
    assert statuses["github api"] == "warn"


def test_doctor_disk_fail_yields_exit_4(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, fs=FakeFs(free_gib=1.0)))
    assert runner.invoke(app, ["doctor", "--json"]).exit_code == 4
