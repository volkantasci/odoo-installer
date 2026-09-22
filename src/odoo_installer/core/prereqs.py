"""Doctor: host prerequisite checks (DEVELOPMENT.md §2).

Each check returns a CheckResult and never raises: expected adapter errors
(OdooInstallerError) are converted to FAIL, non-critical services that are down
(github) degrade to WARN. Any FAIL makes the CLI exit with code 4.

Checks are runtime-aware: under podman the permission model is rootless-first
(so the docker-group check is replaced by linger / podman-restart.service WARNs
for boot survival), under docker it stays the classic group membership check.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.github import GitHubLike
from odoo_installer.adapters.system import SystemLike
from odoo_installer.constants import DEFAULT_HTTP_PORT
from odoo_installer.core.plan import Step
from odoo_installer.exceptions import OdooInstallerError, PrerequisiteError
from odoo_installer.schemas import CheckResult, CheckStatus, GlobalConfig

DISK_FAIL_GIB = 2.0
DISK_WARN_GIB = 5.0

PODMAN_RESTART_SERVICE = "podman-restart.service"


def run_doctor(
    docker: ComposeLike,
    system: SystemLike,
    github: GitHubLike,
    fs: FileSystemLike,
    config: GlobalConfig,
) -> list[CheckResult]:
    """Run every host check and return results in stable display order."""
    checks = [
        _check_runtime(docker, system),
        _check_compose(docker, system, fs),
        _check_permissions(docker, system),
        _check_git(system),
        _check_disk(fs, config),
        _check_ports(system, config),
        _check_github(github),
    ]
    if docker.runtime == "podman":
        checks.append(_check_linger(system))
        checks.append(_check_podman_restart(system))
    return checks


def _guarded(name: str, fix_hint: str, probe: Callable[[], CheckResult]) -> CheckResult:
    try:
        return probe()
    except OdooInstallerError as exc:
        return CheckResult(name=name, status=CheckStatus.FAIL, detail=str(exc), fix_hint=fix_hint)


def _install_hint(system: SystemLike, pacman_pkg: str, apt_pkg: str) -> str:
    if system.package_manager() == "apt":
        return f"install with: sudo apt-get install -y {apt_pkg}"
    return f"install with: sudo pacman -S {pacman_pkg}"


def _check_runtime(docker: ComposeLike, system: SystemLike) -> CheckResult:
    if docker.runtime == "podman":
        return _guarded(
            "container runtime",
            _install_hint(system, "podman", "podman"),
            lambda: CheckResult(
                name="container runtime",
                status=CheckStatus.OK,
                detail=f"podman {docker.engine_version()} usable by the current user",
            ),
        )
    hint = (
        f"{_install_hint(system, 'docker', 'docker.io')}; then sudo systemctl enable --now docker"
    )
    return _guarded(
        "container runtime",
        hint,
        lambda: CheckResult(
            name="container runtime",
            status=CheckStatus.OK,
            detail=f"docker engine {docker.engine_version()} running",
        ),
    )


def _check_compose(docker: ComposeLike, system: SystemLike, fs: FileSystemLike) -> CheckResult:
    if docker.runtime == "podman":
        socket_check = _check_podman_socket(docker, fs)
        if socket_check is not None:
            return socket_check
    return _guarded(
        "compose",
        _install_hint(system, "docker-compose", "docker-compose-plugin"),
        lambda: CheckResult(
            name="compose",
            status=CheckStatus.OK,
            detail=f"compose provider {docker.compose_version()} via {docker.runtime}",
        ),
    )


def _check_podman_socket(docker: ComposeLike, fs: FileSystemLike) -> CheckResult | None:
    """FAIL when the rootless podman socket is not listening.

    The compose provider connects through that socket; `podman compose version`
    succeeds without it, so an explicit reachability probe is the only honest
    signal that `instance create --apply` will get past `up -d`.
    """
    socket_uri = docker.remote_socket()
    if not socket_uri:
        return CheckResult(
            name="compose",
            status=CheckStatus.FAIL,
            detail="cannot determine the rootless podman socket (podman info failed)",
            fix_hint="check that 'podman info' works for the current user",
        )
    socket_path = Path(socket_uri.removeprefix("unix://"))
    if not fs.exists(socket_path):
        return CheckResult(
            name="compose",
            status=CheckStatus.FAIL,
            detail=f"rootless podman socket {socket_path} is not listening — the compose "
            "provider cannot reach podman without it",
            fix_hint="run: systemctl --user enable --now podman.socket",
        )
    return None


def _check_permissions(docker: ComposeLike, system: SystemLike) -> CheckResult:
    if docker.runtime == "podman":
        # The runtime check already proved `podman info` answers for this user;
        # rootless podman needs no group, socket or service enrollment.
        return CheckResult(
            name="runtime permissions",
            status=CheckStatus.OK,
            detail="rootless podman usable by the current user",
        )
    members = system.group_members("docker")
    if members is None:
        return CheckResult(
            name="runtime permissions",
            status=CheckStatus.WARN,
            detail="no 'docker' group on this host (rootless docker?)",
            fix_hint="verify that 'docker ps' works for the current user",
        )
    if system.current_username() in members:
        return CheckResult(
            name="runtime permissions",
            status=CheckStatus.OK,
            detail="user is configured in the docker group",
        )
    return CheckResult(
        name="runtime permissions",
        status=CheckStatus.FAIL,
        detail="user is not configured in the docker group",
        fix_hint="run: sudo usermod -aG docker $USER (then re-login)",
    )


def _check_linger(system: SystemLike) -> CheckResult:
    linger = system.linger_enabled()
    if linger is None:
        return CheckResult(
            name="linger (boot survival)",
            status=CheckStatus.WARN,
            detail="cannot determine linger status (no systemd user manager?)",
            fix_hint="on servers run: sudo loginctl enable-linger $USER",
        )
    if linger:
        return CheckResult(
            name="linger (boot survival)",
            status=CheckStatus.OK,
            detail=f"linger enabled for {system.current_username()} — "
            "rootless containers survive reboots",
        )
    return CheckResult(
        name="linger (boot survival)",
        status=CheckStatus.WARN,
        detail="linger is disabled: rootless containers and user services stop at logout",
        fix_hint="run: sudo loginctl enable-linger $USER",
    )


def _check_podman_restart(system: SystemLike) -> CheckResult:
    enabled = system.user_service_enabled(PODMAN_RESTART_SERVICE)
    if enabled is None:
        return CheckResult(
            name="podman boot restart",
            status=CheckStatus.WARN,
            detail=f"cannot query {PODMAN_RESTART_SERVICE} (no systemd user manager?)",
            fix_hint=f"run: systemctl --user enable {PODMAN_RESTART_SERVICE}",
        )
    if enabled:
        return CheckResult(
            name="podman boot restart",
            status=CheckStatus.OK,
            detail=f"{PODMAN_RESTART_SERVICE} enabled — restart-policy containers "
            "come back on boot",
        )
    return CheckResult(
        name="podman boot restart",
        status=CheckStatus.WARN,
        detail=f"{PODMAN_RESTART_SERVICE} is disabled: containers with a restart policy "
        "are not restarted on boot",
        fix_hint=f"run: systemctl --user enable {PODMAN_RESTART_SERVICE}",
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


def host_install_plan(docker: ComposeLike, system: SystemLike, fs: FileSystemLike) -> list[Step]:
    """Plan steps to make host prerequisites ready; an empty list means satisfied."""
    steps: list[Step] = []
    try:
        docker.engine_version()
    except OdooInstallerError:
        if system.which(docker.runtime) is None:
            if docker.runtime == "podman":
                steps.append(_package_step(system, "podman", "podman"))
            else:
                steps.append(_package_step(system, "docker", "docker.io"))
        elif docker.runtime == "docker":
            steps.append(
                Step(
                    description="enable and start the docker service",
                    run=lambda: system.enable_service("docker"),
                )
            )
    try:
        docker.compose_version()
    except OdooInstallerError:
        steps.append(_package_step(system, "docker-compose", "docker-compose-plugin"))
    if system.which("git") is None:
        steps.append(_package_step(system, "git", "git"))
    if docker.runtime == "podman":
        if not _podman_socket_listens(docker, fs):
            steps.append(
                Step(
                    description="enable podman.socket so compose can reach rootless podman",
                    run=lambda: system.enable_user_service("podman.socket"),
                )
            )
        if system.linger_enabled() is False:
            steps.append(
                Step(
                    description="enable linger so rootless containers survive reboots",
                    run=lambda: system.enable_linger(),
                )
            )
        if system.user_service_enabled(PODMAN_RESTART_SERVICE) is False:
            steps.append(
                Step(
                    description=f"enable {PODMAN_RESTART_SERVICE} for boot-time restarts",
                    run=lambda: system.enable_user_service(PODMAN_RESTART_SERVICE),
                )
            )
    return steps


def _podman_socket_listens(docker: ComposeLike, fs: FileSystemLike) -> bool:
    socket_uri = docker.remote_socket()
    if not socket_uri:
        return False
    return fs.exists(Path(socket_uri.removeprefix("unix://")))


def _package_step(system: SystemLike, pacman_pkg: str, apt_pkg: str) -> Step:
    family = system.package_manager()
    if family is None:
        raise PrerequisiteError(
            "cannot determine the package manager; install manually: "
            f"{pacman_pkg} (pacman) or {apt_pkg} (apt)"
        )
    packages = apt_pkg if family == "apt" else pacman_pkg
    return Step(
        description=f"install {packages} ({family})",
        run=lambda: system.install_packages([packages]),
    )
