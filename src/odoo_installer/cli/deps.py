"""Composition root: builds real adapters for CLI commands.

Tests monkeypatch `deps.build` to inject a Container with fakes, so command bodies stay
unchanged between production and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from odoo_installer.adapters.docker import DockerAdapter
from odoo_installer.adapters.filesystem import FileSystemAdapter
from odoo_installer.adapters.git import GitAdapter
from odoo_installer.adapters.github import GitHubAdapter
from odoo_installer.adapters.system import SystemAdapter
from odoo_installer.config import (
    default_config_path,
    default_registry_path,
    default_tested_path,
    load_global_config,
)
from odoo_installer.schemas import GlobalConfig


@dataclass
class Container:
    """Everything a command needs: resolved config, file paths, wired adapters."""

    config: GlobalConfig
    config_path: Path
    registry_path: Path
    tested_path: Path
    docker: DockerAdapter
    git: GitAdapter
    system: SystemAdapter
    github: GitHubAdapter
    fs: FileSystemAdapter


def build(config_path: Path | None = None) -> Container:
    path = config_path or default_config_path()
    config = load_global_config(path)
    return Container(
        config=config,
        config_path=path,
        registry_path=default_registry_path(),
        tested_path=default_tested_path(),
        docker=DockerAdapter(),
        git=GitAdapter(),
        system=SystemAdapter(),
        github=GitHubAdapter(token_env=config.github_token_env),
        fs=FileSystemAdapter(),
    )
