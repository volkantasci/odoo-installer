"""CLI tests for the `instance` sub-app (deps patched; all effects stay in tmp_path)."""

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
    fs: FakeFs | None = None,
) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        docker=docker or FakeDocker(),
        system=system or FakeSystem(),
        github=FakeGitHub(),
        fs=fs or FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_create_dry_run_writes_nothing(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "create", "dev"])
    assert result.exit_code == 0
    assert "8069" in result.output
    assert "dry run" in result.output
    assert not (tmp_path / "instances" / "dev").exists()


def test_create_apply_creates_and_starts_stack(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    stack = tmp_path / "instances" / "dev"
    assert (stack / "docker-compose.yml").exists()
    assert container.docker.compose_calls[0][0] == ("up", "-d")
    assert container.docker.health_checks == ["dev-web-1"]
    assert "ready at http://localhost:8069" in result.output


def test_create_apply_reruns_are_idempotent(patch_deps, tmp_path: Path) -> None:
    system = FakeSystem(busy_ports={8069})  # like this machine: 8069 held by a live stack
    container = make_container(tmp_path, system=system)
    patch_deps(container)
    first = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert first.exit_code == 0, first.output
    assert "8070" in first.output
    system.block_port(8070)  # the instance's own container now holds its port
    second = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert second.exit_code == 0, second.output
    assert "8070" in second.output  # port must not drift to 8071 on re-run
    assert "already satisfied" in second.output
    assert len(container.docker.compose_calls) == 2  # one up -d per run, nothing else


def test_create_rejects_invalid_name(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "create", "Bad_Name"])
    assert result.exit_code == 1
    assert "invalid instance name" in result.output


def test_create_auto_allocates_next_free_port(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, system=FakeSystem(busy_ports={8069})))
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    assert "8070" in result.output


def test_create_rejects_busy_requested_port(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, system=FakeSystem(busy_ports={8123})))
    result = runner.invoke(app, ["instance", "create", "dev", "--http-port", "8123"])
    assert result.exit_code == 1
    assert "already in use" in result.output


def test_list_empty_then_populated(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    empty = runner.invoke(app, ["instance", "list"])
    assert empty.exit_code == 0
    assert "no instances" in empty.output
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    populated = runner.invoke(app, ["instance", "list"])
    assert populated.exit_code == 0
    assert "dev" in populated.output
    assert "8069" in populated.output


def test_lifecycle_actions_map_to_compose(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    for action, expected in (
        ("stop", ("stop",)),
        ("start", ("up", "-d")),
        ("restart", ("restart",)),
    ):
        result = runner.invoke(app, ["instance", action, "dev"])
        assert result.exit_code == 0, result.output
        assert container.docker.compose_calls[-1][0] == expected


def test_show_renders_manifest_details(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "show", "dev"])
    assert result.exit_code == 0
    assert "dev" in result.output
    assert "odoo:19.0" in result.output


def test_show_unknown_instance_fails(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "show", "ghost"])
    assert result.exit_code == 1


def test_remove_without_yes_removes_nothing(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "remove", "dev", "--apply"])
    assert result.exit_code == 0
    assert "add --yes" in result.output
    assert (tmp_path / "instances" / "dev").exists()


def test_remove_apply_yes_deletes_everything(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "remove", "dev", "--apply", "--yes", "--remove-data"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "instances" / "dev").exists()
    assert container.docker.compose_calls[-1][0] == (
        "down",
        "--remove-orphans",
        "-v",
    )
    listed = runner.invoke(app, ["instance", "list"])
    assert "no instances" in listed.output


def test_remove_unknown_instance_fails(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "remove", "ghost"])
    assert result.exit_code == 1
    assert "not registered" in result.output
