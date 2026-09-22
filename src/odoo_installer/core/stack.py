"""Rendering of the generated stack files (compose, .env, odoo.conf) and .env parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import jinja2

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass(frozen=True)
class StackParams:
    """Everything the templates need; secrets are resolved by the caller.

    Fields beyond the classic five are optional (None/False defaults render the
    same files as before), so existing callers and golden tests stay valid.
    Ingress mode (network set, no published port) is how stacks attach to a
    shared reverse-proxy network without exposing host ports.
    """

    name: str
    odoo_image: str
    pg_tag: int
    http_port: int  # 0 = unpublished (ingress mode)
    pg_password: str
    admin_passwd: str
    ingress_network: str | None = None
    ingress_alias: str | None = None
    memory_limit: str | None = None  # compose mem_limit, e.g. "2g"
    cpus: float | None = None
    proxy_mode: bool = False
    list_db: bool = True
    workers: int | None = None
    odoo_login: str = "admin"
    odoo_password: str = ""


def _environment() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=jinja2.StrictUndefined,
    )


def compose_yaml(params: StackParams) -> str:
    return (
        _environment()
        .get_template("docker-compose.yml.j2")
        .render(
            name=params.name,
            odoo_image=params.odoo_image,
            pg_tag=params.pg_tag,
            http_port=params.http_port,
            ingress_network=params.ingress_network,
            ingress_alias=params.ingress_alias or params.name,
            memory_limit=params.memory_limit,
            cpus=params.cpus,
        )
    )


def env_file(params: StackParams) -> str:
    return (
        _environment()
        .get_template(".env.j2")
        .render(
            name=params.name,
            odoo_image=params.odoo_image,
            pg_tag=params.pg_tag,
            http_port=params.http_port,
            pg_password=params.pg_password,
            admin_passwd=params.admin_passwd,
            odoo_login=params.odoo_login,
            odoo_password=params.odoo_password,
        )
    )


def odoo_conf(params: StackParams) -> str:
    return (
        _environment()
        .get_template("odoo.conf.j2")
        .render(
            admin_passwd=params.admin_passwd,
            pg_password=params.pg_password,
            proxy_mode=params.proxy_mode,
            list_db=params.list_db,
            workers=params.workers,
        )
    )


def parse_env(content: str) -> dict[str, str]:
    """Parse a dotenv-style file (KEY=VALUE lines, # comments ignored)."""
    values: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values
