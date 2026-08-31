"""Tests for db management core: psql SQL generation and safety guards."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker

from odoo_installer.core.dbms import (
    create_database,
    drop_database_plan,
    list_databases,
    module_states,
    reset_database_plan,
    validate_db_name,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import StackError

STACK = Path("/tmp/stack")


def recorded_sql(docker: FakeDocker) -> list[str]:
    return [" ".join(args) for args, _ in docker.compose_calls]


def test_validate_db_name() -> None:
    assert validate_db_name("my_db01") == "my_db01"
    for bad in ("1bad", "with-dash", "UPPER", "has space", "x" * 64, ""):
        with pytest.raises(StackError, match="invalid database name"):
            validate_db_name(bad)


def test_list_databases_parses_psql_rows() -> None:
    docker = FakeDocker(compose_results=["odoo|100 MB\npostgres|7 MB\noitest_db|16 kB\n"])
    databases = list_databases(docker, STACK, "db", "odoo")
    assert [db.name for db in databases] == ["odoo", "postgres", "oitest_db"]
    assert databases[0].size == "100 MB"
    sql = recorded_sql(docker)[0]
    assert "pg_database" in sql and "psql -U odoo" in sql


def test_create_database_creates_when_missing() -> None:
    docker = FakeDocker(compose_results=["", ""])  # exists-check empty, then CREATE
    note = create_database(docker, STACK, "db", "odoo", "newdb")
    assert note == "created"
    sqls = recorded_sql(docker)
    assert any("SELECT 1 FROM pg_database WHERE datname = 'newdb'" in s for s in sqls)
    assert any('CREATE DATABASE "newdb"' in s for s in sqls)


def test_create_database_is_idempotent() -> None:
    docker = FakeDocker(compose_results=["1"])  # exists-check hits
    note = create_database(docker, STACK, "db", "odoo", "newdb")
    assert note == "already exists"
    assert len(recorded_sql(docker)) == 1  # no CREATE attempted


def test_drop_plan_refuses_protected_databases() -> None:
    docker = FakeDocker()
    for name in ("postgres", "template0", "template1"):
        with pytest.raises(StackError, match="protected"):
            drop_database_plan(docker, STACK, "db", "odoo", name)
    assert docker.compose_calls == []  # nothing executed


def test_drop_plan_terminates_connections_then_drops() -> None:
    docker = FakeDocker(compose_results=["", ""])
    steps = drop_database_plan(docker, STACK, "db", "odoo", "scratch")
    notes = apply_steps(steps)
    assert notes == ["no active connections", "dropped"]
    sqls = recorded_sql(docker)
    assert "pg_terminate_backend" in sqls[0]
    assert "datname = 'scratch'" in sqls[0]
    assert 'DROP DATABASE IF EXISTS "scratch"' in sqls[1]


def test_reset_plan_adds_create() -> None:
    docker = FakeDocker(compose_results=["", "", ""])
    steps = reset_database_plan(docker, STACK, "db", "odoo", "scratch")
    assert len(steps) == 3
    apply_steps(steps)
    sqls = recorded_sql(docker)
    assert 'CREATE DATABASE "scratch"' in sqls[2]


def test_module_states_rejects_invalid_names() -> None:
    with pytest.raises(StackError, match="invalid module name"):
        module_states(FakeDocker(), STACK, "db", "odoo", "d", ["bad;name"])


def test_module_states_skips_blank_lines_and_returns_empty_for_no_names() -> None:
    docker = FakeDocker(compose_results=["\nfoo|installed\n\n"])
    assert module_states(docker, STACK, "db", "odoo", "d", ["foo"]) == {"foo": "installed"}
    assert module_states(FakeDocker(), STACK, "db", "odoo", "d", []) == {}
