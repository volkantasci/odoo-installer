"""Doctor check tests: every pass/fail/warn branch with fakes (DEVELOPMENT.md §8)."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker, FakeFs, FakeGitHub, FakeSystem, GitHubDown

from odoo_installer.core.prereqs import PODMAN_RESTART_SERVICE, host_install_plan, run_doctor
from odoo_installer.schemas import CheckStatus, GlobalConfig

CHECK_NAMES = {
    "container runtime",
    "compose",
    "runtime permissions",
    "git",
    "disk space",
    "ports",
    "github api",
}

PODMAN_CHECK_NAMES = CHECK_NAMES | {"linger (boot survival)", "podman boot restart"}


def _run(system: FakeSystem | None = None, **kwargs: object) -> dict[str, str]:
    docker = kwargs.get("docker", FakeDocker())
    assert isinstance(docker, FakeDocker)
    if "fs" in kwargs:
        fs = kwargs["fs"]
    else:
        fs = FakeFs()
        if docker.runtime == "podman":
            # pretend the default rootless socket is listening (the missing-socket
            # branch passes its own FakeFs without this)
            fs.remember(Path(FakeDocker.DEFAULT_PODMAN_SOCKET.removeprefix("unix://")))
    checks = run_doctor(
        docker=docker,
        system=system or FakeSystem(),
        github=kwargs.get("github", FakeGitHub()),
        fs=fs,
        config=kwargs.get("config", GlobalConfig(instances_root=Path("/tmp/oii-test"))),
    )
    expected = PODMAN_CHECK_NAMES if docker.runtime == "podman" else CHECK_NAMES
    assert {check.name for check in checks} == expected
    return {check.name: check.status.value for check in checks}


def _podman_docker() -> FakeDocker:
    return FakeDocker(runtime="podman", engine_version="6.1.1")


def test_all_green_environment() -> None:
    assert set(_run().values()) == {"ok"}


def test_runtime_down_fails_with_pacman_hint() -> None:
    statuses = _run(docker=FakeDocker(engine_error="engine down"))
    assert statuses["container runtime"] == "fail"


def test_runtime_hint_uses_apt_when_debian() -> None:
    checks = run_doctor(
        FakeDocker(engine_error="engine down"),
        FakeSystem(family="apt"),
        FakeGitHub(),
        FakeFs(),
        GlobalConfig(instances_root=Path("/tmp/oii-test")),
    )
    engine = next(check for check in checks if check.name == "container runtime")
    assert engine.fix_hint is not None
    assert "apt-get" in engine.fix_hint


def test_compose_missing_fails() -> None:
    statuses = _run(docker=FakeDocker(compose_error="compose missing"))
    assert statuses["compose"] == "fail"


def test_podman_compose_fails_when_socket_not_listening() -> None:
    # default podman socket path, but a bare FakeFs: nothing marked existing
    docker = FakeDocker(runtime="podman", engine_version="6.1.1")
    statuses = _run(docker=docker, fs=FakeFs())
    assert statuses["compose"] == "fail"
    checks = run_doctor(
        docker,
        FakeSystem(),
        FakeGitHub(),
        FakeFs(),
        GlobalConfig(instances_root=Path("/tmp/oii-test")),
    )
    compose = next(check for check in checks if check.name == "compose")
    assert "podman.socket" in (compose.fix_hint or "")


def test_podman_compose_fails_when_socket_undeterminable() -> None:
    docker = FakeDocker(runtime="podman", engine_version="6.1.1", podman_socket=None)
    statuses = _run(docker=docker)
    assert statuses["compose"] == "fail"


def test_podman_compose_ok_when_socket_listens() -> None:
    docker = FakeDocker(runtime="podman", engine_version="6.1.1")
    statuses = _run(docker=docker)  # _run marks the default socket as listening
    assert statuses["compose"] == "ok"


def test_docker_group_membership_variants() -> None:
    # default fake: "alice" is a member of the docker group → ok
    assert _run()["runtime permissions"] == "ok"
    # group exists, user missing → fail
    assert _run(FakeSystem(docker_group_members=()))["runtime permissions"] == "fail"
    assert _run(FakeSystem(docker_group_members=("bob",)))["runtime permissions"] == "fail"
    # group does not exist (rootless docker) → warn, not fail
    assert _run(FakeSystem(docker_group_members=None))["runtime permissions"] == "warn"


def test_podman_permissions_do_not_depend_on_docker_group() -> None:
    # rootless podman: no group requirement at all, even without a docker group
    statuses = _run(docker=_podman_docker(), system=FakeSystem(docker_group_members=None))
    assert statuses["runtime permissions"] == "ok"
    assert statuses["container runtime"] == "ok"


def test_podman_linger_and_restart_checks() -> None:
    # linger off and podman-restart disabled → warns (not fails: desktop boxes)
    statuses = _run(docker=_podman_docker(), system=FakeSystem(linger=False))
    assert statuses["linger (boot survival)"] == "warn"
    assert statuses["podman boot restart"] == "warn"
    # both on → green
    healthy = _run(
        docker=_podman_docker(),
        system=FakeSystem(linger=True, user_units_enabled={PODMAN_RESTART_SERVICE}),
    )
    assert set(healthy.values()) == {"ok"}
    # undeterminable systemd state → warns
    unknown = _run(
        docker=_podman_docker(),
        system=FakeSystem(linger=None, user_units_enabled=set()),
    )
    assert unknown["linger (boot survival)"] == "warn"
    assert unknown["podman boot restart"] == "warn"


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


def test_install_plan_podman_enables_linger_and_restart() -> None:
    system = FakeSystem(binaries={"git", "podman", "sudo"}, linger=False)
    fs = FakeFs()
    fs.remember(Path(FakeDocker.DEFAULT_PODMAN_SOCKET.removeprefix("unix://")))
    steps = host_install_plan(_podman_docker(), system, fs)
    descriptions = [step.description for step in steps]
    assert any("linger" in description for description in descriptions)
    assert any(PODMAN_RESTART_SERVICE in description for description in descriptions)
    assert not any("podman.socket" in description for description in descriptions)
    # once enabled, the plan is empty again (idempotent re-probe)
    system.enable_linger()
    system.enable_user_service(PODMAN_RESTART_SERVICE)
    assert host_install_plan(_podman_docker(), system, fs) == []


def test_install_plan_podman_adds_socket_step_when_not_listening() -> None:
    system = FakeSystem(
        binaries={"git", "podman", "sudo"},
        linger=True,
        user_units_enabled={PODMAN_RESTART_SERVICE},
    )
    steps = host_install_plan(_podman_docker(), system, FakeFs())
    assert any("podman.socket" in step.description for step in steps)
