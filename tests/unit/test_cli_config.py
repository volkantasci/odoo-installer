"""CLI tests for the `config` sub-app (deps patched; writes only into tmp_path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer import config as config_mod
from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()


def make_container(tmp_path: Path) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        git=FakeGit(),
        docker=FakeDocker(),
        system=FakeSystem(),
        github=FakeGitHub(),
        fs=FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_config_show_defaults_as_json(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["default_pg_tag"] == 17
    assert payload["github_token_env"] == "GITHUB_TOKEN"
    assert payload["port_range_end"] == 8099


def test_config_show_key_value_lines(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "instances_root" in result.output
    assert "default_pg_tag" in result.output


def test_config_set_writes_validated_file(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["config", "set", "default_pg_tag", "16"])
    assert result.exit_code == 0
    saved = config_mod.load_global_config(tmp_path / "config.toml")
    assert saved.default_pg_tag == 16


def test_config_set_rejects_unknown_key(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["config", "set", "bogus", "1"])
    assert result.exit_code == 1
    assert "bogus" in result.output


def test_config_set_rejects_bad_value(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["config", "set", "default_pg_tag", "not-a-number"])
    assert result.exit_code == 1


def test_config_path_prints_location() -> None:
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert "odoo-installer" in result.output


def test_config_edit_saves_validated_content(patch_deps, tmp_path, monkeypatch):
    container = make_container(tmp_path)
    patch_deps(container)
    (tmp_path / "config.toml").write_text("default_pg_tag = 17\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoo_installer.cli.config._edit_text",
        lambda text, extension=".toml": text.replace("17", "16"),
    )
    result = runner.invoke(app, ["config", "edit"])
    assert result.exit_code == 0, result.output
    assert config_mod.load_global_config(tmp_path / "config.toml").default_pg_tag == 16


def test_config_edit_rejects_invalid_content(patch_deps, tmp_path, monkeypatch):
    container = make_container(tmp_path)
    patch_deps(container)
    monkeypatch.setattr(
        "odoo_installer.cli.config._edit_text",
        lambda text, extension=".toml": "bogus_key = 1\n",
    )
    result = runner.invoke(app, ["config", "edit"])
    assert result.exit_code == 1
    assert "nothing saved" in result.output
    assert not (tmp_path / "config.toml").exists() or "bogus" not in (
        tmp_path / "config.toml"
    ).read_text(encoding="utf-8")


def test_config_edit_no_changes(patch_deps, tmp_path, monkeypatch):
    container = make_container(tmp_path)
    patch_deps(container)
    (tmp_path / "config.toml").write_text("default_pg_tag = 17\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoo_installer.cli.config._edit_text", lambda text, extension=".toml": text
    )
    result = runner.invoke(app, ["config", "edit"])
    assert result.exit_code == 0
    assert "no changes" in result.output
