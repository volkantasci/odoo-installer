"""`odoo-installer doctor` — host prerequisite checks."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.console import render_checks
from odoo_installer.core.prereqs import run_doctor
from odoo_installer.schemas import CheckStatus


def doctor(
    *,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of a table."),
    ] = False,
) -> None:
    """Check host prerequisites for managing Odoo Docker stacks.

    Exits with code 4 when a critical check fails.
    """
    container = deps.build()
    checks = run_doctor(
        container.docker, container.system, container.github, container.fs, container.config
    )
    if as_json:
        typer.echo(json.dumps([check.model_dump(mode="json") for check in checks], indent=2))
    else:
        render_checks(checks)
    if any(check.status is CheckStatus.FAIL for check in checks):
        raise typer.Exit(code=4)
