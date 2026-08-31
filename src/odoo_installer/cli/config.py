"""`odoo-installer config` — show or edit global configuration."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.config import default_config_path, set_config_value
from odoo_installer.console import console, error
from odoo_installer.exceptions import ConfigError

app = typer.Typer(no_args_is_help=True, help="Show or edit global configuration.")


@app.command("show")
def show(
    *,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print JSON instead of key = value lines."),
    ] = False,
) -> None:
    """Show the resolved global configuration."""
    container = deps.build()
    data = container.config.model_dump(mode="json")
    if as_json:
        typer.echo(json.dumps(data, indent=2))
    else:
        for key, value in data.items():
            console.print(f"[bold]{key}[/bold] = {value}")


@app.command("set")
def set_value(key: str, value: str) -> None:
    """Set one configuration value; unknown keys or bad values are rejected."""
    container = deps.build()
    try:
        updated = set_config_value(key, value, path=container.config_path)
    except ConfigError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] {key} = {updated.model_dump(mode='json')[key]}")


@app.command("path")
def config_path() -> None:
    """Print the config file path."""
    typer.echo(default_config_path())
