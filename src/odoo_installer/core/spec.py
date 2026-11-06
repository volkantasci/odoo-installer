"""Declarative stack specification (odoo-stack.toml) for `oii apply`.

The spec is the desired state of ONE instance: stack knobs, OCA repos, databases
and the modules each database must have installed. `oii apply` converges the
instance to it — see core/apply.py — so a control plane (or an operator) can
treat the file as the single source of truth and re-run apply idempotently.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from odoo_installer.constants import ODOO_VERSION
from odoo_installer.exceptions import ConfigError, StackError
from odoo_installer.schemas import INSTANCE_NAME_PATTERN, StackExtras


class IngressSpec(BaseModel):
    """Attach web to an external reverse-proxy network; no host port."""

    model_config = ConfigDict(extra="forbid")

    network: str = Field(min_length=1)
    alias: str | None = None


class ResourcesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory: str | None = Field(default=None, pattern=r"^\d+[kmg]?$")
    cpus: float | None = Field(default=None, gt=0)


class SettingsSpec(BaseModel):
    """odoo.conf knobs the CLI renders."""

    model_config = ConfigDict(extra="forbid")

    proxy_mode: bool | None = None
    list_db: bool | None = None
    workers: int | None = Field(default=None, ge=0)
    max_cron_threads: int | None = Field(default=None, ge=0)
    limit_memory_soft: str | None = Field(default=None, pattern=r"^\d+[kmg]?$")
    limit_memory_hard: str | None = Field(default=None, pattern=r"^\d+[kmg]?$")


class RepoSpec(BaseModel):
    """One OCA repository to clone and mount (branch is fixed by D2: Odoo 19.0)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=3)
    modules: list[str] = Field(default_factory=list)

    @property
    def repo_arg(self) -> str:
        return repo_arg_from_url(self.url)


class DatabaseDefaults(BaseModel):
    """First-initialisation defaults for a fresh database.

    Applied through Odoo's ORM only when Odoo creates the database. Re-applying
    the spec never touches them, so customer/operator changes always win.
    """

    model_config = ConfigDict(extra="forbid")

    # Odoo/XPG locale code, e.g. "tr_TR" or "en_US"
    lang: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(?:_[A-Z]{2})?(@[a-z]+)?$")
    # ISO 3166-1 alpha-2 country code
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    # IANA timezone, e.g. "Europe/Istanbul" (validated against Odoo's list at runtime)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    # ISO 4217 currency code, e.g. "TRY"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class DatabaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    install: list[str] = Field(default_factory=list)
    allow_untested: bool = False
    defaults: DatabaseDefaults | None = None


class StackSpec(BaseModel):
    """Root of odoo-stack.toml."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=INSTANCE_NAME_PATTERN)
    dir: Path | None = None
    image: str | None = None
    pg_tag: int | None = None
    http_port: int | None = Field(default=None, ge=1, le=65535)
    admin_login: str = "admin"
    ingress: IngressSpec | None = None
    resources: ResourcesSpec | None = None
    settings: SettingsSpec | None = None
    repos: list[RepoSpec] = Field(default_factory=list)
    databases: dict[str, DatabaseSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> StackSpec:
        if self.http_port is not None and self.ingress is not None:
            raise ValueError(
                "http_port and [ingress] are mutually exclusive — ingress mode "
                "publishes no host port"
            )
        for db_name in self.databases:
            _validate_db_name(db_name)
        return self


def _validate_db_name(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise ValueError(
            f"invalid database name {name!r}: use lowercase letters, digits and "
            "_, starting with a letter (max 63 chars)"
        )


def repo_arg_from_url(url: str) -> str:
    """Normalize a GitHub URL (or an owner/repo shorthand) to `owner/repo`.

    The module machinery is GitHub/OCA-centric (D2): clone URLs, branch checks
    and raw-manifest probes are all built from owner/repo.
    """
    cleaned = url.strip().removesuffix(".git")
    if cleaned.startswith("https://github.com/"):
        cleaned = cleaned[len("https://github.com/") :]
    elif cleaned.startswith("git@github.com:"):
        cleaned = cleaned[len("git@github.com:") :]
    elif cleaned.startswith("http://") or cleaned.startswith("git@") or "://" in cleaned:
        raise StackError(
            f"unsupported repo url {url!r}: only GitHub repositories are supported "
            "(use owner/repo shorthand for OCA repos)"
        )
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) == 1:  # bare repo shorthand: OCA is the default owner
        parts.insert(0, "OCA")
    if len(parts) != 2 or not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0] + parts[1]):
        raise StackError(
            f"invalid repository {url!r}: expected owner/repo, "
            f"https://github.com/owner/repo[.git] (branch is always {ODOO_VERSION})"
        )
    return f"{parts[0]}/{parts[1]}"


def load_spec(path: Path) -> StackSpec:
    """Read and validate an odoo-stack.toml file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read stack spec {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in stack spec {path}: {exc}") from exc
    try:
        return StackSpec.model_validate(data)
    except ValueError as exc:
        raise ConfigError(f"invalid stack spec {path}: {exc}") from exc


def spec_to_extras(spec: StackSpec) -> StackExtras:
    return StackExtras(
        ingress_network=spec.ingress.network if spec.ingress else None,
        ingress_alias=spec.ingress.alias if spec.ingress else None,
        memory_limit=spec.resources.memory if spec.resources else None,
        cpus=spec.resources.cpus if spec.resources else None,
        proxy_mode=spec.settings.proxy_mode if spec.settings else None,
        list_db=spec.settings.list_db if spec.settings else None,
        workers=spec.settings.workers if spec.settings else None,
        max_cron_threads=spec.settings.max_cron_threads if spec.settings else None,
        limit_memory_soft=spec.settings.limit_memory_soft if spec.settings else None,
        limit_memory_hard=spec.settings.limit_memory_hard if spec.settings else None,
        odoo_login=spec.admin_login,
    )
