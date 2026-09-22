"""`odoo-installer backup` — per-instance database + filestore backups.

`create` is additive and runs directly (pg_dump is MVCC-consistent while Odoo
serves); `prune` and `restore` are plan-first, and restore additionally requires
`--yes` because it replaces the database and filestore wholesale.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.cli.common import resolve_instance
from odoo_installer.console import console, error, progress_reporter, render_plan
from odoo_installer.core.backup import (
    create_backup,
    find_backup,
    list_backups,
    prune_backups_plan,
    resolve_backup_db,
    restore_backup_plan,
    verify_backup,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import OdooInstallerError

app = typer.Typer(no_args_is_help=True, help="Backup and restore instance data.")

_APPLY_HELP = "Execute the plan (without it, this is a dry run)."
_INSTANCE_HELP = "Target instance (default: the only registered instance)."


@app.command("create")
def create(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    db: Annotated[
        str | None,
        typer.Option("--db", help="Database to back up (default: the only Odoo database)."),
    ] = None,
) -> None:
    """Stream a backup now: pg_dump -Fc + filestore tar + checksummed manifest."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        db_name = db or resolve_backup_db(container.docker, manifest)
        info = create_backup(
            container.docker,
            container.fs,
            manifest,
            db=db_name,
            hook=container.config.backup_hook,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    total = info.db_bytes + info.filestore_bytes
    console.print(
        f"[green]✔[/green] backup {info.timestamp} of {info.db!r}: "
        f"db {info.db_bytes} bytes + filestore {info.filestore_bytes} bytes "
        f"({total} total) in {info.path}"
    )
    if container.config.backup_hook:
        console.print("[dim]offsite hook ran (backup_hook)[/dim]")


@app.command("list")
def list_backups_cmd(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of a table."),
    ] = False,
) -> None:
    """List backups of an instance (newest last)."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        backups = list_backups(container.fs, manifest)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if as_json:
        typer.echo(json.dumps([b.to_dict() for b in backups], indent=2))
        return
    if not backups:
        console.print("no backups")
        return
    for backup in backups:
        console.print(
            f"  {backup.timestamp}  db {backup.db!r}  "
            f"{backup.db_bytes} + {backup.filestore_bytes} bytes"
        )


@app.command("verify")
def verify(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    backup: Annotated[
        str | None,
        typer.Option("--backup", help="Timestamp to verify (default: all backups)."),
    ] = None,
) -> None:
    """Recompute checksums against the backup manifest; exits 1 on any mismatch."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        targets = (
            [find_backup(container.fs, manifest, backup)]
            if backup is not None
            else list_backups(container.fs, manifest)
        )
        failures: list[str] = []
        for target in targets:
            problems = verify_backup(target)
            if problems:
                failures.extend(f"{target.timestamp}: {problem}" for problem in problems)
                console.print(f"[red]✘[/red] {target.timestamp}: {'; '.join(problems)}")
            else:
                console.print(f"[green]✔[/green] {target.timestamp}: checksums match")
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if failures:
        raise typer.Exit(code=1)


@app.command("prune")
def prune(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    keep: Annotated[int, typer.Option("--keep", help="Number of newest backups to keep.")] = 3,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Delete all but the newest `--keep` backups. Dry-run by default."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        steps = prune_backups_plan(container.fs, manifest, keep=keep)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not steps:
        console.print(f"[green]✔[/green] nothing to prune (kept {keep} newest)")
        return
    if not apply_changes:
        render_plan(steps, f"Backup prune plan: {manifest.name} (keep {keep})")
        return
    try:
        apply_steps(steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] pruned {len(steps)} backup(s)")


@app.command("restore")
def restore(
    timestamp: str,
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm the restore (required together with --apply)."),
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Restore database + filestore from a backup. Dry-run; --apply --yes runs."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        backup_info = find_backup(container.fs, manifest, timestamp)
        steps = restore_backup_plan(container.docker, container.fs, manifest, backup_info)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not (apply_changes and yes):
        render_plan(steps, f"Backup restore plan: {manifest.name} <- {timestamp}")
        console.print(
            f"[red]This replaces database {backup_info.db!r} and the filestore with "
            f"the state from {timestamp}.[/red]"
        )
        if apply_changes and not yes:
            console.print("[yellow]add --yes to confirm the restore[/yellow]")
        return
    try:
        apply_steps(steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] restored {backup_info.db!r} from {timestamp}")
