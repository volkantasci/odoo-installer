"""Run odoo CLI commands inside the web container (alternate port convention).

Install/upgrade runs use --stop-after-init on RUNNER_HTTP_PORT (8071) so they never
clash with the serving process — same convention as the manual workflow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.constants import RUNNER_HTTP_PORT


def install_modules(
    docker: ComposeLike,
    stack_dir: Path,
    web_service: str,
    db: str,
    modules: list[str],
    *,
    upgrade: bool = False,
    timeout_s: int = 1800,
) -> str:
    """`odoo -i/-u` on RUNNER_HTTP_PORT (8071) so the serving process never clashes.

    NOTE: Odoo's own `-r`/`-w` flags are the DATABASE connection user/password,
    not the app's admin login — never pass credentials here. First-time admin
    credentials are set through the ORM via `set_admin_credentials` below.
    """
    flag = "-u" if upgrade else "-i"
    args = [
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
    ]
    return docker.compose(args, stack_dir, timeout_s=timeout_s)


def set_admin_credentials(
    docker: ComposeLike,
    stack_dir: Path,
    web_service: str,
    db: str,
    login: str,
    password: str,
    *,
    timeout_s: int = 300,
) -> str:
    """Set the database's admin login/password through Odoo's ORM (odoo shell).

    A raw SQL UPDATE would bypass password hashing and brick the login; the
    shell writes through res.users, so passlib hashing and related caches stay
    correct. Only ever run this right after a database's first initialization —
    later runs would silently reset a password the user may have changed.
    """
    script = (
        "user = env.ref('base.user_admin')\n"
        f"user.write({{'login': {login!r}, 'password': {password!r}}})\n"
        "env.cr.commit()\n"
        f"print('admin credentials set for {login}')\n"
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as fh:
        fh.write(script)
        script_path = Path(fh.name)
    try:
        docker.compose_transfer(
            ["exec", "-T", web_service, "odoo", "shell", "-d", db, "--no-http"],
            stack_dir,
            stdin_path=script_path,
            timeout_s=timeout_s,
        )
    finally:
        script_path.unlink(missing_ok=True)
    return f"admin login {login!r} password set (ORM-hashed)"
