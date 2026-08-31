"""CLI tests for the `test` sub-app (deps patched, fully offline).

Suite flow per module (no --keep-db): psql pre/post-drop SELECTs go through
`compose()`, the odoo test run goes through `compose_result()`. The default
FakeDocker returns (0, "compose ... ok") for every call, which is a PASS.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.schemas import GlobalConfig, InstanceManifest

runner = CliRunner()

MODULE = "server_util_foo"
REPO = "OCA/server-utils"


def make_container(tmp_path: Path, docker: FakeDocker | None = None) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances", repo_root=tmp_path / "repos"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        docker=docker or FakeDocker(),
        git=FakeGit(sample_modules=(MODULE,)),
        system=FakeSystem(),
        github=FakeGitHub(),
        fs=FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def prepared_instance(
    tmp_path: Path, patch_deps, docker: FakeDocker | None = None
) -> tuple[Container, InstanceManifest]:
    container = make_container(tmp_path, docker)
    patch_deps(container)
    created = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert created.exit_code == 0, created.output
    added = runner.invoke(app, ["module", "add", "server-utils", "--apply"])
    assert added.exit_code == 0, added.output
    manifest = InstanceManifest.model_validate_json(
        (tmp_path / "instances" / "dev" / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    return container, manifest


def test_suite_all_modules_pass(patch_deps, tmp_path: Path) -> None:
    container, manifest = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["test", "suite"])
    assert result.exit_code == 0, result.output
    assert MODULE in result.output
    assert "PASS" in result.output
    # odoo test run happened against the scratch db with the runner port
    odoo_calls = [
        args
        for args, _ in container.docker.compose_calls
        if "odoo" in args and "-i" in args and "--test-enable" in args
    ]
    assert len(odoo_calls) == 1
    assert any(a.startswith("--http-port=") for a in odoo_calls[0])
    assert f"-d oitest_{MODULE}" in " ".join(odoo_calls[0])
    # log captured under the stack logs dir
    logs = list((manifest.dir / "logs").glob(f"test-{MODULE}-*.log"))
    assert logs, "test log not written"
    # PASS recorded in the whitelist with provenance
    data = tomllib.loads((tmp_path / "tested.toml").read_text(encoding="utf-8"))
    entry = data["modules"][MODULE]
    assert entry["repo"] == REPO
    assert entry["branch"] == "19.0"
    assert entry["commit"]
    # scratch db dropped after the run: 2 SELECTs + 1 odoo run per module
    assert len(container.docker.compose_calls) >= 3


def test_suite_writes_md_and_json_reports(patch_deps, tmp_path: Path) -> None:
    _, _manifest = prepared_instance(tmp_path, patch_deps)
    md_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    result = runner.invoke(
        app, ["test", "suite", "--output", str(md_path), "--output", str(json_path)]
    )
    assert result.exit_code == 0, result.output
    assert md_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["instance"] == "dev"
    assert payload["total"] == 1 and payload["passed"] == 1 and payload["failed"] == 0
    assert payload["results"][0]["module"] == MODULE
    md = md_path.read_text(encoding="utf-8")
    assert f"| {MODULE} | PASS |" in md


def test_suite_failure_exit_3_and_kinds(patch_deps, tmp_path: Path) -> None:
    container, _manifest = prepared_instance(tmp_path, patch_deps)
    # Queue AFTER setup (setup consumes compose_result calls too). Only the odoo
    # test run uses compose_result — psql SELECTs go through compose(), so a
    # single item is enough: it lands on the odoo run.
    container.docker.compose_result_results = [(1, "FAIL: test_check_failed")]
    result = runner.invoke(app, ["test", "suite"])
    assert result.exit_code == 3, result.output
    assert "FAIL" in result.output
    json_path = tmp_path / "fail.json"
    container.docker.compose_result_results = [(1, "FAIL: test_check_failed")]
    result2 = runner.invoke(app, ["test", "suite", "--output", str(json_path)])
    assert result2.exit_code == 3
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["failed"] == 1
    assert "test_failure" in payload["results"][0]["kinds"]


def test_suite_keep_db_skips_post_drop(patch_deps, tmp_path: Path) -> None:
    container, _manifest = prepared_instance(tmp_path, patch_deps)
    before = len(container.docker.compose_calls)
    result = runner.invoke(app, ["test", "suite", "--keep-db"])
    assert result.exit_code == 0, result.output
    # 1 odoo run + 1 pre-drop SELECT (post-drop skipped)
    assert len(container.docker.compose_calls) - before == 2


def test_suite_only_filters_by_repo(patch_deps, tmp_path: Path) -> None:
    _, _manifest = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["test", "suite", "--only", "server-utils"])
    assert result.exit_code == 0, result.output
    assert MODULE in result.output
    empty = runner.invoke(app, ["test", "suite", "--only", "web"])
    assert empty.exit_code == 0, empty.output
    assert "nothing to test" in empty.output


def test_suite_modules_explicit_list(patch_deps, tmp_path: Path) -> None:
    _, _manifest = prepared_instance(tmp_path, patch_deps)
    result = runner.invoke(app, ["test", "suite", "--modules", MODULE])
    assert result.exit_code == 0, result.output
    missing = runner.invoke(app, ["test", "suite", "--modules", "ghost_module"])
    assert missing.exit_code == 1, missing.output
    assert "not visible" in missing.output


def test_suite_bad_report_suffix_exits_1(patch_deps, tmp_path: Path) -> None:
    _, _manifest = prepared_instance(tmp_path, patch_deps)
    bad = tmp_path / "report.txt"
    result = runner.invoke(app, ["test", "suite", "--output", str(bad)])
    assert result.exit_code == 1, result.output
    assert ".md or .json" in result.output
    assert not bad.exists()
