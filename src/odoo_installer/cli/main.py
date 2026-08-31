"""Typer application for the odoo-installer CLI.

Command groups attach here milestone by milestone: M1 doctor + config, M2 install +
instance, M3 db (adoption), M4 module, M5 test.
"""

from __future__ import annotations

from typing import Annotated

import typer

from odoo_installer import __version__
from odoo_installer.cli import config as config_cli
from odoo_installer.cli import db as db_cli
from odoo_installer.cli import doctor as doctor_cli
from odoo_installer.cli import install as install_cli
from odoo_installer.cli import instance as instance_cli
from odoo_installer.cli import module as module_cli
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

app.add_typer(config_cli.app, name="config")
app.add_typer(db_cli.app, name="db")
app.add_typer(instance_cli.app, name="instance")
app.add_typer(module_cli.app, name="module")
app.command(name="doctor")(doctor_cli.doctor)
app.command(name="install")(install_cli.install)


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
