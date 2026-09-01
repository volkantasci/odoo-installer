"""Tests for the central whitelist repo (test pull) and registry merging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fakes import FakeFs, FakeGit

from odoo_installer.config import load_tested_registry
from odoo_installer.core import tested as tested_core
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import OdooInstallerError
from odoo_installer.schemas import TestedModule, TestedRegistry

REPO_TOML = """
[modules.web_responsive]
name = "web_responsive"
repo = "OCA/web"
branch = "19.0"
commit = "d4bfccf526ab7519de75db4e8d9dd3d247cf45d5"
tested_at = "2026-09-01T12:12:40Z"
db = "odoo"
log_path = ""

[modules.pim]
name = "pim"
repo = "local"
branch = "19.0"
commit = ""
tested_at = "2026-09-01T12:20:00Z"
db = "odoo"
log_path = ""
"""


class WhitelistRepoGit(FakeGit):
    """A FakeGit whose clone materializes a tested.toml at the repo root."""

    def __init__(self, *, content: str = REPO_TOML, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._content = content

    def clone(
        self, url: str, path: Path, branch: str | None = None, depth: int | None = None
    ) -> str:
        note = super().clone(url, path, branch=branch, depth=depth)
        (Path(path) / "tested.toml").write_text(self._content, encoding="utf-8")
        return note


def _module(name: str, when: datetime, repo: str = "OCA/web") -> TestedModule:
    return TestedModule(name=name, repo=repo, branch="19.0", tested_at=when, db="odoo")


# --- merge semantics ----------------------------------------------------------


def test_merge_adds_new_modules() -> None:
    base = datetime.now(UTC)
    local = TestedRegistry(modules={"a": _module("a", base)})
    incoming = TestedRegistry(modules={"b": _module("b", base)})
    merged, added, updated = tested_core.merge_tested_registries(local, incoming)
    assert set(merged.modules) == {"a", "b"}
    assert (added, updated) == (1, 0)


def test_merge_keeps_newer_on_clash() -> None:
    now = datetime.now(UTC)
    local = TestedRegistry(modules={"m": _module("m", now)})
    incoming = TestedRegistry(modules={"m": _module("m", now + timedelta(hours=1))})
    merged, added, updated = tested_core.merge_tested_registries(local, incoming)
    assert merged.modules["m"].tested_at > now
    assert (added, updated) == (0, 1)

    older = TestedRegistry(modules={"m": _module("m", now - timedelta(hours=1))})
    merged2, added2, updated2 = tested_core.merge_tested_registries(local, older)
    assert merged2.modules["m"].tested_at == now
    assert (added2, updated2) == (0, 0)


# --- pull plan ----------------------------------------------------------------


def test_pull_plan_merges_into_active_whitelist(tmp_path: Path, monkeypatch) -> None:
    active = tmp_path / "tested.toml"
    local = TestedRegistry(modules={"m": _module("m", datetime.now(UTC), repo="local")})
    import tomli_w

    active.write_text(tomli_w.dumps(local.model_dump(mode="json")), encoding="utf-8")
    plan = tested_core.tested_pull_plan(
        url="https://github.com/volkantasci/odoo-installer-tested.git",
        git=WhitelistRepoGit(),
        fs=FakeFs(),
        active_path=active,
    )
    apply_steps(plan.steps)
    merged = load_tested_registry(active)
    assert set(merged.modules) == {"m", "web_responsive", "pim"}
    assert plan.summary["added"] == 2 and plan.summary["updated"] == 0


def test_pull_plan_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    active = tmp_path / "tested.toml"
    before = active.read_text(encoding="utf-8") if active.exists() else None
    plan = tested_core.tested_pull_plan(
        url="https://example.com/whitelist.git",
        git=WhitelistRepoGit(),
        fs=FakeFs(),
        active_path=active,
    )
    # a dry run only renders: apply_steps is not invoked here by design
    assert len(plan.steps) == 2
    after = active.read_text(encoding="utf-8") if active.exists() else None
    assert before == after


def test_pull_plan_requires_tested_toml_in_repo(tmp_path: Path) -> None:
    active = tmp_path / "tested.toml"
    plan = tested_core.tested_pull_plan(
        url="https://example.com/not-a-whitelist.git",
        git=FakeGit(),
        fs=FakeFs(),
        active_path=active,
    )
    with pytest.raises(OdooInstallerError, match=r"no tested\.toml"):
        apply_steps(plan.steps)
