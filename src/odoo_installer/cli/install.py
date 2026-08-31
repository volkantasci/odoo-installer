"""`odoo-installer install` — host prerequisites (plan-first)."""

from __future__ import annotations

from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.console import console, error, render_plan, render_results
from odoo_installer.core.plan import apply_steps
from odoo_installer.core.prereqs import host_install_plan
from odoo_installer.exceptions import OdooInstallerError


def install(
    *,
    apply_changes: Annotated[
        bool,
        typer.Option("--apply", help="Execute the plan (without it, this is a dry run)."),
    ] = False,
) -> None:
    """Install host prerequisites (docker engine, compose plugin, git).

    Never installs Odoo itself — Odoo runs in Docker stacks created with
    `odoo-installer instance create`.
    """
    container = deps.build()
    try:
        steps = host_install_plan(container.docker, container.system)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not steps:
        console.print("[green]✔[/green] all host prerequisites already satisfied")
        return
    if not apply_changes:
        render_plan(steps, "Host prerequisite install plan")
        return
    try:
        notes = apply_steps(steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(steps, notes)
