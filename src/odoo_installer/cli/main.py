"""Typer application for the odoo-installer CLI.

M0 scope: version reporting only. Milestones M1+ attach command groups here
(doctor, install, instance, module, db, test, config).
"""

from __future__ import annotations

from typing import Annotated

import typer

from odoo_installer import __version__
from odoo_installer.constants import APP_NAME


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{APP_NAME} {__version__}")
        raise typer.Exit


app = typer.Typer(
    name=APP_NAME,
    no_args_is_help=True,
    help="Install, configure and manage Odoo 19.0 Docker stacks with OCA modules.",
)


@app.callback()
def main(
    *,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Manage Odoo 19.0 Docker stacks, OCA modules and their tests."""


@app.command()
def version() -> None:
    """Print the installed odoo-installer version."""
    typer.echo(__version__)
