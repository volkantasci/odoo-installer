"""Run odoo CLI commands inside the web container (alternate port convention).

Install/upgrade runs use --stop-after-init on RUNNER_HTTP_PORT (8071) so they never
clash with the serving process — same convention as the manual workflow.
"""

from __future__ import annotations

from pathlib import Path

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.constants import RUNNER_HTTP_PORT


def install_modules(
    docker: DockerLike,
    stack_dir: Path,
    web_service: str,
    db: str,
    modules: list[str],
    *,
    upgrade: bool = False,
    timeout_s: int = 1800,
) -> str:
    flag = "-u" if upgrade else "-i"
    return docker.compose(
        [
            "exec",
            "-T",
            web_service,
            "odoo",
            "-d",
            db,
            flag,
            ",".join(modules),
            "--stop-after-init",
            f"--http-port={RUNNER_HTTP_PORT}",
        ],
        stack_dir,
        timeout_s=timeout_s,
    )
