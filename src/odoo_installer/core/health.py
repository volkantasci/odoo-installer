"""Instance health probing: published-port HTTP or container healthcheck.

Published instances are probed over HTTP on localhost (what the operator sees);
ingress-mode instances (no published port) are probed through the runtime's
container healthcheck — the same signal `create --apply` waits for.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import InstanceManifest

Probe = Callable[[str], tuple[int, str]]


def instance_health(
    manifest: InstanceManifest,
    docker: ComposeLike,
    *,
    wait_s: int = 0,
    poll_s: float = 2.0,
    probe: Probe | None = None,
) -> tuple[bool, str]:
    """Return (healthy, detail); polls up to `wait_s` seconds when given."""
    deadline = time.monotonic() + wait_s
    while True:
        ok, detail = _probe_once(manifest, docker, probe)
        if ok or time.monotonic() >= deadline:
            return ok, detail
        time.sleep(poll_s)


def _probe_once(
    manifest: InstanceManifest, docker: ComposeLike, probe: Probe | None
) -> tuple[bool, str]:
    if manifest.http_port > 0:
        url = f"http://localhost:{manifest.http_port}/web/health"
        getter = probe or _http_get
        code, detail = getter(url)
        return code == 200, detail if code != 200 else f"GET {url} -> 200"
    container = f"{manifest.name}-{manifest.web_service}-1"
    try:
        status = docker.health_status(container)
    except StackError as exc:
        return False, str(exc)
    return status == "healthy", f"container {container} healthcheck: {status}"


def _http_get(url: str) -> tuple[int, str]:
    try:
        response = httpx.get(url, timeout=5.0)
    except httpx.HTTPError as exc:
        return 0, f"GET {url} failed: {exc}"
    return response.status_code, f"GET {url} -> {response.status_code}"
