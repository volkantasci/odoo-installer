"""Config + registry persistence tests (DEVELOPMENT.md §5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from odoo_installer import config as config_mod
from odoo_installer.exceptions import ConfigError
from odoo_installer.schemas import GlobalConfig, Registry, RegistryEntry


def test_missing_file_yields_defaults(tmp_path: Path) -> None:
    loaded = config_mod.load_global_config(tmp_path / "config.toml")
    assert loaded == GlobalConfig()


def test_save_load_roundtrip_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = GlobalConfig(instances_root=Path("/srv/odoo"), default_pg_tag=16)
    config_mod.save_global_config(original, path)
    loaded = config_mod.load_global_config(path)
    assert loaded == original
    assert not list(tmp_path.glob("*.tmp"))


def test_save_overwrites_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config_mod.save_global_config(GlobalConfig(default_pg_tag=16), path)
    config_mod.save_global_config(GlobalConfig(default_pg_tag=17), path)
    assert config_mod.load_global_config(path).default_pg_tag == 17


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('instances_root = "/srv"\nbogus_key = 1\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="bogus_key"):
        config_mod.load_global_config(path)


def test_unparseable_toml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("not [ valid", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read"):
        config_mod.load_global_config(path)


def test_inverted_port_range_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("port_range_start = 9000\nport_range_end = 8000\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="port_range_start"):
        config_mod.load_global_config(path)


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("default_pg_tag", "16", 16),
        ("instances_root", "/srv/odoo", Path("/srv/odoo")),
        ("github_token_env", "GH_TOKEN", "GH_TOKEN"),
    ],
)
def test_set_config_value_coerces_raw_strings(
    tmp_path: Path, key: str, raw: str, expected: object
) -> None:
    path = tmp_path / "config.toml"
    updated = config_mod.set_config_value(key, raw, path=path)
    assert getattr(updated, key) == expected
    assert getattr(config_mod.load_global_config(path), key) == expected


def test_set_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="bogus"):
        config_mod.set_config_value("bogus", "1", path=tmp_path / "config.toml")


def test_set_bad_value_is_rejected_and_keeps_old_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config_mod.set_config_value("default_pg_tag", "17", path=path)
    with pytest.raises(ConfigError):
        config_mod.set_config_value("default_pg_tag", "not-a-number", path=path)
    assert config_mod.load_global_config(path).default_pg_tag == 17


def test_registry_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "registry.toml"
    entry = RegistryEntry(name="dev", dir=Path("/home/x/odoo-instances/dev"), http_port=8070)
    registry = Registry(instances={"dev": entry})
    config_mod.save_registry(registry, path)
    assert config_mod.load_registry(path) == registry


def test_registry_missing_file_yields_empty(tmp_path: Path) -> None:
    assert config_mod.load_registry(tmp_path / "registry.toml") == Registry()
