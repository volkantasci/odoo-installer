"""Integration tests: real container runtime, real compose, real files.

Opt-in via OII_INTEGRATION=1 (pytest -m integration). Everything runs inside a
throwaway XDG_CONFIG_HOME + instances root, so the host's real registry, config
and stacks are never touched. OII_INTEGRATION_RUNTIME selects the runtime
(default podman; docker works too — the suite is runtime-agnostic).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REASON = "set OII_INTEGRATION=1 to run integration tests"
if os.environ.get("OII_INTEGRATION") != "1":
    pytest.skip(_REASON, allow_module_level=True)


@pytest.fixture(scope="session")
def runtime() -> str:
    return os.environ.get("OII_INTEGRATION_RUNTIME", "podman")


@pytest.fixture(scope="session")
def podman_socket(tmp_path_factory: pytest.TempPathFactory, runtime: str) -> str | None:
    """A listening rootless podman socket URI, or None when not needed.

    Hermetic on purpose: a session-scoped `podman system service` on its own
    socket file — no host unit is enabled or mutated. Real hosts get the same
    reachability from `systemctl --user enable --now podman.socket` (which
    `oii install` plans and `oii doctor` verifies).
    """
    if runtime != "podman":
        return None
    socket_file = tmp_path_factory.mktemp("podman") / "podman.sock"
    proc = subprocess.Popen(
        ["podman", "system", "service", "--time=0", f"unix://{socket_file}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not socket_file.exists():
        time.sleep(0.2)
    if not socket_file.exists():
        proc.terminate()
        pytest.fail("podman system service did not come up within 30s")
    yield f"unix://{socket_file}"
    proc.terminate()
    proc.wait(timeout=15)


@pytest.fixture(scope="session")
def cli_env(
    tmp_path_factory: pytest.TempPathFactory, runtime: str, podman_socket: str | None
) -> dict[str, str]:
    """Isolated environment: XDG paths + config.toml pinned to the runtime."""
    base = tmp_path_factory.mktemp("oii-integration")
    config_dir = base / "config" / "odoo-installer"
    config_dir.mkdir(parents=True)
    instances_root = base / "instances"
    repo_root = base / "repos"
    (config_dir / "config.toml").write_text(
        f'container_runtime = "{runtime}"\n'
        f'instances_root = "{instances_root}"\n'
        f'repo_root = "{repo_root}"\n'
        "port_range_start = 18069\n"
        "port_range_end = 18099\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(base / "config")
    env["XDG_CACHE_HOME"] = str(base / "cache")
    env["XDG_STATE_HOME"] = str(base / "state")
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    if podman_socket:
        env["CONTAINER_HOST"] = podman_socket
        env["DOCKER_HOST"] = podman_socket
    if runtime == "podman":
        _sweep_orphans(env)
    return env


def _sweep_orphans(env: dict[str, str]) -> None:
    """Remove containers/volumes/networks leaked by crashed earlier runs.

    A crashed suite leaves its stacks behind (no cleanup ran); the next session
    starts with an empty registry and would collide on ports and project names.
    Orphans are identified by compose labels: any project whose working_dir is
    under the pytest tmp root belongs to an integration run, never to a user.
    """
    listing = subprocess.run(
        ["podman", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    if listing.returncode != 0:
        return
    projects: set[str] = set()
    for line in listing.stdout.splitlines():
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        labels = raw.get("Labels") or {}
        if isinstance(labels, str):
            labels = dict(part.split("=", 1) for part in labels.split(",") if "=" in part)
        workdir = labels.get("com.docker.compose.project.working_dir", "")
        if workdir.startswith("/tmp/pytest"):
            projects.add(labels.get("com.docker.compose.project", ""))
    if not projects:
        return
    for project in sorted(p for p in projects if p):
        subprocess.run(
            [
                "podman",
                "rm",
                "-f",
                "--ignore",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        subprocess.run(
            ["podman", "volume", "rm", "-f", f"{project}_pgdata", f"{project}_filestore"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )


@pytest.fixture(scope="session")
def run(cli_env: dict[str, str]):
    def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, "-m", "odoo_installer", *args],
            capture_output=True,
            text=True,
            timeout=900,
            env=cli_env,
        )
        if check and proc.returncode != 0:
            pytest.fail(
                f"`oii {' '.join(args)}` exited {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc

    return _run


@pytest.fixture(scope="session")
def compose_provider(runtime: str) -> str:
    if shutil.which(runtime) is None:
        pytest.skip(f"{runtime} binary not available")
    proc = subprocess.run(
        [runtime, "compose", "version", "--short"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"no compose provider for {runtime}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def test_doctor_reports_selected_runtime(run, runtime: str, compose_provider: str) -> None:
    proc = run("doctor", "--json", check=False)
    checks = {check["name"]: check for check in json.loads(proc.stdout)}
    # The runtime/compose pair must be green; unrelated checks (ports, github,
    # disk) may legitimately warn on a busy CI box.
    assert proc.returncode in (0, 4)
    assert checks["container runtime"]["status"] == "ok"
    assert runtime in checks["container runtime"]["detail"].lower()
    assert checks["compose"]["status"] == "ok"
    assert compose_provider.split("-")[0].lstrip("v") in checks["compose"]["detail"]


def test_full_instance_lifecycle(run, compose_provider: str) -> None:
    run("instance", "create", "smoke", "--apply")
    listing = json.loads(run("instance", "list", "--json").stdout)
    assert [entry["name"] for entry in listing] == ["smoke"]
    assert listing[0]["http_port"] == 18069

    shown = json.loads(run("instance", "show", "smoke", "--json").stdout)
    assert shown["reachable"] is True
    states = {c["service"]: c["state"] for c in shown["containers"]}
    assert states.get("web") == "running"
    assert states.get("db") == "running"

    run("db", "create", "smokedb")
    databases = json.loads(run("db", "list", "--json").stdout)
    assert "smokedb" in [db["name"] for db in databases]

    run("instance", "stop", "smoke")
    stopped = json.loads(run("instance", "show", "smoke", "--json").stdout)
    states = {c["service"]: c["state"] for c in stopped["containers"]}
    assert states.get("web") in ("exited", "stopped")

    run("instance", "start", "smoke")
    started = json.loads(run("instance", "show", "smoke", "--json").stdout)
    states = {c["service"]: c["state"] for c in started["containers"]}
    assert states.get("web") == "running"

    run("instance", "remove", "smoke", "--remove-data", "--apply", "--yes")
    empty = json.loads(run("instance", "list", "--json").stdout)
    assert empty == []


def test_ingress_mode_stack(run, cli_env: dict[str, str]) -> None:
    """Reverse-proxy style: external network + alias, no published port."""
    network = "oii-integration-ingress"
    subprocess.run(
        ["podman", "network", "create", network],
        capture_output=True,
        text=True,
        env=cli_env,
        timeout=60,
        check=False,
    )
    try:
        run("instance", "create", "ingress", "--apply", "--ingress-network", network)
        compose = _stack_file(cli_env, "ingress", "docker-compose.yml")
        assert "ports:" not in compose.read_text(encoding="utf-8")

        # health goes through the container healthcheck (no host port exists)
        health = json.loads(run("instance", "health", "ingress", "--json").stdout)
        assert health["healthy"] is True

        # the alias resolves from another container on the same network
        probe = subprocess.run(
            [
                "podman",
                "run",
                "--rm",
                "--network",
                network,
                "docker.io/library/alpine:latest",
                "getent",
                "hosts",
                "ingress",
            ],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=180,
        )
        assert probe.returncode == 0, probe.stdout + probe.stderr
        assert "ingress" in probe.stdout
    finally:
        run("instance", "remove", "ingress", "--remove-data", "--apply", "--yes")
        subprocess.run(
            ["podman", "network", "rm", network],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=60,
            check=False,
        )


def _stack_file(cli_env: dict[str, str], name: str, filename: str) -> Path:
    shown = json.loads(
        subprocess.run(
            [sys.executable, "-m", "odoo_installer", "config", "show", "--json"],
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=60,
            check=True,
        ).stdout
    )
    return Path(shown["instances_root"]) / name / filename


def test_backup_round_trip(run) -> None:
    """Real pg_dump/pg_restore/tar streamed through the runtime."""
    run("instance", "create", "bk", "--apply")
    try:
        run("db", "create", "bkdb")
        # initialize the db as Odoo expects it (also exercises module install):
        # Odoo cannot serve (and /web/health stays 500) on a never-initialized db
        run("module", "install", "base", "--db", "bkdb")
        assert json.loads(run("backup", "list", "--json").stdout) == []
        run("backup", "create")  # single Odoo database -> unambiguous default
        backups = json.loads(run("backup", "list", "--json").stdout)
        assert len(backups) == 1
        assert backups[0]["db"] == "bkdb"
        assert backups[0]["db_bytes"] > 0
        assert backups[0]["filestore_bytes"] > 0
        timestamp = backups[0]["timestamp"]
        run("backup", "verify")
        run("backup", "restore", timestamp, "--apply", "--yes")
        run("backup", "prune", "--keep", "1", "--apply")
        assert len(json.loads(run("backup", "list", "--json").stdout)) == 1
    finally:
        run("instance", "remove", "bk", "--remove-data", "--apply", "--yes", check=False)


def test_apply_end_to_end(run, tmp_path: Path) -> None:
    """Declarative converge: spec -> stack -> OCA repo -> Odoo db with modules."""
    spec_file = tmp_path / "odoo-stack.toml"
    spec_file.write_text(
        """name = "e2e"
http_port = 18069

[settings]
workers = 2

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.e2edb]
install = ["base", "web_environment_ribbon"]
allow_untested = true
""",
        encoding="utf-8",
    )
    run("apply", str(spec_file), "--apply")
    try:
        shown = json.loads(run("instance", "show", "e2e", "--json").stdout)
        assert shown["reachable"] is True
        databases = json.loads(run("db", "list", "--json").stdout)
        assert "e2edb" in [db["name"] for db in databases]

        # the OCA module is genuinely installed in the Odoo database
        # (module list shows repo-mounted modules; core modules like base are
        # implicit — web_environment_ribbon pulls them in via its deps)
        listing = run("module", "list", "--db", "e2edb", "--json").stdout
        rows = {row["module"]: row for row in json.loads(listing)}
        assert rows["web_environment_ribbon"]["state"] == "installed"

        # convergence is idempotent: second apply reports satisfied steps, exit 0
        again = run("apply", str(spec_file), "--apply", check=False)
        assert again.returncode == 0, again.stdout + again.stderr
        assert "already satisfied" in again.stdout
    finally:
        run("instance", "remove", "e2e", "--remove-data", "--apply", "--yes", check=False)
