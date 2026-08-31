"""Tests for instance lifecycle core: naming, ports, create/remove plans, idempotency."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeSystem

from odoo_installer.core.instances import (
    allocate_port,
    compose_action,
    create_instance_plan,
    instance_dir,
    load_manifest,
    remove_instance_plan,
    resolve_create_port,
    save_manifest,
    upsert_registry_entry,
    validate_instance_name,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.core.stack import parse_env
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import GlobalConfig, RegistryEntry


def make_config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(instances_root=tmp_path / "instances")


def create_and_apply(tmp_path: Path, name: str = "dev", port: int = 8069):
    fs, docker = FakeFs(), FakeDocker()
    registry_path = tmp_path / "registry.toml"
    stack_dir = instance_dir(make_config(tmp_path), name, None)
    plan = create_instance_plan(
        name=name,
        stack_dir=stack_dir,
        http_port=port,
        odoo_image="odoo:19.0",
        pg_tag=17,
        config=make_config(tmp_path),
        docker=docker,
        fs=fs,
        registry_path=registry_path,
    )
    apply_steps(plan.steps)
    return fs, docker, registry_path, stack_dir


def test_validate_instance_name_accepts_and_rejects() -> None:
    assert validate_instance_name("dev") == "dev"
    assert validate_instance_name("19-dev") == "19-dev"
    for bad in ("Bad_Name", "-lead", "x" * 40, ""):
        with pytest.raises(StackError, match="invalid instance name"):
            validate_instance_name(bad)


def test_allocate_port_picks_first_free(tmp_path: Path) -> None:
    assert allocate_port(FakeSystem(), make_config(tmp_path), None) == 8069


def test_allocate_port_skips_busy_ones(tmp_path: Path) -> None:
    system = FakeSystem(busy_ports={8069, 8070})
    assert allocate_port(system, make_config(tmp_path), None) == 8071


def test_allocate_port_rejects_busy_requested_port(tmp_path: Path) -> None:
    with pytest.raises(StackError, match="already in use"):
        allocate_port(FakeSystem(busy_ports={9999}), make_config(tmp_path), 9999)


def test_resolve_create_port_reuses_recorded_port(tmp_path: Path) -> None:
    fs, _, _, stack_dir = create_and_apply(tmp_path)  # instance created on 8069
    system = FakeSystem(busy_ports={8069, 8070})  # its own container holds 8069
    port = resolve_create_port(
        system=system,
        config=make_config(tmp_path),
        fs=fs,
        stack_dir=stack_dir,
        requested=None,
    )
    assert port == 8069


def test_resolve_create_port_explicit_busy_request_fails(tmp_path: Path) -> None:
    with pytest.raises(StackError, match="already in use"):
        resolve_create_port(
            system=FakeSystem(busy_ports={9999}),
            config=make_config(tmp_path),
            fs=FakeFs(),
            stack_dir=tmp_path / "fresh",
            requested=9999,
        )


def test_resolve_create_port_fresh_instance_allocates(tmp_path: Path) -> None:
    port = resolve_create_port(
        system=FakeSystem(busy_ports={8069}),
        config=make_config(tmp_path),
        fs=FakeFs(),
        stack_dir=tmp_path / "instances" / "new",
        requested=None,
    )
    assert port == 8070


def test_allocate_port_raises_when_range_exhausted(tmp_path: Path) -> None:
    config = GlobalConfig(instances_root=tmp_path, port_range_start=9000, port_range_end=9001)
    with pytest.raises(StackError, match="no free port"):
        allocate_port(FakeSystem(busy_ports={9000, 9001}), config, None)


def test_create_plan_apply_materializes_stack(tmp_path: Path) -> None:
    fs, docker, registry_path, stack_dir = create_and_apply(tmp_path)
    assert (stack_dir / "docker-compose.yml").exists()
    assert (stack_dir / ".env").exists()
    assert (stack_dir / "config" / "odoo.conf").exists()
    assert (stack_dir / "addons" / "local").is_dir()
    assert (stack_dir / "logs").is_dir()
    manifest = load_manifest(fs, stack_dir)
    assert manifest is not None
    assert manifest.name == "dev"
    assert manifest.http_port == 8069
    assert manifest.image == "odoo:19.0"
    registry_entry = load_registry_entry(registry_path, "dev")
    assert registry_entry is not None
    assert registry_entry.http_port == 8069
    assert docker.compose_calls == [(("up", "-d"), stack_dir)]
    assert docker.health_checks == ["dev-web-1"]


def test_create_plan_file_permissions(tmp_path: Path) -> None:
    _, _, _, stack_dir = create_and_apply(tmp_path)
    import stat

    env_mode = stat.S_IMODE((stack_dir / ".env").stat().st_mode)
    conf_mode = stat.S_IMODE((stack_dir / "config" / "odoo.conf").stat().st_mode)
    assert env_mode == 0o600  # host-only: read by docker compose on the host
    assert conf_mode == 0o644  # must be readable by the container's odoo user


def test_create_plan_reuses_existing_secrets(tmp_path: Path) -> None:
    stack_dir = tmp_path / "instances" / "dev"
    (stack_dir / "config").mkdir(parents=True)
    (stack_dir / ".env").write_text(
        "POSTGRES_PASSWORD=hunter2\nADMIN_PASSWD=master1\n", encoding="utf-8"
    )
    create_and_apply(tmp_path)
    conf = (stack_dir / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "db_password = hunter2" in conf
    assert "admin_passwd = master1" in conf


def test_create_plan_second_run_is_idempotent(tmp_path: Path) -> None:
    fs, _, _, stack_dir = create_and_apply(tmp_path)
    first_env = parse_env((stack_dir / ".env").read_text(encoding="utf-8"))

    plan2 = create_instance_plan(
        name="dev",
        stack_dir=stack_dir,
        http_port=8069,
        odoo_image="odoo:19.0",
        pg_tag=17,
        config=make_config(tmp_path),
        docker=FakeDocker(),
        fs=fs,
        registry_path=tmp_path / "registry.toml",
    )
    descriptions = [step.description for step in plan2.steps]
    satisfied = [step.already_satisfied for step in plan2.steps]
    # directories and all three rendered files are already satisfied
    assert satisfied[0] is True  # dirs
    assert satisfied[1:4] == [True, True, True]  # compose, .env, odoo.conf
    # the stack start + health wait still run (idempotent, no-op on a running stack)
    assert not satisfied[6]
    apply_steps(plan2.steps)
    second_env = parse_env((stack_dir / ".env").read_text(encoding="utf-8"))
    assert second_env["POSTGRES_PASSWORD"] == first_env["POSTGRES_PASSWORD"]
    assert descriptions[0].startswith("create directory structure")


def test_create_plan_refuses_adopted_instance(tmp_path: Path) -> None:
    fs, _, _, stack_dir = create_and_apply(tmp_path)
    manifest = load_manifest(fs, stack_dir)
    assert manifest is not None
    manifest.adopted = True
    save_manifest(fs, manifest)
    with pytest.raises(StackError, match="adopted"):
        create_instance_plan(
            name="dev",
            stack_dir=stack_dir,
            http_port=8069,
            odoo_image="odoo:19.0",
            pg_tag=17,
            config=make_config(tmp_path),
            docker=FakeDocker(),
            fs=fs,
            registry_path=tmp_path / "registry.toml",
        )


def test_remove_plan_refuses_unknown_and_manifestless(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.toml"
    with pytest.raises(StackError, match="not registered"):
        remove_instance_plan(
            name="ghost",
            registry_path=registry_path,
            fs=FakeFs(),
            docker=FakeDocker(),
            remove_data=False,
        )
    upsert_registry_entry(
        registry_path,
        RegistryEntry(name="dev", dir=tmp_path / "somewhere", http_port=8069),
    )
    with pytest.raises(StackError, match="refusing"):
        remove_instance_plan(
            name="dev",
            registry_path=registry_path,
            fs=FakeFs(),
            docker=FakeDocker(),
            remove_data=False,
        )


def test_remove_plan_apply_keeps_volumes_by_default(tmp_path: Path) -> None:
    fs, docker, registry_path, stack_dir = create_and_apply(tmp_path)
    steps = remove_instance_plan(
        name="dev", registry_path=registry_path, fs=fs, docker=docker, remove_data=False
    )
    apply_steps(steps)
    assert not stack_dir.exists()
    assert docker.compose_calls[-1][0] == ("down", "--remove-orphans")
    registry = load_registry_safe(registry_path)
    assert "dev" not in registry


def test_remove_plan_with_data_destroys_volumes(tmp_path: Path) -> None:
    fs, docker, registry_path, _ = create_and_apply(tmp_path)
    steps = remove_instance_plan(
        name="dev", registry_path=registry_path, fs=fs, docker=docker, remove_data=True
    )
    apply_steps(steps)
    assert docker.compose_calls[-1][0] == ("down", "--remove-orphans", "-v")


def test_compose_action_mapping(tmp_path: Path) -> None:
    docker = FakeDocker()
    compose_action("start", tmp_path, docker)
    compose_action("stop", tmp_path, docker)
    compose_action("restart", tmp_path, docker)
    assert [call[0] for call in docker.compose_calls] == [
        ("up", "-d"),
        ("stop",),
        ("restart",),
    ]
    with pytest.raises(StackError, match="unknown lifecycle action"):
        compose_action("explode", tmp_path, docker)


# --- small helpers -----------------------------------------------------------


def load_registry_entry(registry_path: Path, name: str) -> RegistryEntry | None:
    import tomllib

    data = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    entry = data.get("instances", {}).get(name)
    return RegistryEntry.model_validate(entry) if entry else None


def load_registry_safe(registry_path: Path) -> dict[str, object]:
    import tomllib

    data = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    return data.get("instances", {})
