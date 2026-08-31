"""Doctor: host prerequisite checks (DEVELOPMENT.md §2).

Each check returns a CheckResult and never raises: expected adapter errors
(OdooInstallerError) are converted to FAIL, non-critical services that are down
(github) degrade to WARN. Any FAIL makes the CLI exit with code 4.
"""

from __future__ import annotations

from collections.abc import Callable

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.github import GitHubLike
from odoo_installer.adapters.system import SystemLike
from odoo_installer.constants import DEFAULT_HTTP_PORT
from odoo_installer.exceptions import OdooInstallerError
from odoo_installer.schemas import CheckResult, CheckStatus, GlobalConfig

DISK_FAIL_GIB = 2.0
DISK_WARN_GIB = 5.0


def run_doctor(
    docker: DockerLike,
    system: SystemLike,
    github: GitHubLike,
    fs: FileSystemLike,
    config: GlobalConfig,
) -> list[CheckResult]:
    """Run every host check and return results in stable display order."""
    return [
        _check_docker_engine(docker, system),
        _check_compose(docker, system),
        _check_docker_group(system),
        _check_git(system),
        _check_disk(fs, config),
        _check_ports(system, config),
        _check_github(github),
    ]


def _guarded(name: str, fix_hint: str, probe: Callable[[], CheckResult]) -> CheckResult:
    try:
        return probe()
    except OdooInstallerError as exc:
        return CheckResult(name=name, status=CheckStatus.FAIL, detail=str(exc), fix_hint=fix_hint)


def _install_hint(system: SystemLike, pacman_pkg: str, apt_pkg: str) -> str:
    if system.package_manager() == "apt":
        return f"install with: sudo apt-get install -y {apt_pkg}"
    return f"install with: sudo pacman -S {pacman_pkg}"


def _check_docker_engine(docker: DockerLike, system: SystemLike) -> CheckResult:
    hint = (
        f"{_install_hint(system, 'docker', 'docker.io')}; then sudo systemctl enable --now docker"
    )
    return _guarded(
        "docker engine",
        hint,
        lambda: CheckResult(
            name="docker engine",
            status=CheckStatus.OK,
            detail=f"Docker engine {docker.engine_version()} running",
        ),
    )


def _check_compose(docker: DockerLike, system: SystemLike) -> CheckResult:
    return _guarded(
        "docker compose",
        _install_hint(system, "docker-compose", "docker-compose-plugin"),
        lambda: CheckResult(
            name="docker compose",
            status=CheckStatus.OK,
            detail=f"compose plugin {docker.compose_version()}",
        ),
    )


def _check_docker_group(system: SystemLike) -> CheckResult:
    members = system.group_members("docker")
    if members is None:
        return CheckResult(
            name="docker permissions",
            status=CheckStatus.WARN,
            detail="no 'docker' group on this host (rootless docker?)",
            fix_hint="verify that 'docker ps' works for the current user",
        )
    if system.current_username() in members:
        return CheckResult(
            name="docker permissions",
            status=CheckStatus.OK,
            detail="user is configured in the docker group",
        )
    return CheckResult(
        name="docker permissions",
        status=CheckStatus.FAIL,
        detail="user is not configured in the docker group",
        fix_hint="run: sudo usermod -aG docker $USER (then re-login)",
    )


def _check_git(system: SystemLike) -> CheckResult:
    git_path = system.which("git")
    if git_path is None:
        return CheckResult(
            name="git",
            status=CheckStatus.FAIL,
            detail="git not found on PATH",
            fix_hint=_install_hint(system, "git", "git"),
        )
    return CheckResult(name="git", status=CheckStatus.OK, detail=f"git at {git_path}")


def _check_disk(fs: FileSystemLike, config: GlobalConfig) -> CheckResult:
    free_gib, probe = fs.disk_free_gib(config.instances_root)
    suffix = (
        ""
        if probe == config.instances_root
        else f" (instances root {config.instances_root} does not exist yet)"
    )
    detail = f"{free_gib:.1f} GiB free at {probe}{suffix}"
    if free_gib < DISK_FAIL_GIB:
        return CheckResult(
            name="disk space",
            status=CheckStatus.FAIL,
            detail=detail,
            fix_hint="free up space (an Odoo 19 stack needs roughly 7 GB)",
        )
    if free_gib < DISK_WARN_GIB:
        return CheckResult(name="disk space", status=CheckStatus.WARN, detail=detail)
    return CheckResult(name="disk space", status=CheckStatus.OK, detail=detail)


def _check_ports(system: SystemLike, config: GlobalConfig) -> CheckResult:
    start, end = config.port_range_start, config.port_range_end
    total = end - start + 1
    busy = [port for port in range(start, end + 1) if system.port_in_use(port)]
    if not busy:
        return CheckResult(
            name="ports",
            status=CheckStatus.OK,
            detail=f"ports {start}-{end} all free",
        )
    busy_str = ", ".join(str(port) for port in busy)
    detail = f"{total - len(busy)}/{total} ports free in {start}-{end}; in use: {busy_str}"
    if DEFAULT_HTTP_PORT in busy:
        detail = f"default HTTP port {DEFAULT_HTTP_PORT} is busy; {detail}"
    return CheckResult(
        name="ports",
        status=CheckStatus.WARN,
        detail=detail,
        fix_hint=f"free the ports or let instance create pick the next free one "
        f"({DEFAULT_HTTP_PORT}-{end})",
    )


def _check_github(github: GitHubLike) -> CheckResult:
    try:
        return CheckResult(name="github api", status=CheckStatus.OK, detail=github.ping())
    except OdooInstallerError as exc:
        return CheckResult(
            name="github api",
            status=CheckStatus.WARN,
            detail=str(exc),
            fix_hint="check network or set the token env var; needed only for OCA module search",
        )
