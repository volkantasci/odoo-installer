"""CLI tests for the `instance` sub-app (deps patched; all effects stay in tmp_path)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()


def make_container(
    tmp_path: Path,
    docker: FakeDocker | None = None,
    system: FakeSystem | None = None,
    fs: FakeFs | None = None,
) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        git=FakeGit(),
        docker=docker or FakeDocker(),
        system=system or FakeSystem(),
        github=FakeGitHub(),
        fs=fs or FakeFs(),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_create_dry_run_writes_nothing(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "create", "dev"])
    assert result.exit_code == 0
    assert "8069" in result.output
    assert "dry run" in result.output
    assert not (tmp_path / "instances" / "dev").exists()


def test_create_apply_creates_and_starts_stack(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    stack = tmp_path / "instances" / "dev"
    assert (stack / "docker-compose.yml").exists()
    assert container.docker.compose_calls[0][0] == ("up", "-d")
    assert container.docker.health_checks == ["dev-web-1"]
    assert "ready at http://localhost:8069" in result.output
    # live progress: every step is announced as [i/n] before it runs
    assert "[1/" in result.output
    counts = [
        int(line.split("[")[1].split("/")[0])
        for line in result.output.splitlines()
        if line.startswith("[")
    ]
    total = max(counts)
    assert f"[{total}/" in result.output


def test_create_apply_reruns_are_idempotent(patch_deps, tmp_path: Path) -> None:
    system = FakeSystem(busy_ports={8069})  # like this machine: 8069 held by a live stack
    container = make_container(tmp_path, system=system)
    patch_deps(container)
    first = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert first.exit_code == 0, first.output
    assert "8070" in first.output
    system.block_port(8070)  # the instance's own container now holds its port
    second = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert second.exit_code == 0, second.output
    assert "8070" in second.output  # port must not drift to 8071 on re-run
    assert "already satisfied" in second.output
    assert len(container.docker.compose_calls) == 2  # one up -d per run, nothing else


def test_create_rejects_invalid_name(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "create", "Bad_Name"])
    assert result.exit_code == 1
    assert "invalid instance name" in result.output


def test_create_auto_allocates_next_free_port(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, system=FakeSystem(busy_ports={8069})))
    result = runner.invoke(app, ["instance", "create", "dev", "--apply"])
    assert result.exit_code == 0, result.output
    assert "8070" in result.output


def test_create_rejects_busy_requested_port(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path, system=FakeSystem(busy_ports={8123})))
    result = runner.invoke(app, ["instance", "create", "dev", "--http-port", "8123"])
    assert result.exit_code == 1
    assert "already in use" in result.output


def test_list_empty_then_populated(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    empty = runner.invoke(app, ["instance", "list"])
    assert empty.exit_code == 0
    assert "no instances" in empty.output
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    populated = runner.invoke(app, ["instance", "list"])
    assert populated.exit_code == 0
    assert "dev" in populated.output
    assert "8069" in populated.output


def test_lifecycle_actions_map_to_compose(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    for action, expected in (
        ("stop", ("stop",)),
        ("start", ("up", "-d")),
        ("restart", ("restart",)),
    ):
        result = runner.invoke(app, ["instance", action, "dev"])
        assert result.exit_code == 0, result.output
        assert container.docker.compose_calls[-1][0] == expected


def test_show_renders_manifest_details(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "show", "dev"])
    assert result.exit_code == 0
    assert "dev" in result.output
    assert "odoo:19.0" in result.output


def test_show_unknown_instance_fails(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "show", "ghost"])
    assert result.exit_code == 1


def test_show_json_includes_manifest_and_containers(patch_deps, tmp_path: Path) -> None:
    docker = FakeDocker(
        containers=[
            {
                "name": "dev-web-1",
                "service": "web",
                "project": "dev",
                "image": "odoo:19.0",
                "ports": "0.0.0.0:8069->8069/tcp",
                "state": "running",
            },
            {
                "name": "dev-db-1",
                "service": "db",
                "project": "dev",
                "image": "postgres:17",
                "state": "running",
            },
        ]
    )
    patch_deps(make_container(tmp_path, docker=docker))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "show", "dev", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "dev"
    assert payload["image"] == "odoo:19.0"
    assert payload["reachable"] is True
    assert [c["service"] for c in payload["containers"]] == ["web", "db"]
    assert payload["containers"][0]["state"] == "running"


def test_show_json_marks_unreachable_runtime(patch_deps, tmp_path: Path) -> None:
    docker = FakeDocker(containers_error=StackError("podman ps failed: no socket"))
    patch_deps(make_container(tmp_path, docker=docker))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "show", "dev", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["reachable"] is False
    assert payload["containers"] == []


def test_list_json(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    runner.invoke(app, ["instance", "create", "shop", "--apply"])
    result = runner.invoke(app, ["instance", "list", "--json"])
    assert result.exit_code == 0, result.output
    entries = json.loads(result.output)
    assert [entry["name"] for entry in entries] == ["dev", "shop"]
    assert entries[0]["http_port"] == 8069
    assert entries[1]["http_port"] == 8070


def test_create_skips_ports_reserved_by_stopped_stacks(patch_deps, tmp_path: Path) -> None:
    # instance "first" is registered on 8069 but stopped: no socket, only the
    # registry claim — auto-allocation for "second" must skip 8069 anyway.
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "first", "--apply"])
    container.docker.compose_calls.clear()
    result = runner.invoke(app, ["instance", "create", "second", "--apply"])
    assert result.exit_code == 0, result.output
    assert "8070" in result.output
    assert "8069" not in result.output


def test_create_rejects_port_reserved_by_other_instance(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "first", "--apply"])
    result = runner.invoke(app, ["instance", "create", "second", "--http-port", "8069"])
    assert result.exit_code == 1
    assert "reserved by instance 'first'" in result.output


def test_create_reaccepts_own_pinned_port_when_running(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    container.system.block_port(8069)  # its own web container holds the port now
    result = runner.invoke(app, ["instance", "create", "dev", "--http-port", "8069", "--apply"])
    assert result.exit_code == 0, result.output
    assert "already satisfied" in result.output


def test_secret_prints_master_password(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "secret", "dev"])
    assert result.exit_code == 0
    value = result.output.strip()
    assert len(value) >= 16  # generated master password
    env_text = (tmp_path / "instances" / "dev" / ".env").read_text(encoding="utf-8")
    assert value in env_text


def test_secret_custom_key(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "secret", "dev", "--key", "POSTGRES_PASSWORD"])
    assert result.exit_code == 0
    assert result.output.strip() not in ("", "ADMIN_PASSWD")


def test_secret_unknown_key_fails(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "secret", "dev", "--key", "NOPE"])
    assert result.exit_code == 1
    assert "NOPE" in result.output


def test_remove_without_yes_removes_nothing(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "remove", "dev", "--apply"])
    assert result.exit_code == 0
    assert "add --yes" in result.output
    assert (tmp_path / "instances" / "dev").exists()


def test_remove_apply_yes_deletes_everything(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    result = runner.invoke(app, ["instance", "remove", "dev", "--apply", "--yes", "--remove-data"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "instances" / "dev").exists()
    assert container.docker.compose_calls[-1][0] == (
        "down",
        "--remove-orphans",
        "-v",
    )
    listed = runner.invoke(app, ["instance", "list"])
    assert "no instances" in listed.output


def test_remove_unknown_instance_fails(patch_deps, tmp_path: Path) -> None:
    patch_deps(make_container(tmp_path))
    result = runner.invoke(app, ["instance", "remove", "ghost"])
    assert result.exit_code == 1
    assert "not registered" in result.output


def test_create_ingress_mode_publishes_no_port(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(
        app,
        [
            "instance",
            "create",
            "acme",
            "--apply",
            "--ingress-network",
            "violetear-ingress",
        ],
    )
    assert result.exit_code == 0, result.output
    compose = (tmp_path / "instances" / "acme" / "docker-compose.yml").read_text()
    assert "ports:" not in compose
    assert "violetear-ingress" in compose
    assert "- acme" in compose  # alias defaults to the instance name
    conf = (tmp_path / "instances" / "acme" / "config" / "odoo.conf").read_text()
    assert "proxy_mode = True" in conf  # ingress implies proxy_mode
    assert "ready on ingress network" in result.output
    entry = json.loads(runner.invoke(app, ["instance", "list", "--json"]).stdout)[0]
    assert entry["http_port"] == 0


def test_create_ingress_rerun_pins_state(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    first = runner.invoke(
        app, ["instance", "create", "acme", "--apply", "--ingress-network", "ing"]
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["instance", "create", "acme", "--apply"])
    assert second.exit_code == 0, second.output
    assert "already satisfied" in second.output
    compose = (tmp_path / "instances" / "acme" / "docker-compose.yml").read_text()
    assert "name: ing" in compose  # manifest fallback: no drift without flags


def test_create_with_resources(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    result = runner.invoke(
        app,
        [
            "instance",
            "create",
            "big",
            "--apply",
            "--memory",
            "2g",
            "--cpus",
            "1.5",
            "--workers",
            "4",
            "--no-proxy-mode",
        ],
    )
    assert result.exit_code == 0, result.output
    compose = (tmp_path / "instances" / "big" / "docker-compose.yml").read_text()
    assert "mem_limit: 2g" in compose
    assert "cpus: 1.5" in compose
    conf = (tmp_path / "instances" / "big" / "config" / "odoo.conf").read_text()
    assert "workers = 4" in conf


def test_health_json_and_exit_codes(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    with mock.patch("odoo_installer.core.health._http_get", return_value=(200, "GET -> 200")):
        ok = runner.invoke(app, ["instance", "health", "dev", "--json"])
    assert ok.exit_code == 0, ok.output
    payload = json.loads(ok.stdout)
    assert payload == {
        "instance": "dev",
        "healthy": True,
        "detail": "GET http://localhost:8069/web/health -> 200",
    }
    with mock.patch("odoo_installer.core.health._http_get", return_value=(0, "connection refused")):
        bad = runner.invoke(app, ["instance", "health", "dev", "--json"])
    assert bad.exit_code == 1
    assert json.loads(bad.stdout)["healthy"] is False


def test_health_ingress_uses_container_probe(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "acme", "--apply", "--ingress-network", "ing"])
    result = runner.invoke(app, ["instance", "health", "acme", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["healthy"] is True
    assert "dev-web-1".replace("dev", "acme") in payload["detail"]


def test_logs_command_maps_to_compose(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    runner.invoke(app, ["instance", "create", "dev", "--apply"])
    container.docker.compose_calls.clear()
    result = runner.invoke(app, ["instance", "logs", "dev", "--tail", "20"])
    assert result.exit_code == 0, result.output
    assert container.docker.compose_calls[-1][0] == ("logs", "--tail", "20")
