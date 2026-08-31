"""Tests for stack file rendering (compose, .env, odoo.conf)."""

from __future__ import annotations

from odoo_installer.core.stack import (
    StackParams,
    compose_yaml,
    env_file,
    odoo_conf,
    parse_env,
)

PARAMS = StackParams(
    name="dev",
    odoo_image="odoo:19.0",
    pg_tag=17,
    http_port=8070,
    pg_password="pgsecret",
    admin_passwd="adminsecret",
)


def test_compose_yaml_maps_host_port_and_images() -> None:
    content = compose_yaml(PARAMS)
    assert '"8070:8069"' in content
    assert "image: odoo:19.0" in content
    assert "image: postgres:17" in content


def test_compose_yaml_uses_healthchecks_and_interpolation() -> None:
    content = compose_yaml(PARAMS)
    assert "curl -f http://localhost:8069/web/health" in content
    assert "pg_isready -U odoo" in content
    # secrets go through compose interpolation, never literally into the compose file
    assert "${POSTGRES_PASSWORD}" in content
    assert "pgsecret" not in content


def test_compose_yaml_mounts_local_addons() -> None:
    content = compose_yaml(PARAMS)
    assert "./config:/etc/odoo" in content
    assert "./addons/local:/mnt/extra-addons" in content


def test_env_file_binds_project_name_and_secrets() -> None:
    content = env_file(PARAMS)
    assert "COMPOSE_PROJECT_NAME=dev" in content
    assert "HTTP_PORT=8070" in content
    assert "POSTGRES_PASSWORD=pgsecret" in content


def test_odoo_conf_has_addons_path_and_master_password() -> None:
    content = odoo_conf(PARAMS)
    assert "addons_path = /mnt/extra-addons" in content
    assert "admin_passwd = adminsecret" in content
    assert "db_host = db" in content
    assert "db_password = pgsecret" in content


def test_parse_env_ignores_comments_blanks_and_invalid_lines() -> None:
    assert parse_env("# comment\nA=1\n\nB = two\nBAD\n") == {"A": "1", "B": "two"}
    assert parse_env("") == {}
