"""Tests for instance health probing (probe and runtime injected; fully offline)."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker

from odoo_installer.core.health import instance_health
from odoo_installer.schemas import InstanceManifest


def make_manifest(*, http_port: int = 8069) -> InstanceManifest:
    return InstanceManifest(
        name="dev",
        dir=Path("/tmp/oii-dev"),
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=http_port,
    )


def test_published_instance_probes_http_200() -> None:
    calls: list[str] = []

    def probe(url: str) -> tuple[int, str]:
        calls.append(url)
        return 200, "GET -> 200"

    ok, detail = instance_health(make_manifest(), FakeDocker(), probe=probe)
    assert ok is True
    assert calls == ["http://localhost:8069/web/health"]
    assert "200" in detail


def test_published_instance_http_500_is_unhealthy() -> None:
    ok, detail = instance_health(
        make_manifest(), FakeDocker(), probe=lambda _url: (500, "GET -> 500")
    )
    assert ok is False
    assert "500" in detail


def test_published_instance_connection_failure_is_unhealthy() -> None:
    ok, _detail = instance_health(
        make_manifest(), FakeDocker(), probe=lambda _url: (0, "connection refused")
    )
    assert ok is False


def test_ingress_instance_uses_container_healthcheck() -> None:
    manifest = make_manifest(http_port=0)
    docker = FakeDocker()
    ok, detail = instance_health(manifest, docker)
    assert ok is True
    assert docker.health_checks == ["dev-web-1"]
    assert "healthcheck" in detail


def test_ingress_instance_unhealthy_container() -> None:
    manifest = make_manifest(http_port=0)
    ok, _detail = instance_health(manifest, FakeDocker(healthy=False))
    assert ok is False


def test_wait_retries_until_deadline() -> None:
    attempts: list[int] = []

    def flaky(_url: str) -> tuple[int, str]:
        attempts.append(1)
        return (200, "ok") if len(attempts) >= 3 else (0, "refused")

    ok, _detail = instance_health(
        make_manifest(), FakeDocker(), wait_s=10, poll_s=0.01, probe=flaky
    )
    assert ok is True
    assert len(attempts) == 3


def test_wait_reports_last_failure() -> None:
    ok, detail = instance_health(
        make_manifest(),
        FakeDocker(),
        wait_s=0.05,
        poll_s=0.02,
        probe=lambda _url: (0, "connection refused"),
    )
    assert ok is False
    assert "connection refused" in detail
