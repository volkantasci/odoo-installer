"""Rendering of the generated stack files (compose, .env, odoo.conf) and .env parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import jinja2

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass(frozen=True)
class StackParams:
    """Everything the templates need; secrets are resolved by the caller."""

    name: str
    odoo_image: str
    pg_tag: int
    http_port: int
    pg_password: str
    admin_passwd: str


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
        )
    )


def odoo_conf(params: StackParams) -> str:
    return (
        _environment()
        .get_template("odoo.conf.j2")
        .render(
            admin_passwd=params.admin_passwd,
            pg_password=params.pg_password,
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
