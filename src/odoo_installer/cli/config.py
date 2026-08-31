"""`odoo-installer config` — show or edit global configuration."""

from __future__ import annotations

import json
import tomllib
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.config import (
    default_config_path,
    save_global_config,
    set_config_value,
)
from odoo_installer.console import console, error
from odoo_installer.exceptions import ConfigError
from odoo_installer.schemas import GlobalConfig


def _edit_text(text: str, extension: str = ".toml") -> str | None:
    """Open $EDITOR (or VISUAL, else vi) on a temp file; None on editor failure."""
    import os
    import shlex
    import subprocess
    import tempfile

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    fd, tmp_name = tempfile.mkstemp(suffix=extension)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        result = subprocess.run([*shlex.split(editor), tmp_name], check=False)
        if result.returncode != 0:
            return None
        with open(tmp_name, encoding="utf-8") as fh:
            return fh.read()
    finally:
        os.unlink(tmp_name)


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


@app.command("edit")
def edit() -> None:
    """Open the config file in $EDITOR; the result is validated before saving."""
    container = deps.build()
    path = container.config_path
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        edited = _edit_text(original)
    except Exception as exc:
        error(f"editor failed: {exc}")
        raise typer.Exit(code=1) from None
    if edited is None:
        error("editor exited with an error; nothing saved")
        raise typer.Exit(code=1) from None
    if edited == original:
        console.print("[dim]no changes[/dim]")
        return
    try:
        updated = GlobalConfig.model_validate(tomllib.loads(edited))
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        error(f"edited config is invalid, nothing saved: {exc}")
        raise typer.Exit(code=1) from None
    save_global_config(updated, path)
    console.print(f"[green]✔[/green] config saved: {path}")


@app.command("path")
def config_path() -> None:
    """Print the config file path."""
    typer.echo(default_config_path())
