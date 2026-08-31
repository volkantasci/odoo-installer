"""`odoo-installer db` — manage databases of an instance via the db container.

Safety (DEVELOPMENT.md §7): the database name is always an explicit argument; drop/
reset are plan-first and execute only with `--apply --yes`; protected databases are
refused. On adopted stacks the CLI never touches the production database unless the
user passes its name explicitly through the guarded path.
"""

from __future__ import annotations

from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.config import load_registry
from odoo_installer.console import console, error, render_databases, render_plan, render_results
from odoo_installer.core.dbms import (
    create_database,
    drop_database_plan,
    list_databases,
    reset_database_plan,
)
from odoo_installer.core.instances import load_manifest
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import OdooInstallerError, StackError
from odoo_installer.schemas import InstanceManifest

app = typer.Typer(no_args_is_help=True, help="Manage databases of an Odoo instance.")

_APPLY_HELP = "Execute the plan (without it, this is a dry run)."
_INSTANCE_HELP = "Target instance (default: the only registered instance)."


def _resolve_instance(container: deps.Container, instance_opt: str | None) -> InstanceManifest:
    registry = load_registry(container.registry_path)
    if instance_opt is not None:
        entry = registry.instances.get(instance_opt)
        if entry is None:
            raise StackError(f"instance {instance_opt!r} is not registered")
    elif len(registry.instances) == 1:
        entry = next(iter(registry.instances.values()))
    else:
        names = ", ".join(sorted(registry.instances)) or "none"
        raise StackError(f"multiple instances registered ({names}); specify --instance")
    manifest = load_manifest(container.fs, entry.dir)
    if manifest is None:
        raise StackError(f"no manifest for instance at {entry.dir}")
    return manifest


@app.command("list")
def list_dbs(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
) -> None:
    """List the databases of the instance's db container."""
    container = deps.build()
    try:
        manifest = _resolve_instance(container, instance)
        databases = list_databases(
            container.docker, manifest.dir, manifest.db_service, manifest.db_user
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not databases:
        console.print("no databases found")
        return
    render_databases(databases)


@app.command("create")
def create_db(
    db_name: Annotated[str, typer.Argument(help="Database name (explicit, never defaulted).")],
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
) -> None:
    """Create an empty database; reports when it already exists."""
    container = deps.build()
    try:
        manifest = _resolve_instance(container, instance)
        note = create_database(
            container.docker, manifest.dir, manifest.db_service, manifest.db_user, db_name
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] database {db_name!r}: {note}")


@app.command("drop")
def drop_db(
    db_name: Annotated[str, typer.Argument(help="Database name (explicit, never defaulted).")],
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm the drop (required together with --apply).")
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Drop a database. Dry-run by default; execution requires --apply --yes."""
    container = deps.build()
    try:
        manifest = _resolve_instance(container, instance)
        steps = drop_database_plan(
            container.docker, manifest.dir, manifest.db_service, manifest.db_user, db_name
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not (apply_changes and yes):
        render_plan(steps, f"Database drop plan: {db_name!r} on instance {manifest.name!r}")
        console.print("[red]This destroys all data in the database.[/red]")
        if apply_changes and not yes:
            console.print("[yellow]add --yes to confirm the drop[/yellow]")
        return
    try:
        notes = apply_steps(steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(steps, notes)
    console.print(f"[green]✔[/green] database {db_name!r} dropped")


@app.command("reset")
def reset_db(
    db_name: Annotated[str, typer.Argument(help="Database name (explicit, never defaulted).")],
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    yes: Annotated[
        bool, typer.Option("--yes", help="Confirm the reset (required together with --apply).")
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Drop and recreate a database (empty). Requires --apply --yes."""
    container = deps.build()
    try:
        manifest = _resolve_instance(container, instance)
        steps = reset_database_plan(
            container.docker, manifest.dir, manifest.db_service, manifest.db_user, db_name
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not (apply_changes and yes):
        render_plan(steps, f"Database reset plan: {db_name!r} on instance {manifest.name!r}")
        console.print("[red]This destroys all data in the database.[/red]")
        if apply_changes and not yes:
            console.print("[yellow]add --yes to confirm the reset[/yellow]")
        return
    try:
        notes = apply_steps(steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(steps, notes)
    console.print(f"[green]✔[/green] database {db_name!r} reset (empty)")
