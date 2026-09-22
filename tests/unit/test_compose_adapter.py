"""Unit tests for the runtime-agnostic compose adapter (offline, no containers).

`resolve_runtime` gets injected which/reachable probes; the ps-JSON normalizers
are exercised with recorded docker- and podman-shaped payloads.
"""

from __future__ import annotations

import pytest

from odoo_installer.adapters.docker import (
    ComposeAdapter,
    _normalize_labels,
    _normalize_ports,
    host_port_for,
    resolve_runtime,
)
from odoo_installer.exceptions import PrerequisiteError


def _which_factory(present: set[str]):
    return lambda binary: f"/usr/bin/{binary}" if binary in present else None


def test_resolve_runtime_explicit_podman() -> None:
    assert resolve_runtime("podman", which=_which_factory({"podman"})) == "podman"


def test_resolve_runtime_explicit_binary_missing_fails() -> None:
    with pytest.raises(PrerequisiteError, match="binary is not on PATH"):
        resolve_runtime("docker", which=_which_factory({"podman"}))


def test_resolve_runtime_invalid_value_fails() -> None:
    with pytest.raises(PrerequisiteError, match="invalid container_runtime"):
        resolve_runtime("containerd", which=_which_factory({"containerd"}))


def test_resolve_runtime_auto_prefers_podman() -> None:
    runtime = resolve_runtime(
        "auto", which=_whereis({"podman", "docker"}), reachable=lambda _r: True
    )
    assert runtime == "podman"


def test_resolve_runtime_auto_falls_back_to_docker_when_podman_dead() -> None:
    def reachable(candidate: str) -> bool:
        return candidate == "docker"

    runtime = resolve_runtime("auto", which=_whereis({"podman", "docker"}), reachable=reachable)
    assert runtime == "docker"


def test_resolve_runtime_auto_falls_back_when_podman_missing() -> None:
    runtime = resolve_runtime("auto", which=_whereis({"docker"}), reachable=lambda _r: True)
    assert runtime == "docker"


def test_resolve_runtime_auto_nothing_usable_fails() -> None:
    with pytest.raises(PrerequisiteError, match="no usable container runtime"):
        resolve_runtime("auto", which=_whereis({"podman"}), reachable=lambda _r: False)


def _whereis(present: set[str]):
    def which(binary: str) -> str | None:
        return f"/usr/bin/{binary}" if binary in present else None

    return which


def test_adapter_carries_chosen_runtime() -> None:
    adapter = ComposeAdapter(runtime="podman")
    assert adapter.runtime == "podman"
    assert ComposeAdapter().runtime == "docker"


def test_docker_shaped_labels_and_ports_pass_through() -> None:
    labels = _normalize_labels("com.docker.compose.service=web,com.docker.compose.project=dev")
    assert labels["com.docker.compose.service"] == "web"
    ports = _normalize_ports("0.0.0.0:8069->8069/tcp, [::]:8069->8069/tcp")
    assert host_port_for(ports, 8069) == 8069


def test_podman_shaped_labels_and_ports_normalize() -> None:
    labels = _normalize_labels(
        {"com.docker.compose.service": "web", "com.docker.compose.project": "dev"}
    )
    assert labels["com.docker.compose.service"] == "web"
    labels_none = _normalize_labels(None)
    assert labels_none == {}
    ports = _normalize_ports(
        [
            {
                "host_ip": "",
                "container_port": 8069,
                "host_port": 18069,
                "protocol": "tcp",
                "range": 1,
            },
            {"container_port": 5432, "host_port": None, "protocol": "tcp"},
        ]
    )
    assert "0.0.0.0:18069->8069/tcp" in ports
    assert host_port_for(ports, 8069) == 18069
    assert _normalize_ports(None) == ""
    assert host_port_for(_normalize_ports([]), 8069) is None
