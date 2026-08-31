"""Scratch-database test runs for single modules (DEVELOPMENT.md §2 `module test`).

A test run installs the module on a throwaway `oitest_<module>` database with
`--test-enable --test-tags /<module>`, captures the full log, and derives PASS/FAIL
from the exit code plus unittest result lines. PASS is what feeds the installable
addons whitelist (tested.toml).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.constants import RUNNER_HTTP_PORT, SCRATCH_DB_PREFIX
from odoo_installer.core.dbms import execute_sql

_FAILURE_PATTERN = re.compile(r"^(FAIL|ERROR): (.+)$")

# Failure classes proven against recorded fixture logs (DEVELOPMENT.md §8):
# test_failure, import_error, not_installable, addons_path, manifest, traceback, exit_code
_KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("test_failure", re.compile(r"^(FAIL|ERROR): ", re.M)),
    ("import_error", re.compile(r"^(ImportError|ModuleNotFoundError): ", re.M)),
    ("not_installable", re.compile(r"not installable|Unable to install module")),
    ("addons_path", re.compile(r"invalid addons directory|option addons_path")),
    (
        "manifest",
        re.compile(
            r"[Mm]anifest file .{0,60}(not found|missing)|no manifest found|[Mm]issing [Mm]anifest"
        ),
    ),
    ("traceback", re.compile(r"^Traceback \(most recent call last\)", re.M)),
]


def failure_kinds(output: str, exit_code: int) -> list[str]:
    """Classify a test log into failure kinds; empty list means a clean run."""
    kinds = [name for name, pattern in _KIND_PATTERNS if pattern.search(output)]
    if exit_code != 0 and not kinds:
        kinds.append("exit_code")
    return kinds


@dataclass
class TestOutcome:
    module: str
    db: str
    passed: bool
    exit_code: int
    failures: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    log_path: Path | None = None
    duration_s: float = 0.0


def scratch_db_name(module: str) -> str:
    return f"{SCRATCH_DB_PREFIX}_{module}"


def _drop_scratch_db(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, db: str
) -> None:
    exists = execute_sql(
        docker,
        stack_dir,
        db_service,
        db_user,
        "postgres",
        f"SELECT 1 FROM pg_database WHERE datname = '{db}'",
    )
    if exists.strip() != "1":
        return
    execute_sql(
        docker,
        stack_dir,
        db_service,
        db_user,
        "postgres",
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{db}' AND pid <> pg_backend_pid()",
    )
    execute_sql(
        docker, stack_dir, db_service, db_user, "postgres", f'DROP DATABASE IF EXISTS "{db}"'
    )


def drop_scratch_db(
    docker: DockerLike, stack_dir: Path, db_service: str, db_user: str, module: str
) -> bool:
    """Drop the module's scratch database; returns True when it existed."""
    db = scratch_db_name(module)
    exists = execute_sql(
        docker,
        stack_dir,
        db_service,
        db_user,
        "postgres",
        f"SELECT 1 FROM pg_database WHERE datname = '{db}'",
    )
    if exists.strip() != "1":
        return False
    _drop_scratch_db(docker, stack_dir, db_service, db_user, db)
    return True


def run_module_test(
    docker: DockerLike,
    stack_dir: Path,
    web_service: str,
    db_service: str,
    db_user: str,
    fs: FileSystemLike,
    logs_dir: Path,
    module: str,
    *,
    timeout_s: int = 1800,
) -> TestOutcome:
    """Install `module` on a fresh scratch DB and run its tests. Never raises for
    test failures — the outcome object carries the verdict."""
    db = scratch_db_name(module)
    _drop_scratch_db(docker, stack_dir, db_service, db_user, db)

    started = time.monotonic()
    exit_code, output = docker.compose_result(
        [
            "exec",
            "-T",
            web_service,
            "odoo",
            "-d",
            db,
            "-i",
            module,
            "--test-enable",
            f"--test-tags=/{module}",
            "--stop-after-init",
            f"--http-port={RUNNER_HTTP_PORT}",
        ],
        stack_dir,
        timeout_s=timeout_s,
    )
    duration = time.monotonic() - started

    failures = [
        match.group(0) for line in output.splitlines() if (match := _FAILURE_PATTERN.match(line))
    ]
    log_path: Path | None = None
    if output.strip():
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        log_path = logs_dir / f"test-{module}-{stamp}.log"
        fs.write_text(log_path, output)
    return TestOutcome(
        module=module,
        db=db,
        passed=exit_code == 0 and not failures,
        exit_code=exit_code,
        failures=failures,
        kinds=[] if exit_code == 0 and not failures else failure_kinds(output, exit_code),
        log_path=log_path,
        duration_s=duration,
    )
