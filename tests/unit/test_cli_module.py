"""CLI tests for the `module` sub-app (deps patched, fully offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig, InstanceManifest

runner = CliRunner()

COMPOSE = """services:
  web:
    image: odoo:19.0
    volumes:
      - ./config:/etc/odoo
      - ./addons/local:/mnt/extra-addons
  db:
    image: postgres:17
"""

CONF = """[options]
admin_passwd = x
addons_path = /mnt/extra-addons
db_host = db
"""


def make_container(tmp_path: Path, docker: FakeDocker | None = None) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances", repo_root=tmp_path / "repos"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        docker=docker or FakeDocker(),
        git=FakeGit(sample_modules=("server_util_foo",)),
        system=FakeSystem(),
        github=FakeGitHub(),
        fs=FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def prepared_instance(tmp_path: Path, patch_deps) -> tuple[Container, InstanceManifest]:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    manifest = InstanceManifest.model_validate_json(
        (tmp_path / "instances" / "dev" / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    return container, manifest


def test_module_add_apply_edits_files_and_recreates(patch_deps, tmp_path: Path) -> None:
    container, manifest = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert result.exit_code == 0, result.output
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/mnt/oca/server-utils" in compose
    assert ("up", "-d", "web") in [args for args, _ in container.docker.compose_calls]
    assert "added" in result.output


def test_module_add_dry_run_touches_nothing(patch_deps, tmp_path: Path) -> None:
    _, manifest = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "add", "server-utils"])
    assert result.exit_code == 0
    assert "dry run" in result.output
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/mnt/oca/server-utils" not in compose


def test_module_add_adopted_requires_yes(patch_deps, tmp_path: Path) -> None:
    stack = tmp_path / "existing-stack"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (stack / "config").mkdir()
    (stack / "config" / "odoo.conf").write_text(CONF, encoding="utf-8")
    container = make_container(
        tmp_path,
        docker=FakeDocker(
            containers=[
                {
                    "name": "odoo-docker-web-1",
                    "service": "web",
                    "project": "odoo-docker",
                    "image": "odoo:19",
                    "ports": "0.0.0.0:8069->8069/tcp",
                },
                {
                    "name": "odoo-docker-db-1",
                    "service": "db",
                    "project": "odoo-docker",
                    "image": "postgres:17",
                },
            ]
        ),
    )
    patch_deps(container)
    adopted = runner.invoke(app, ["instance", "adopt", str(stack), "--apply"])
    assert adopted.exit_code == 0, adopted.output

    without_yes = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert without_yes.exit_code == 0
    assert "add --yes" in without_yes.output
    assert (stack / "docker-compose.yml").read_text(encoding="utf-8") == COMPOSE

    with_yes = runner.invoke(app, ["module", "add", "server-utils", "--apply", "--yes"])
    assert with_yes.exit_code == 0, with_yes.output
    assert "/mnt/oca/server-utils" in (stack / "docker-compose.yml").read_text(encoding="utf-8")
    # read-mostly: never restarted by the CLI (config --quiet validation is allowed)
    assert ("up", "-d", "web") not in [args for args, _ in container.docker.compose_calls]
    assert "recreate it with your own tooling" in with_yes.output


def test_module_add_bad_branch_fails(patch_deps, tmp_path: Path) -> None:
    class NoBranch(FakeGitHub):
        def branch_exists(self, repo: str, branch: str) -> bool:
            return False

    container = make_container(tmp_path)
    container.github = NoBranch()  # type: ignore[assignment]
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert result.exit_code == 1
    assert "does not exist on OCA/server-utils" in result.output


def test_module_search_renders_results(patch_deps, tmp_path: Path) -> None:
    from odoo_installer.schemas import RepoSummary

    class Searchable(FakeGitHub):
        def search_repos(self, query: str, limit: int = 10) -> list[RepoSummary]:
            return [
                RepoSummary(
                    full_name="OCA/server-tools", description="Tools", default_branch="19.0"
                )
            ]

    container = make_container(tmp_path)
    container.github = Searchable()  # type: ignore[assignment]
    patch_deps(container)
    result = runner.invoke(app, ["module", "search", "server tools"])
    assert result.exit_code == 0
    assert "OCA/server-tools" in result.output
    assert "19.0" in result.output


def test_module_install_requires_visible_module(patch_deps, tmp_path: Path) -> None:
    _container, _ = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "install", "ghost_module", "--db", "oitest_x"])
    assert result.exit_code == 1
    assert "not visible" in result.output


def test_module_install_runs_odoo_and_reports_state(patch_deps, tmp_path: Path) -> None:
    container, _manifest = prepared_instance(tmp_path, patch_deps)
    add = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert add.exit_code == 0, add.output
    container.docker.compose_results = ["", "server_util_foo|installed\n"]

    result = runner.invoke(
        app,
        [
            "module",
            "install",
            "server_util_foo",
            "--db",
            "oitest_mods",
            "--instance",
            "dev",
            "--allow-untested",
        ],
    )
    assert result.exit_code == 0, result.output
    exec_calls = [args for args, _ in container.docker.compose_calls if args[0] == "exec"]
    assert exec_calls, "expected an odoo exec call"
    args = exec_calls[0]
    assert "odoo" in args and "-i" in args and "--stop-after-init" in args
    assert any(a.startswith("--http-port=8071") for a in args)
    assert "installed" in result.output


def test_module_install_failure_state_exits_1(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = ["", "server_util_foo|uninstallable\n"]
    result = runner.invoke(
        app,
        [
            "module",
            "install",
            "server_util_foo",
            "--db",
            "oitest_mods",
            "--instance",
            "dev",
            "--allow-untested",
        ],
    )
    assert result.exit_code == 1
    assert "not in 'installed' state" in result.output


def test_module_upgrade_uses_u_flag(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = ["", "server_util_foo|installed\n"]
    result = runner.invoke(
        app,
        [
            "module",
            "upgrade",
            "server_util_foo",
            "--db",
            "dev",
            "--instance",
            "dev",
            "--allow-untested",
        ],
    )
    assert result.exit_code == 0, result.output
    exec_calls = [args for args, _ in container.docker.compose_calls if args[0] == "exec"]
    assert "-u" in exec_calls[0]


def test_module_list_shows_repo_modules_with_states(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = ["server_util_foo|installed\n"]
    result = runner.invoke(app, ["module", "list", "--db", "dev", "--instance", "dev"])
    assert result.exit_code == 0, result.output
    assert "server_util_foo" in result.output
    assert "OCA/server-utils" in result.output


def test_module_list_json(patch_deps, tmp_path: Path) -> None:
    import json as jsonlib

    _, _ = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "list", "--json", "--instance", "dev"])
    assert result.exit_code == 0
    payload = jsonlib.loads(result.output)
    assert isinstance(payload, list)


def test_module_remove_unmounts_and_resets_states(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = [""]
    result = runner.invoke(
        app,
        ["module", "remove", "server-utils", "--db", "dev", "--purge-repo", "--apply"],
    )
    assert result.exit_code == 0, result.output
    sqls = [" ".join(args) for args, _ in container.docker.compose_calls if args[0] == "exec"]
    assert any("ir_module_module" in s and "uninstalled" in s for s in sqls)
    compose = (tmp_path / "instances" / "dev" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "oca-server-utils" not in compose
    assert ("up", "-d", "web") in [args for args, _ in container.docker.compose_calls]


def test_module_test_pass_records_whitelist(patch_deps, tmp_path: Path) -> None:
    import tomllib

    _, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    result = runner.invoke(app, ["module", "test", "server_util_foo"])
    assert result.exit_code == 0, result.output
    assert "recorded as tested" in result.output
    data = tomllib.loads((tmp_path / "tested.toml").read_text(encoding="utf-8"))
    assert data["modules"]["server_util_foo"]["repo"] == "OCA/server-utils"


def test_module_test_failure_exits_3(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_result_results = [(1, "FAIL: check_broke")]
    result = runner.invoke(app, ["module", "test", "server_util_foo"])
    assert result.exit_code == 3, result.output
    assert "FAIL" in result.output
    # nothing whitelisted on failure
    assert not (tmp_path / "tested.toml").exists()


def test_module_test_invisible_module_exits_1(patch_deps, tmp_path: Path) -> None:
    _, _ = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "test", "ghost_module"])
    assert result.exit_code == 1, result.output
    assert "not visible" in result.output
