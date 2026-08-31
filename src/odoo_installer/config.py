"""Global config and instance registry persistence (TOML, atomic writes).

Precedence (DEVELOPMENT.md §5): CLI flags > instance manifest > global config.toml >
constants. The manifest part arrives with M2; this module owns the global file and the
registry. All writes are atomic: write a temp file in the target directory, then rename.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

from odoo_installer.constants import APP_NAME
from odoo_installer.exceptions import ConfigError
from odoo_installer.schemas import (
    GlobalConfig,
    InstanceManifest,
    Registry,
    TestedModule,
    TestedRegistry,
)


def app_config_dir() -> Path:
    """Directory holding config.toml and registry.toml (XDG-aware)."""
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def default_config_path() -> Path:
    return app_config_dir() / "config.toml"


def default_registry_path() -> Path:
    return app_config_dir() / "registry.toml"


def default_tested_path() -> Path:
    return app_config_dir() / "tested.toml"


def load_tested_registry(path: Path | None = None) -> TestedRegistry:
    path = path or default_tested_path()
    if not path.exists():
        return TestedRegistry()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read tested registry {path}: {exc}") from exc
    try:
        return TestedRegistry.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"invalid tested registry {path}: {exc}") from exc


def save_tested_registry(registry: TestedRegistry, path: Path | None = None) -> None:
    path = path or default_tested_path()
    _atomic_write_toml(path, registry.model_dump(mode="json"))


def record_tested_module(record: TestedModule, path: Path | None = None) -> None:
    registry = load_tested_registry(path)
    registry.modules[record.name] = record
    save_tested_registry(registry, path)


def get_tested_module(name: str, path: Path | None = None) -> TestedModule | None:
    return load_tested_registry(path).modules.get(name)


def instance_logs_dir(manifest: InstanceManifest) -> Path:
    """Where test logs go: the stack dir for created instances, XDG state for
    adopted ones (read-mostly — we never write into an adopted stack)."""
    if manifest.adopted:
        return Path(platformdirs.user_state_dir(APP_NAME, appauthor=False)) / "logs" / manifest.name
    return manifest.dir / "logs"


def load_global_config(path: Path | None = None) -> GlobalConfig:
    """Load the global config; missing file means defaults."""
    path = path or default_config_path()
    if not path.exists():
        return GlobalConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        return GlobalConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"invalid config file {path}: {exc}") from exc


def save_global_config(config: GlobalConfig, path: Path | None = None) -> None:
    path = path or default_config_path()
    _atomic_write_toml(path, config.model_dump(mode="json"))


def set_config_value(key: str, raw_value: str, *, path: Path | None = None) -> GlobalConfig:
    """Set one config key from a raw CLI string; pydantic coerces and validates."""
    path = path or default_config_path()
    config = load_global_config(path)
    data: dict[str, Any] = config.model_dump(mode="json")
    data[key] = raw_value
    try:
        updated = GlobalConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"invalid value for {key!r}: {exc}") from exc
    save_global_config(updated, path)
    return updated


def load_registry(path: Path | None = None) -> Registry:
    path = path or default_registry_path()
    if not path.exists():
        return Registry()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read registry file {path}: {exc}") from exc
    try:
        return Registry.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"invalid registry file {path}: {exc}") from exc


def save_registry(registry: Registry, path: Path | None = None) -> None:
    path = path or default_registry_path()
    _atomic_write_toml(path, registry.model_dump(mode="json"))


def _atomic_write_toml(path: Path, data: dict[str, Any]) -> None:
    content = tomli_w.dumps(data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"cannot create config directory {path.parent}: {exc}") from exc
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            Path(tmp_name).unlink()
        raise ConfigError(f"cannot write config file {path}: {exc}") from exc
