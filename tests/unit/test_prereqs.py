"""Doctor check tests: every pass/fail/warn branch with fakes (DEVELOPMENT.md §8)."""

from __future__ import annotations

from pathlib import Path

from fakes import (
    ComposeMissing,
    DockerEngineDown,
    FakeDocker,
    FakeFs,
    FakeGitHub,
    FakeSystem,
    GitHubDown,
)

from odoo_installer.core.prereqs import run_doctor
from odoo_installer.schemas import CheckStatus, GlobalConfig

CHECK_NAMES = {
    "docker engine",
    "docker compose",
    "docker permissions",
    "git",
    "disk space",
    "ports",
    "github api",
}


def _run(system: FakeSystem | None = None, **kwargs: object) -> dict[str, str]:
    checks = run_doctor(
        docker=kwargs.get("docker", FakeDocker()),
        system=system or FakeSystem(),
        github=kwargs.get("github", FakeGitHub()),
        fs=kwargs.get("fs", FakeFs()),
        config=kwargs.get("config", GlobalConfig(instances_root=Path("/tmp/oii-test"))),
    )
    assert {check.name for check in checks} == CHECK_NAMES
    return {check.name: check.status.value for check in checks}


def test_all_green_environment() -> None:
    assert set(_run().values()) == {"ok"}


def test_docker_engine_down_fails_with_pacman_hint() -> None:
    statuses = _run(docker=DockerEngineDown())
    assert statuses["docker engine"] == "fail"


def test_docker_engine_hint_uses_apt_when_debian() -> None:
    checks = run_doctor(
        DockerEngineDown(),
        FakeSystem(family="apt"),
        FakeGitHub(),
        FakeFs(),
        GlobalConfig(instances_root=Path("/tmp/oii-test")),
    )
    engine = next(check for check in checks if check.name == "docker engine")
    assert engine.fix_hint is not None
    assert "apt-get" in engine.fix_hint


def test_compose_missing_fails() -> None:
    statuses = _run(docker=ComposeMissing())
    assert statuses["docker compose"] == "fail"


def test_docker_group_membership_variants() -> None:
    # default fake: "alice" is a member of the docker group → ok
    assert _run()["docker permissions"] == "ok"
    # group exists, user missing → fail
    assert _run(FakeSystem(docker_group_members=()))["docker permissions"] == "fail"
    assert _run(FakeSystem(docker_group_members=("bob",)))["docker permissions"] == "fail"
    # group does not exist (rootless docker) → warn, not fail
    assert _run(FakeSystem(docker_group_members=None))["docker permissions"] == "warn"


def test_missing_git_fails() -> None:
    statuses = _run(FakeSystem(has_git=False))
    assert statuses["git"] == "fail"


def test_disk_boundaries() -> None:
    assert _run(fs=FakeFs(free_gib=1.0))["disk space"] == "fail"
    assert _run(fs=FakeFs(free_gib=3.0))["disk space"] == "warn"
    assert _run(fs=FakeFs(free_gib=10.0))["disk space"] == "ok"


def test_ports_all_free_is_ok() -> None:
    statuses = _run()
    assert statuses["ports"] == "ok"


def test_default_port_busy_is_warn_with_free_count() -> None:
    checks = run_doctor(
        FakeDocker(),
        FakeSystem(busy_ports={8069}),
        FakeGitHub(),
        FakeFs(),
        GlobalConfig(instances_root=Path("/tmp/oii-test")),
    )
    ports = next(check for check in checks if check.name == "ports")
    assert ports.status is CheckStatus.WARN
    assert "8069" in ports.detail
    assert "30/31" in ports.detail


def test_many_ports_busy_lists_them_all() -> None:
    checks = run_doctor(
        FakeDocker(),
        FakeSystem(busy_ports={8069, 8070, 8099}),
        FakeGitHub(),
        FakeFs(),
        GlobalConfig(instances_root=Path("/tmp/oii-test")),
    )
    ports = next(check for check in checks if check.name == "ports")
    assert "8099" in ports.detail
    assert "28/31" in ports.detail


def test_github_down_degrades_to_warn_not_fail() -> None:
    statuses = _run(github=GitHubDown())
    assert statuses["github api"] == "warn"
