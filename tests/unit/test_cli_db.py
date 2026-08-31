"""CLI tests for the `db` sub-app and `instance adopt` (deps patched, offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()

LIVE_STACK = [
    {
        "name": "odoo-docker-web-1",
        "service": "web",
        "project": "odoo-docker",
        "image": "odoo:19",
        "ports": "0.0.0.0:8069->8069/tcp",
    },
    {"name": "odoo-docker-db-1", "service": "db", "project": "odoo-docker", "image": "postgres:17"},
]


def make_container(
    tmp_path: Path,
    docker: FakeDocker | None = None,
    system: FakeSystem | None = None,
) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        git=FakeGit(),
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


def prepare_instance(tmp_path: Path, patch_deps) -> Container:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    return container


def test_db_list_renders_psql_rows(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results.append("odoo|100 MB\npostgres|7 MB\n")
    result = runner.invoke(app, ["db", "list", "--instance", "dev"])
    assert result.exit_code == 0, result.output
    assert "odoo" in result.output
    assert "100 MB" in result.output


def test_db_list_defaults_to_single_instance(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results.append("odoo|100 MB\n")
    result = runner.invoke(app, ["db", "list"])
    assert result.exit_code == 0, result.output
    assert "odoo" in result.output


def test_db_list_requires_instance_when_ambiguous(patch_deps, tmp_path: Path) -> None:
    prepare_instance(tmp_path, patch_deps)
    second = runner.invoke(app, ["instance", "create", "dev2", "--apply"])
    assert second.exit_code == 0, second.output
    result = runner.invoke(app, ["db", "list"])
    assert result.exit_code == 1
    assert "specify --instance" in result.output


def test_db_create_records_sql(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results = ["", ""]
    result = runner.invoke(app, ["db", "create", "newdb", "--instance", "dev"])
    assert result.exit_code == 0, result.output
    assert "created" in result.output
    sqls = [" ".join(args) for args, _ in container.docker.compose_calls]
    assert any('CREATE DATABASE "newdb"' in s for s in sqls)


def test_db_create_reports_existing(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results = ["1"]
    result = runner.invoke(app, ["db", "create", "odoo", "--instance", "dev"])
    assert result.exit_code == 0
    assert "already exists" in result.output


def test_db_drop_without_yes_is_dry_run(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["db", "drop", "somedb", "--instance", "dev", "--apply"])
    assert result.exit_code == 0
    assert "add --yes" in result.output
    sqls = [" ".join(args) for args, _ in container.docker.compose_calls]
    assert not any("DROP DATABASE" in s for s in sqls)


def test_db_drop_apply_yes_records_guarded_sql(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results = ["", ""]
    result = runner.invoke(app, ["db", "drop", "somedb", "--instance", "dev", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    sqls = [" ".join(args) for args, _ in container.docker.compose_calls]
    assert any("pg_terminate_backend" in s and "datname = 'somedb'" in s for s in sqls)
    assert any('DROP DATABASE IF EXISTS "somedb"' in s for s in sqls)


def test_db_drop_refuses_protected_names(patch_deps, tmp_path: Path) -> None:
    prepare_instance(tmp_path, patch_deps)
    for name in ("postgres", "template0"):
        result = runner.invoke(app, ["db", "drop", name, "--apply", "--yes"])
        assert result.exit_code == 1
        assert "protected" in result.output


def test_db_reset_apply_yes_recreates(patch_deps, tmp_path: Path) -> None:
    container = prepare_instance(tmp_path, patch_deps)
    container.docker.compose_results = ["", "", ""]
    result = runner.invoke(app, ["db", "reset", "somedb", "--instance", "dev", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    sqls = [" ".join(args) for args, _ in container.docker.compose_calls]
    assert any('DROP DATABASE IF EXISTS "somedb"' in s for s in sqls)
    assert any('CREATE DATABASE "somedb"' in s for s in sqls)


def test_adopt_dry_run_and_apply(patch_deps, tmp_path: Path) -> None:
    stack_dir = tmp_path / "existing-stack"
    stack_dir.mkdir()
    docker = FakeDocker(containers=LIVE_STACK)
    patch_deps(make_container(tmp_path, docker=docker))

    dry = runner.invoke(app, ["instance", "adopt", str(stack_dir)])
    assert dry.exit_code == 0, dry.output
    assert "detected: project" in dry.output
    assert "dry run" in dry.output
    assert not (stack_dir / ".odoo-installer.json").exists()

    applied = runner.invoke(app, ["instance", "adopt", str(stack_dir), "--apply"])
    assert applied.exit_code == 0, applied.output
    assert "adopted (read-mostly)" in applied.output
    assert (stack_dir / ".odoo-installer.json").exists()
    listing = runner.invoke(app, ["instance", "list"])
    assert "odoo-docker" in listing.output
    assert "yes" in listing.output  # adopted column


def test_adopt_twice_fails(patch_deps, tmp_path: Path) -> None:
    stack_dir = tmp_path / "existing-stack"
    stack_dir.mkdir()
    patch_deps(make_container(tmp_path, docker=FakeDocker(containers=LIVE_STACK)))
    first = runner.invoke(app, ["instance", "adopt", str(stack_dir), "--apply"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["instance", "adopt", str(stack_dir), "--apply"])
    assert second.exit_code == 1
    assert "already has" in second.output


def test_adopted_start_uses_compose_start(patch_deps, tmp_path: Path) -> None:
    stack_dir = tmp_path / "existing-stack"
    stack_dir.mkdir()
    container = make_container(tmp_path, docker=FakeDocker(containers=LIVE_STACK))
    patch_deps(container)
    assert runner.invoke(app, ["instance", "adopt", str(stack_dir), "--apply"]).exit_code == 0
    result = runner.invoke(app, ["instance", "start", "odoo-docker"])
    assert result.exit_code == 0, result.output
    assert container.docker.compose_calls[-1][0] == ("start",)  # never "up -d"
