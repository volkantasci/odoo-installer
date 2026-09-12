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


CROSS_REPO_MANIFESTS = {
    "OCA/account-financial-report/account_financial_report": '{"depends": ["base", "date_range"]}',
    "OCA/server-ux/date_range": '{"depends": ["base"]}',
}


def cross_repo_container(container: Container) -> Container:
    container.github = FakeGitHub(  # type: ignore[assignment]
        module_manifests=CROSS_REPO_MANIFESTS,
        org_modules={"date_range": "OCA/server-ux"},
    )
    container.docker = FakeDocker(compose_results=["base\nweb\nmail\nbus"] * 3)
    return container


def test_module_add_dry_run_shows_dependency_plans(patch_deps, tmp_path: Path) -> None:
    container, manifest = prepared_instance(tmp_path, patch_deps)
    cross_repo_container(container)
    result = runner.invoke(
        app,
        ["module", "add", "account-financial-report", "--modules", "account_financial_report"],
    )
    assert result.exit_code == 0, result.output
    assert "Dependency plan: OCA/server-ux (provides date_range)" in result.output
    assert "verify dependencies of account_financial_report" in result.output
    assert "date_range <- OCA/server-ux" in result.output
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/mnt/oca/server-ux" not in compose  # dry run touched nothing


def test_module_add_apply_provisions_cross_repo_deps(patch_deps, tmp_path: Path) -> None:
    container, manifest = prepared_instance(tmp_path, patch_deps)
    cross_repo_container(container)
    container.git = FakeGit(sample_modules=("account_financial_report",))  # type: ignore[assignment]
    result = runner.invoke(
        app,
        [
            "module",
            "add",
            "account-financial-report",
            "--modules",
            "account_financial_report",
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "resolving dependency OCA/server-ux" in result.output
    sparse_dirs = [dirs for _u, _p, dirs in container.git.sparse_cloned]
    assert sparse_dirs == [["date_range"]]  # dep provision is sparse
    cloned = [p for _u, p in container.git.cloned]
    assert cloned == [manifest.dir / "repos" / "oca-account-financial-report"]
    loaded = InstanceManifest.model_validate_json(
        (manifest.dir / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    assert sorted(r.repo for r in loaded.repos) == [
        "OCA/account-financial-report",
        "OCA/server-ux",
    ]
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    for short in ("server-ux", "account-financial-report"):
        assert f"/mnt/oca/{short}" in compose
    assert [args for args, _ in container.docker.compose_calls].count(("up", "-d", "web")) == 1


def test_module_add_no_resolve_deps_skips_provisioning(patch_deps, tmp_path: Path) -> None:
    container, manifest = prepared_instance(tmp_path, patch_deps)
    cross_repo_container(container)
    container.git = FakeGit(sample_modules=("account_financial_report",))  # type: ignore[assignment]
    result = runner.invoke(
        app,
        [
            "module",
            "add",
            "account-financial-report",
            "--modules",
            "account_financial_report",
            "--no-resolve-deps",
            "--apply",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Dependency plan" not in result.output
    assert container.git.sparse_cloned == []  # no provisioning without the flag
    cloned = [p for _u, p in container.git.cloned]
    assert cloned == [manifest.dir / "repos" / "oca-account-financial-report"]
    loaded = InstanceManifest.model_validate_json(
        (manifest.dir / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    assert [r.repo for r in loaded.repos] == ["OCA/account-financial-report"]


def test_module_add_whole_repo_dry_run_notes_late_provisioning(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    cross_repo_container(container)
    result = runner.invoke(app, ["module", "add", "account-financial-report"])
    assert result.exit_code == 0, result.output
    assert "whole-repo add" in result.output
    assert "Dependency plan" not in result.output  # nothing known before the clone
    assert "no dependencies found" in result.output  # the honest empty report


def test_module_add_whole_repo_provisions_late(patch_deps, tmp_path: Path) -> None:
    """`module add <repo>` (no --modules) must provision cross-repo providers from
    the fresh clone and recreate the web service exactly once."""
    container, manifest = prepared_instance(tmp_path, patch_deps)
    checkout = tmp_path / "checkout-afr"
    module_dir = checkout / "account_financial_report"
    module_dir.mkdir(parents=True)
    (module_dir / "__manifest__.py").write_text(
        '{"depends": ["base", "date_range"]}', encoding="utf-8"
    )
    container.git = FakeGit(  # type: ignore[assignment]
        existing={checkout},
        remote="https://github.com/OCA/account-financial-report.git",
    )
    container.github = FakeGitHub(  # type: ignore[assignment]
        module_manifests={"OCA/server-ux/date_range": '{"depends": ["base"]}'},
        org_modules={"date_range": "OCA/server-ux"},
    )
    container.docker = FakeDocker(compose_results=["base\nweb\nmail\nbus"] * 4)
    result = runner.invoke(
        app, ["module", "add", "account-financial-report", "--repo", str(checkout), "--apply"]
    )
    assert result.exit_code == 0, result.output
    sparse_dirs = [dirs for _u, _p, dirs in container.git.sparse_cloned]
    assert sparse_dirs == [["date_range"]]  # late-phase provision ran
    assert "resolving dependency OCA/server-ux" in result.output
    loaded = InstanceManifest.model_validate_json(
        (manifest.dir / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    assert sorted(r.repo for r in loaded.repos) == [
        "OCA/account-financial-report",
        "OCA/server-ux",
    ]
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/mnt/oca/server-ux" in compose
    assert [args for args, _ in container.docker.compose_calls].count(("up", "-d", "web")) == 1


def test_module_add_container_offline_warns_but_provisions(patch_deps, tmp_path: Path) -> None:
    """Container down: resolved providers are still provisioned, misses are warned."""
    container, _ = prepared_instance(tmp_path, patch_deps)
    cross_repo_container(container)
    container.docker = FakeDocker(compose_results=[""] * 4)  # core listing unavailable
    result = runner.invoke(
        app,
        ["module", "add", "account-financial-report", "--modules", "account_financial_report"],
    )
    assert result.exit_code == 0, result.output
    assert "container offline" in result.output
    assert "Dependency plan: OCA/server-ux (provides date_range)" in result.output


# --- 0.6.4: core modules installable, --with test modules, comma lists --------


def test_module_install_allows_core_modules(patch_deps, tmp_path: Path) -> None:
    """Core modules (sale, account, ...) install without the whitelist gate —
    they are verified against the web container's core addons listing instead."""
    container, _ = prepared_instance(tmp_path, patch_deps)
    container.docker = FakeDocker(
        compose_results=["sale\naccount\nboard\n", "", "sale|installed\n"]
    )
    result = runner.invoke(
        app, ["module", "install", "sale", "--db", "oitest_x", "--instance", "dev"]
    )
    assert result.exit_code == 0, result.output
    assert "installed" in result.output
    assert "--allow-untested" not in result.output


def test_module_install_core_needs_running_stack(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    container.docker = FakeDocker(compose_results=[""])  # core listing unavailable
    result = runner.invoke(
        app, ["module", "install", "sale", "--db", "oitest_x", "--instance", "dev"]
    )
    assert result.exit_code == 1
    assert "not visible" in result.output
    assert "is the stack running?" in result.output


def test_module_test_with_installs_extra_modules(patch_deps, tmp_path: Path) -> None:
    """--with runs a SEPARATE setup stage first (plain install, no test flags):
    Odoo 19 applies chart templates only after the install loop, so a single
    combined -i run would run the module's tests before the journals exist."""
    container, _ = prepared_instance(tmp_path, patch_deps)
    add = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert add.exit_code == 0, add.output
    result = runner.invoke(
        app,
        [
            "module",
            "test",
            "server_util_foo",
            "--with",
            "l10n_generic_coa,sale",
            "--instance",
            "dev",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    odoo_calls = [
        args
        for args, _ in container.docker.compose_calls
        if args[0] == "exec" and "odoo" in args and "--stop-after-init" in args
    ]
    setup_call, test_call = odoo_calls[-2], odoo_calls[-1]
    assert setup_call[setup_call.index("-i") + 1] == "l10n_generic_coa,sale"
    assert "--test-enable" not in setup_call  # plain setup stage
    assert test_call[test_call.index("-i") + 1] == "server_util_foo"
    assert "--test-enable" in test_call
    assert "--test-tags=/server_util_foo" in test_call  # executed tests stay scoped


def test_module_test_with_failing_setup_stage_fails(patch_deps, tmp_path: Path) -> None:
    """A broken setup stage is reported as a FAIL (exit 3), not as a crash."""
    container, _ = prepared_instance(tmp_path, patch_deps)
    add = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert add.exit_code == 0, add.output
    container.docker.compose_result_results = [
        (1, "ERROR: setup stage exploded\n"),
        (0, ""),
    ]
    result = runner.invoke(
        app,
        [
            "module",
            "test",
            "server_util_foo",
            "--with",
            "l10n_generic_coa",
            "--instance",
            "dev",
        ],
    )
    assert result.exit_code == 3
    assert "FAIL" in result.output
    assert "setup stage exploded" in result.output


def test_module_install_accepts_comma_lists(patch_deps, tmp_path: Path) -> None:
    """install/upgrade accept `a,b` exactly like `add --modules` does."""
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker = FakeDocker(
        compose_results=["sale\naccount\n", "", "sale|installed\nserver_util_foo|installed\n"]
    )
    result = runner.invoke(
        app,
        [
            "module",
            "install",
            "server_util_foo,sale",
            "--db",
            "oitest_x",
            "--instance",
            "dev",
            "--allow-untested",
        ],
    )
    assert result.exit_code == 0, result.output
    odoo_call = next(
        args for args, _ in container.docker.compose_calls if args[0] == "exec" and "odoo" in args
    )
    assert odoo_call[odoo_call.index("-i") + 1] == "server_util_foo,sale"
    assert "installed: server_util_foo, sale" in result.output


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
    exec_calls = [
        args for args, _ in container.docker.compose_calls if args[0] == "exec" and "odoo" in args
    ]
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
    exec_calls = [
        args for args, _ in container.docker.compose_calls if args[0] == "exec" and "odoo" in args
    ]
    assert exec_calls, "expected an odoo exec call"
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


def test_module_approve_records_whitelisted_modules(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = ["server_util_foo|installed\n"]
    result = runner.invoke(app, ["module", "approve", "server_util_foo", "--db", "dev"])
    assert result.exit_code == 0, result.output
    assert "approved" in result.output
    import tomllib

    data = tomllib.loads((container.tested_path).read_text(encoding="utf-8"))
    assert data["modules"]["server_util_foo"]["repo"] == "OCA/server-utils"
    assert data["modules"]["server_util_foo"]["db"] == "dev"
    assert data["modules"]["server_util_foo"]["branch"] == "19.0"


def test_module_approve_refuses_not_installed(patch_deps, tmp_path: Path) -> None:
    container, _ = prepared_instance(tmp_path, patch_deps)
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    container.docker.compose_results = ["server_util_foo|uninstalled\n"]
    result = runner.invoke(app, ["module", "approve", "server_util_foo", "--db", "dev"])
    assert result.exit_code == 1
    assert "not in 'installed' state" in result.output
    assert not container.tested_path.exists()


def test_module_approve_refuses_invisible_module(patch_deps, tmp_path: Path) -> None:
    prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["module", "approve", "ghost_module", "--db", "dev"])
    assert result.exit_code == 1
    assert "not visible" in result.output


def test_module_install_resolve_deps_mounts_provider(patch_deps, tmp_path: Path) -> None:
    import tomli_w

    class DepGit(FakeGit):
        """server_util_foo's manifest declares a dep on web_dark_mode (OCA/web)."""

        def clone(self, url: str, path, branch=None, depth=None) -> str:
            note = super().clone(url, path, branch=branch, depth=depth)
            target = Path(path)
            if url.endswith("/OCA/web.git"):
                mod = target / "web_dark_mode"
                mod.mkdir(parents=True, exist_ok=True)
                (mod / "__manifest__.py").write_text(
                    '{"name": "web_dark_mode", "depends": []}', encoding="utf-8"
                )
            else:
                mod = target / "server_util_foo"
                mod.mkdir(parents=True, exist_ok=True)
                (mod / "__manifest__.py").write_text(
                    '{"name": "server_util_foo", "depends": ["base", "web_dark_mode"]}',
                    encoding="utf-8",
                )
            return note

    container = make_container(tmp_path, docker=FakeDocker())
    container.git = DepGit(sample_modules=("server_util_foo",))
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    # central catalog: the dep module is approved, provided by OCA/web
    catalog = {
        "server_util_foo": {
            "name": "server_util_foo",
            "repo": "OCA/server-utils",
            "branch": "19.0",
            "commit": "abc1234def5678",
            "tested_at": "2026-09-01T10:00:00Z",
            "db": "dev",
            "log_path": "",
            "deps": ["web_dark_mode"],
        },
        "web_dark_mode": {
            "name": "web_dark_mode",
            "repo": "OCA/web",
            "branch": "19.0",
            "commit": "d4bfccf526ab7519de75db4e8d9dd3d247cf45d5",
            "tested_at": "2026-09-01T10:00:00Z",
            "db": "odoo",
            "log_path": "",
            "deps": [],
        },
    }
    (container.tested_path).write_text(tomli_w.dumps({"modules": catalog}), encoding="utf-8")

    without = runner.invoke(app, ["module", "install", "server_util_foo", "--db", "dev"])
    assert without.exit_code == 1
    assert "missing OCA dependencies need mounting" in without.output
    assert "OCA/web" in without.output

    container.docker.compose_results = [
        "base\nweb\nmail\nproduct\n",  # core addons listing (pre-mount resolver)
        "base\nweb\nmail\nproduct\n",  # core addons listing (dep report in module add)
        "",  # module add: compose config pre-validation
        "",  # module add: compose config post-validation
        "",  # module add: recreate web (up -d)
        "install ok\n",  # odoo -i run
        "server_util_foo|installed\nweb_dark_mode|installed\n",
    ]
    result = runner.invoke(
        app, ["module", "install", "server_util_foo", "--db", "dev", "--resolve-deps"]
    )
    assert result.exit_code == 0, result.output
    assert "resolving dependency" in result.output
    assert "OCA/web" in result.output
    manifest = tmp_path / "instances" / "dev" / ".odoo-installer.json"
    assert "OCA/web" in manifest.read_text(encoding="utf-8")
    assert "/mnt/oca/web" in (tmp_path / "instances" / "dev" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    install_calls = [
        " ".join(args) for args, _ in container.docker.compose_calls if args[0] == "exec"
    ]
    assert any("-i server_util_foo,web_dark_mode" in call for call in install_calls)


def test_module_install_without_resolver_lets_core_deps_pass(patch_deps, tmp_path: Path) -> None:
    class CoreDepGit(FakeGit):
        def clone(self, url: str, path, branch=None, depth=None) -> str:
            note = super().clone(url, path, branch=branch, depth=depth)
            (Path(path) / "server_util_foo" / "__manifest__.py").write_text(
                '{"name": "server_util_foo", "depends": ["base", "product"]}',
                encoding="utf-8",
            )
            return note

    container = make_container(tmp_path, docker=FakeDocker())
    container.git = CoreDepGit(sample_modules=("server_util_foo",))
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    import tomli_w

    entry = {
        "name": "server_util_foo",
        "repo": "OCA/server-utils",
        "branch": "19.0",
        "commit": "abc1234def5678",
        "tested_at": "2026-09-01T10:00:00Z",
        "db": "dev",
        "log_path": "",
        "deps": ["base", "product"],
    }
    (container.tested_path).write_text(
        tomli_w.dumps({"modules": {"server_util_foo": entry}}), encoding="utf-8"
    )
    container.docker.compose_results = ["install ok\n", "server_util_foo|installed\n"]
    result = runner.invoke(app, ["module", "install", "server_util_foo", "--db", "dev"])
    assert result.exit_code == 0, result.output  # core deps never block the cheap check
