"""Tests for the module test runner and the tested-addons whitelist."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker, FakeFs

from odoo_installer.core.tester import (
    drop_scratch_db,
    failure_kinds,
    run_module_test,
    scratch_db_name,
)

STACK = Path("/tmp/stack")


def test_scratch_db_name() -> None:
    assert scratch_db_name("web_responsive") == "oitest_web_responsive"


def test_run_module_test_pass() -> None:
    docker = FakeDocker(compose_result_results=[(0, "loading modules...\nall tests passed\n")])
    fs = FakeFs()
    logs_dir = Path("/tmp/stack/logs")
    outcome = run_module_test(docker, STACK, "web", "db", "odoo", fs, logs_dir, "web_responsive")
    assert outcome.passed is True
    assert outcome.exit_code == 0
    assert outcome.failures == []
    assert outcome.log_path is not None
    assert fs.read_text(outcome.log_path) is not None
    exec_args = next(
        args
        for args, _ in docker.compose_calls
        if args[0] == "exec" and "odoo" in args and "psql" not in args
    )
    assert "--test-enable" in exec_args
    assert "--test-tags=/web_responsive" in exec_args
    assert "-i" in exec_args and "web_responsive" in exec_args
    assert "--http-port=8071" in exec_args
    assert outcome.db == "oitest_web_responsive"


def test_run_module_test_failure_captures_failures() -> None:
    log = "Traceback below\nFAIL: test_responsive (odoo.addons.web_responsive.tests)\n"
    docker = FakeDocker(compose_result_results=[(1, log)])
    outcome = run_module_test(
        docker, STACK, "web", "db", "odoo", FakeFs(), Path("/tmp/stack/logs"), "web_responsive"
    )
    assert outcome.passed is False
    assert outcome.exit_code == 1
    assert outcome.failures == ["FAIL: test_responsive (odoo.addons.web_responsive.tests)"]


def test_run_module_test_drops_existing_scratch_db_first() -> None:
    docker = FakeDocker(
        compose_results=["1", "", ""],  # exists-check: hit, then terminate, then drop
        compose_result_results=[(0, "ok")],
    )
    run_module_test(docker, STACK, "web", "db", "odoo", FakeFs(), Path("/tmp/l"), "mod_x")
    sqls = [" ".join(args) for args, _ in docker.compose_calls if args[0] == "exec"]
    assert "SELECT 1 FROM pg_database WHERE datname = 'oitest_mod_x'" in sqls[0]
    assert "pg_terminate_backend" in sqls[1]
    assert 'DROP DATABASE IF EXISTS "oitest_mod_x"' in sqls[2]


def test_run_module_test_skips_drop_when_scratch_absent() -> None:
    docker = FakeDocker(compose_results=[""], compose_result_results=[(0, "ok")])
    run_module_test(docker, STACK, "web", "db", "odoo", FakeFs(), Path("/tmp/l"), "mod_x")
    sqls = [" ".join(args) for args, _ in docker.compose_calls if "psql" in args]
    assert len(sqls) == 1  # only the exists-check ran


def test_drop_scratch_db_helper() -> None:
    docker = FakeDocker(compose_results=["1", "", ""])
    assert drop_scratch_db(docker, STACK, "db", "odoo", "mod_y") is True
    docker = FakeDocker(compose_results=[""])
    assert drop_scratch_db(docker, STACK, "db", "odoo", "mod_y") is False


# --- failure-kind parsing against recorded-style fixture logs ----------------

PASS_LOG = (
    "2026-08-31 18:16:59 INFO oitest odoo.tests.common: Importing test framework\n"
    "2026-08-31 18:17:11 INFO oitest odoo.modules.loading: Loading module web_responsive (25/28)\n"
    "2026-08-31 18:17:13 INFO oitest odoo.modules.loading: Modules loaded.\n"
)

TEST_FAILURE_LOG = (
    "2026-08-31 INFO odoo.tests: Starting TestThing.test_a\n"
    "FAIL: test_a (odoo.addons.mod_x.tests.test_thing)\n"
    "Traceback (most recent call last):\n"
    '  File "x.py", line 1, in test_a\n'
    "AssertionError: not equal\n"
    "FAIL: test_b (odoo.addons.mod_x.tests.test_thing)\n"
)

IMPORT_ERROR_LOG = (
    "2026-08-31 ERROR odoo.modules.module: Couldn't load module mod_x\n"
    "ModuleNotFoundError: No module named 'missing_dep'\n"
)

NOT_INSTALLABLE_LOG = (
    "WARNING odoo.modules.graph: module mod_x: not installable, skipped\n"
    "ERROR odoo.modules.loading: Some modules are not loadable: ['mod_x']\n"
)

ADDONS_PATH_LOG = (
    "WARNING odoo.tools.config: option addons_path, invalid addons directory "
    "'/mnt/ghost', skipped\n"
)

MANIFEST_LOG = "ERROR odoo.modules.module: Missing manifest file for module mod_x\n"


def test_failure_kinds_pass_log_is_clean() -> None:
    assert failure_kinds(PASS_LOG, 0) == []


def test_failure_kinds_test_failure() -> None:
    kinds = failure_kinds(TEST_FAILURE_LOG, 1)
    assert "test_failure" in kinds
    assert "traceback" in kinds


def test_failure_kinds_import_error() -> None:
    assert "import_error" in failure_kinds(IMPORT_ERROR_LOG, 1)


def test_failure_kinds_not_installable() -> None:
    assert "not_installable" in failure_kinds(NOT_INSTALLABLE_LOG, 1)


def test_failure_kinds_addons_path_warning() -> None:
    assert "addons_path" in failure_kinds(ADDONS_PATH_LOG, 0)


def test_failure_kinds_missing_manifest() -> None:
    assert "manifest" in failure_kinds(MANIFEST_LOG, 1)


def test_failure_kinds_bare_exit_code() -> None:
    assert failure_kinds("something odd happened", 1) == ["exit_code"]


def test_run_module_test_records_kinds() -> None:
    docker = FakeDocker(compose_result_results=[(1, TEST_FAILURE_LOG)])
    outcome = run_module_test(docker, STACK, "web", "db", "odoo", FakeFs(), Path("/tmp/l"), "mod_x")
    assert outcome.passed is False
    assert "test_failure" in outcome.kinds
