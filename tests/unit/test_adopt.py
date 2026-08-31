"""Tests for stack detection and adoption (read-mostly management)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs

from odoo_installer.core.instances import (
    adopt_instance_plan,
    compose_action,
    detect_stack,
    load_manifest,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import StackError

LIVE_STACK = [
    {
        "name": "odoo-docker-web-1",
        "service": "web",
        "project": "odoo-docker",
        "image": "odoo:19",
        "ports": "0.0.0.0:8069->8069/tcp, [::]:8069->8069/tcp, 0.0.0.0:8072->8072/tcp",
    },
    {"name": "odoo-docker-db-1", "service": "db", "project": "odoo-docker", "image": "postgres:17"},
]


def test_detect_stack_classifies_services(tmp_path: Path) -> None:
    docker = FakeDocker(containers=LIVE_STACK)
    detected = detect_stack(docker, tmp_path)
    assert detected.project == "odoo-docker"
    assert detected.web_service == "web"
    assert detected.db_service == "db"
    assert detected.web_image == "odoo:19"
    assert detected.db_image == "postgres:17"
    # the published host port mapping to container 8069 — not 8072
    assert detected.http_port == 8069


def test_detect_stack_requires_containers(tmp_path: Path) -> None:
    with pytest.raises(StackError, match="no compose containers"):
        detect_stack(FakeDocker(), tmp_path)


def test_detect_stack_requires_db_service(tmp_path: Path) -> None:
    docker = FakeDocker(containers=[LIVE_STACK[0]])
    with pytest.raises(StackError, match="cannot identify the web/db services"):
        detect_stack(docker, tmp_path)


def test_detect_stack_requires_web_service(tmp_path: Path) -> None:
    docker = FakeDocker(containers=[LIVE_STACK[1]])
    with pytest.raises(StackError, match="cannot identify the web/db services"):
        detect_stack(docker, tmp_path)


def test_detect_stack_requires_published_8069(tmp_path: Path) -> None:
    docker = FakeDocker(containers=[{**LIVE_STACK[0], "ports": ""}, LIVE_STACK[1]])
    with pytest.raises(StackError, match="publishes no host port"):
        detect_stack(docker, tmp_path)


def test_adopt_plan_writes_adopted_manifest(tmp_path: Path) -> None:
    fs = FakeFs()
    registry_path = tmp_path / "registry.toml"
    docker = FakeDocker(containers=LIVE_STACK)
    detected = detect_stack(docker, tmp_path)
    plan = adopt_instance_plan(
        name="odoo-docker",
        stack_dir=tmp_path,
        detected=detected,
        db_user="odoo",
        fs=fs,
        registry_path=registry_path,
    )
    apply_steps(plan.steps)
    manifest = load_manifest(fs, tmp_path)
    assert manifest is not None
    assert manifest.adopted is True
    assert manifest.name == "odoo-docker"
    assert manifest.http_port == 8069
    assert manifest.odoo_version == "19.0"
    assert manifest.db_service == "db"
    assert manifest.db_user == "odoo"
    assert manifest.image == "odoo:19"
    # registry marks the instance adopted
    import tomllib

    data = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    assert data["instances"]["odoo-docker"]["adopted"] is True


def test_adopt_refuses_already_managed_directory(tmp_path: Path) -> None:
    fs = FakeFs()
    registry_path = tmp_path / "registry.toml"
    detected = detect_stack(FakeDocker(containers=LIVE_STACK), tmp_path)
    first = adopt_instance_plan(
        name="odoo-docker",
        stack_dir=tmp_path,
        detected=detected,
        db_user="odoo",
        fs=fs,
        registry_path=registry_path,
    )
    apply_steps(first.steps)
    with pytest.raises(StackError, match="already has"):
        adopt_instance_plan(
            name="odoo-docker",
            stack_dir=tmp_path,
            detected=detected,
            db_user="odoo",
            fs=fs,
            registry_path=registry_path,
        )


def test_adopt_refuses_name_registered_for_other_dir(tmp_path: Path) -> None:
    fs = FakeFs()
    registry_path = tmp_path / "registry.toml"
    other_dir = tmp_path / "other"
    from odoo_installer.core.instances import upsert_registry_entry
    from odoo_installer.schemas import RegistryEntry

    upsert_registry_entry(
        registry_path, RegistryEntry(name="odoo-docker", dir=other_dir, http_port=8069)
    )
    detected = detect_stack(FakeDocker(containers=LIVE_STACK), tmp_path)
    with pytest.raises(StackError, match="already registered"):
        adopt_instance_plan(
            name="odoo-docker",
            stack_dir=tmp_path,
            detected=detected,
            db_user="odoo",
            fs=fs,
            registry_path=registry_path,
        )


def test_adopted_lifecycle_start_never_recreates(tmp_path: Path) -> None:
    docker = FakeDocker()
    compose_action("start", tmp_path, docker, adopted=True)
    compose_action("start", tmp_path, docker, adopted=False)
    assert [call[0] for call in docker.compose_calls] == [("start",), ("up", "-d")]
