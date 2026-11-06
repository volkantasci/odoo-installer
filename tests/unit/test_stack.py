"""Tests for stack file rendering (compose, .env, odoo.conf)."""

from __future__ import annotations

from odoo_installer.core.stack import (
    StackParams,
    compose_yaml,
    env_file,
    memory_bytes,
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


def test_compose_yaml_filestore_is_a_named_volume() -> None:
    content = compose_yaml(PARAMS)
    # named volume (not an anonymous image volume): survives plain `down`,
    # removed by `down -v`, and reachable for exec-based backup streams
    assert "- filestore:/var/lib/odoo" in content
    assert "filestore:" in content.split("volumes:")[1]


def test_compose_yaml_ingress_mode_publishes_no_port() -> None:
    ingress = compose_yaml(
        StackParams(
            name="acme",
            odoo_image="odoo:19.0",
            pg_tag=17,
            http_port=0,
            pg_password="pgsecret",
            admin_passwd="adminsecret",
            ingress_network="violetear-ingress",
            ingress_alias="acme",
        )
    )
    assert "ports:" not in ingress
    assert "aliases:" in ingress
    assert "- acme" in ingress
    assert "external: true" in ingress
    assert "name: violetear-ingress" in ingress
    # web keeps the default network too (it must reach db); db never joins ingress
    assert "default: {}" in ingress
    services_section = ingress.split("\nvolumes:")[0]
    db_block = services_section.split("\n  db:")[1]
    assert "ingress" not in db_block


def test_compose_yaml_resource_limits() -> None:
    limited = compose_yaml(
        StackParams(
            name="acme",
            odoo_image="odoo:19.0",
            pg_tag=17,
            http_port=8069,
            pg_password="pgsecret",
            admin_passwd="adminsecret",
            memory_limit="2g",
            cpus=1.5,
        )
    )
    assert "mem_limit: 2g" in limited
    assert "cpus: 1.5" in limited


def test_odoo_conf_workers_and_flags() -> None:
    tuned = odoo_conf(
        StackParams(
            name="acme",
            odoo_image="odoo:19.0",
            pg_tag=17,
            http_port=0,
            pg_password="pgsecret",
            admin_passwd="adminsecret",
            proxy_mode=True,
            list_db=False,
            workers=4,
        )
    )
    lines = [line for line in tuned.splitlines() if line.strip()]
    assert "proxy_mode = True" in lines  # line-exact: never glued to another key
    assert "list_db = False" in lines
    assert "workers = 4" in lines
    # default PARAMS keep the classic values
    classic = odoo_conf(PARAMS)
    assert "proxy_mode = False" in classic.splitlines()
    assert "list_db = True" in classic.splitlines()
    assert "workers" not in classic


def test_env_file_carries_odoo_admin_credentials() -> None:
    content = env_file(
        StackParams(
            name="acme",
            odoo_image="odoo:19.0",
            pg_tag=17,
            http_port=8069,
            pg_password="pgsecret",
            admin_passwd="adminsecret",
            odoo_login="admin",
            odoo_password="odoosecret",
        )
    )
    assert "ODOO_ADMIN_LOGIN=admin" in content
    assert "ODOO_ADMIN_PASSWORD=odoosecret" in content


def test_memory_bytes_units() -> None:
    assert memory_bytes("512") == 512
    assert memory_bytes("1k") == 1024
    assert memory_bytes("1536m") == 1610612736
    assert memory_bytes("2g") == 2147483648


def test_odoo_conf_cron_and_memory_knobs_one_per_line() -> None:
    conf = odoo_conf(
        StackParams(
            name="acme",
            odoo_image="odoo:19.0",
            pg_tag=17,
            http_port=0,
            pg_password="p",
            admin_passwd="a",
            workers=1,
            max_cron_threads=1,
            limit_memory_soft=memory_bytes("1536m"),
            limit_memory_hard=memory_bytes("2g"),
        )
    )
    lines = conf.splitlines()
    assert "workers = 1" in lines
    assert "max_cron_threads = 1" in lines
    assert "limit_memory_soft = 1610612736" in lines
    assert "limit_memory_hard = 2147483648" in lines
    classic = odoo_conf(PARAMS)
    assert "max_cron_threads" not in classic and "limit_memory" not in classic
