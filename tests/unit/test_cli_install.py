"""CLI tests for `install` (deps patched with fakes; nothing touches the host)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()


def make_container(
    tmp_path: Path,
    docker: FakeDocker | None = None,
    system: FakeSystem | None = None,
) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        docker=docker or FakeDocker(),
        system=system or FakeSystem(),
        github=FakeGitHub(),
        fs=FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_install_all_satisfied(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    assert "already satisfied" in result.output


def test_install_dry_run_lists_missing_compose(patch_deps, tmp_path: Path) -> None:
    docker = FakeDocker(compose_error="docker compose plugin: not found")
    patch_deps(make_container(tmp_path, docker=docker))
    result = runner.invoke(app, ["install"])
    assert result.exit_code == 0
    assert "install docker-compose (pacman)" in result.output
    assert "dry run" in result.output
    assert not docker.compose_calls


def test_install_apply_executes_recorded_steps(patch_deps, tmp_path: Path) -> None:
    docker = FakeDocker(engine_error="engine down", compose_error="compose missing")
    system = FakeSystem()  # docker binary present -> service enable; compose missing -> package
    patch_deps(make_container(tmp_path, docker=docker, system=system))
    result = runner.invoke(app, ["install", "--apply"])
    assert result.exit_code == 0
    assert system.enabled == ["docker"]
    assert system.installed == [["docker-compose"]]


def test_install_apply_unknown_package_manager_fails(patch_deps, tmp_path: Path) -> None:
    docker = FakeDocker(engine_error="engine down", compose_error="compose missing")
    system = FakeSystem(family=None)
    patch_deps(make_container(tmp_path, docker=docker, system=system))
    result = runner.invoke(app, ["install", "--apply"])
    assert result.exit_code == 1
    assert "package manager" in result.output
