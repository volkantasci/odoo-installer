"""Pydantic schemas shared across layers (DEVELOPMENT.md §3.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from odoo_installer.constants import (
    DEFAULT_PG_TAG,
    PORT_ALLOCATION_END,
    PORT_ALLOCATION_START,
)


class CheckStatus(StrEnum):
    """Outcome of a doctor check."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class CheckResult(BaseModel):
    """Result of a single doctor check."""

    name: str
    status: CheckStatus
    detail: str = ""
    fix_hint: str = ""


class GlobalConfig(BaseModel):
    """User-editable global configuration (config.toml).

    Unknown keys are rejected so typos in config.toml fail loudly instead of being
    silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    instances_root: Path = Path.home() / "odoo-instances"
    repo_root: Path = Path.home() / "odoo-repos"
    default_pg_tag: int = DEFAULT_PG_TAG
    port_range_start: int = PORT_ALLOCATION_START
    port_range_end: int = PORT_ALLOCATION_END
    github_token_env: str = "GITHUB_TOKEN"
    tested_repo_url: str = ""

    @model_validator(mode="after")
    def _validate_port_range(self) -> Self:
        if self.port_range_start > self.port_range_end:
            raise ValueError("port_range_start must be <= port_range_end")
        if self.port_range_start < 1024:
            raise ValueError("port_range_start must be >= 1024 (unprivileged ports)")
        return self


class RegistryEntry(BaseModel):
    """One managed (or adopted) instance in the registry."""

    name: str
    dir: Path
    http_port: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    adopted: bool = False


class Registry(BaseModel):
    """Contents of registry.toml."""

    instances: dict[str, RegistryEntry] = Field(default_factory=dict)


class RepoSummary(BaseModel):
    """A GitHub repository hit from a module search."""

    full_name: str
    description: str = ""
    default_branch: str = ""


class TestedModule(BaseModel):
    """One module that passed its test run — the installable-addons whitelist."""

    __test__ = False  # not a pytest test class despite the name

    name: str
    repo: str
    branch: str
    commit: str = ""
    tested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    db: str = ""
    log_path: str = ""
    deps: list[str] = Field(default_factory=list)  # OCA/module deps from __manifest__.py


class TestedRegistry(BaseModel):
    """Contents of tested.toml: modules known to pass their tests."""

    __test__ = False  # not a pytest test class despite the name

    modules: dict[str, TestedModule] = Field(default_factory=dict)


class RepoRecord(BaseModel):
    """One OCA repo mounted into an instance (manifest repos list)."""

    repo: str  # "OCA/server-utils"
    url: str
    branch: str
    commit: str
    host_path: Path
    container_path: str
    modules: list[str] = Field(default_factory=list)
    sparse: bool = False


INSTANCE_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"


class InstanceManifest(BaseModel):
    """Per-instance state file (.odoo-installer.json) inside the stack directory.

    Deliberately secret-free: credentials live only in .env and config/odoo.conf.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    name: str = Field(pattern=INSTANCE_NAME_PATTERN)
    dir: Path
    odoo_version: str
    image: str
    pg_tag: int
    http_port: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    adopted: bool = False
    applied_steps: list[str] = Field(default_factory=list)
    # service layout inside the compose project (adopted stacks may differ)
    web_service: str = "web"
    db_service: str = "db"
    db_user: str = "odoo"
    repos: list[RepoRecord] = Field(default_factory=list)
