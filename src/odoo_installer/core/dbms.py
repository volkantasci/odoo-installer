"""Database management inside an instance's db container (psql via compose exec).

Safety (DEVELOPMENT.md §7): database names are always explicit CLI arguments, never
defaults; protected databases refuse to be dropped; drop/reset are plan-first and
execute only with `--apply --yes`. Names are validated to `[a-z][a-z0-9_]*` before
they are ever interpolated into SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.core.plan import Step
from odoo_installer.exceptions import StackError

DB_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"
PROTECTED_DATABASES = {"postgres", "template0", "template1"}


@dataclass
class DatabaseInfo:
    name: str
    size: str


def validate_db_name(name: str) -> str:
    if not re.fullmatch(DB_NAME_PATTERN, name):
        raise StackError(
            f"invalid database name {name!r}: use lowercase letters, digits and "
            "_, starting with a letter (max 63 chars)"
        )
    return name


def _psql_exec(docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, sql: str) -> str:
    return docker.compose(
        ["exec", "-T", db_service, "psql", "-U", db_user, "-d", "postgres", "-At", "-c", sql],
        stack_dir,
    )


def list_databases(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str
) -> list[DatabaseInfo]:
    sql = (
        "SELECT datname, pg_size_pretty(pg_database_size(datname)) "
        "FROM pg_database WHERE NOT datistemplate ORDER BY datname"
    )
    out = _psql_exec(docker, stack_dir, db_service, db_user, sql)
    databases: list[DatabaseInfo] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        name, _, size = line.partition("|")
        databases.append(DatabaseInfo(name=name.strip(), size=size.strip()))
    return databases


def create_database(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, name: str
) -> str:
    validate_db_name(name)
    exists = _psql_exec(
        docker,
        stack_dir,
        db_service,
        db_user,
        f"SELECT 1 FROM pg_database WHERE datname = '{name}'",
    )
    if exists.strip() == "1":
        return "already exists"
    _psql_exec(docker, stack_dir, db_service, db_user, f'CREATE DATABASE "{name}"')
    return "created"


def drop_database_plan(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, name: str
) -> list[Step]:
    validate_db_name(name)
    if name in PROTECTED_DATABASES:
        raise StackError(f"refusing to drop protected database {name!r}")

    def terminate() -> str:
        return (
            _psql_exec(
                docker,
                stack_dir,
                db_service,
                db_user,
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{name}' AND pid <> pg_backend_pid()",
            )
            or "no active connections"
        )

    def drop() -> str:
        _psql_exec(docker, stack_dir, db_service, db_user, f'DROP DATABASE IF EXISTS "{name}"')
        return "dropped"

    return [
        Step(description=f"terminate active connections to {name!r}", run=terminate),
        Step(description=f'DROP DATABASE IF EXISTS "{name}"', run=drop),
    ]


def reset_database_plan(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, name: str
) -> list[Step]:
    steps = drop_database_plan(docker, stack_dir, db_service, db_user, name)

    def create() -> str:
        _psql_exec(docker, stack_dir, db_service, db_user, f'CREATE DATABASE "{name}"')
        return "recreated (empty)"

    steps.append(Step(description=f'CREATE DATABASE "{name}"', run=create))
    return steps
