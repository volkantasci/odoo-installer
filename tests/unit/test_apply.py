"""Spec loading/validation and `oii apply` plan assembly (fakes only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.core.spec import load_spec, repo_arg_from_url
from odoo_installer.exceptions import ConfigError, StackError
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()


# ---------------------------------------------------------------- spec loading


def write_spec(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "odoo-stack.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_spec_full_shape(tmp_path: Path) -> None:
    path = write_spec(
        tmp_path,
        """
name = "acme"
http_port = 8069

[ingress]
network = "violetear-ingress"
""",
    )
    with pytest.raises(ConfigError, match="mutually exclusive"):
        load_spec(path)


def test_load_spec_minimal(tmp_path: Path) -> None:
    spec = load_spec(write_spec(tmp_path, 'name = "acme"\n'))
    assert spec.name == "acme"
    assert spec.repos == []
    assert spec.databases == {}


def test_load_spec_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid stack spec"):
        load_spec(write_spec(tmp_path, 'name = "x"\nunknown_key = 1\n'))


def test_load_spec_rejects_bad_db_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid database name"):
        load_spec(write_spec(tmp_path, 'name = "x"\n[databases."9bad"]\ninstall = []\n'))


def test_load_spec_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read stack spec"):
        load_spec(tmp_path / "nope.toml")


def test_repo_arg_from_url_variants() -> None:
    assert repo_arg_from_url("OCA/web") == "OCA/web"
    assert repo_arg_from_url("web") == "OCA/web"
    assert repo_arg_from_url("https://github.com/OCA/web.git") == "OCA/web"
    assert repo_arg_from_url("https://github.com/OCA/web") == "OCA/web"
    assert repo_arg_from_url("git@github.com:OCA/web.git") == "OCA/web"
    with pytest.raises(StackError, match="only GitHub"):
        repo_arg_from_url("https://gitlab.com/OCA/web.git")
    with pytest.raises(StackError, match="invalid repository"):
        repo_arg_from_url("https://github.com/a/b/c")


# ------------------------------------------------------------- apply planning


def make_container(tmp_path: Path, **overrides: object) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        git=overrides.get("git", FakeGit(remote="https://github.com/OCA/web.git")),
        docker=overrides.get("docker", FakeDocker()),
        system=overrides.get("system", FakeSystem()),
        github=overrides.get(
            "github",
            FakeGitHub(
                module_manifests={
                    "web_environment_ribbon": "{'name': 'web_environment_ribbon', 'depends': []}"
                }
            ),
        ),
        fs=overrides.get("fs", FakeFs()),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_apply_dry_run_fresh_instance(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "fresh"
http_port = 18069

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.freshdb]
install = ["base"]
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["instance"] == "fresh"
    assert payload["created"] is True
    descriptions = [s["description"] for s in payload["steps"]]
    assert any("converge repos, databases" in d for d in descriptions)
    assert not (tmp_path / "instances" / "fresh").exists()  # dry run writes nothing


def test_apply_existing_instance_details_repo_and_db_steps(
    patch_deps, tmp_path: Path, monkeypatch
) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    # create the instance first (fakes: no containers, just files + registry)
    created = runner.invoke(app, ["instance", "create", "app1", "--apply"])
    assert created.exit_code == 0, created.output

    spec = write_spec(
        tmp_path,
        """
name = "app1"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.app1db]
install = ["base", "web_environment_ribbon"]
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["created"] is False
    descriptions = [s["description"] for s in payload["steps"]]
    assert any("web_environment_ribbon" in d for d in descriptions)
    assert any("ensure database 'app1db' exists" in d for d in descriptions)
    assert any("install modules base, web_environment_ribbon" in d for d in descriptions)


def test_apply_executes_and_converges_idempotently(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    # every runtime probe in the install step (core listing, psql, odoo -i) is
    # served from this queue; the core listing must contain the core modules
    container.docker = FakeDocker(compose_results=["base\nweb\nmail\nbus\n"] * 24)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "conv"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.convdb]
install = ["base"]
""",
    )
    first = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert first.exit_code == 0, first.output
    assert (tmp_path / "instances" / "conv" / ".odoo-installer.json").exists()

    # second apply: create steps satisfied; repo steps re-run their idempotent
    # plans; install step reports already-installed via module_states stub
    second = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert second.exit_code == 0, second.output
    assert "already satisfied" in second.output


def test_apply_removes_repos_dropped_from_spec(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    (tmp_path / "a").mkdir()
    with_repos = write_spec(
        tmp_path / "a",
        """
name = "diff"
""",
    )
    base = write_spec(
        tmp_path,
        """
name = "diff"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]
""",
    )
    # create with the repo, then apply the repo-less spec
    created = runner.invoke(app, ["apply", str(base), "--apply"])
    assert created.exit_code == 0, created.output
    manifest = json.loads((tmp_path / "instances" / "diff" / ".odoo-installer.json").read_text())
    assert any(r["repo"] == "OCA/web" for r in manifest["repos"])
    removed = runner.invoke(app, ["apply", str(with_repos), "--apply"])
    assert removed.exit_code == 0, removed.output
    assert "remove /mnt/oca/web mount from the compose file" in removed.output
    assert "forget OCA/web in .odoo-installer.json" in removed.output


def test_apply_ingress_spec_publishes_no_port(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "ing"

[ingress]
network = "violetear-ingress"
alias = "tenant-42"

[resources]
memory = "2g"

[settings]
proxy_mode = true
list_db = false
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert result.exit_code == 0, result.output
    compose = (tmp_path / "instances" / "ing" / "docker-compose.yml").read_text()
    assert "ports:" not in compose
    assert "tenant-42" in compose
    assert "mem_limit: 2g" in compose
    conf = (tmp_path / "instances" / "ing" / "config" / "odoo.conf").read_text()
    assert "proxy_mode = True" in conf
    assert "list_db = False" in conf
