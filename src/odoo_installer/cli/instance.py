"""`odoo-installer instance` — create and manage Odoo Docker stacks."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.config import load_registry
from odoo_installer.console import console, error, render_plan, render_registry, render_results
from odoo_installer.constants import DEFAULT_ODOO_IMAGE
from odoo_installer.core.instances import (
    adopt_instance_plan,
    compose_action,
    create_instance_plan,
    detect_stack,
    instance_dir,
    load_manifest,
    remove_instance_plan,
    resolve_create_port,
    validate_instance_name,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import OdooInstallerError, StackError

app = typer.Typer(no_args_is_help=True, help="Create and manage Odoo Docker stacks.")

_APPLY_HELP = "Execute the plan (without it, this is a dry run)."


@app.command("create")
def create(
    name: str,
    *,
    dir_opt: Annotated[
        Path | None,
        typer.Option("--dir", help="Stack directory (default: <instances_root>/<name>)."),
    ] = None,
    http_port: Annotated[
        int | None,
        typer.Option(
            "--http-port", help="Host HTTP port (default: first free in the configured range)."
        ),
    ] = None,
    image: Annotated[
        str | None,
        typer.Option("--image", help=f"Odoo image (default: {DEFAULT_ODOO_IMAGE})."),
    ] = None,
    pg_tag: Annotated[
        int | None,
        typer.Option("--pg-tag", help="Postgres image tag (default from config)."),
    ] = None,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Create an Odoo stack: render compose/.env/odoo.conf, start it, wait for health."""
    container = deps.build()
    try:
        instance_name = validate_instance_name(name)
        stack_dir = instance_dir(container.config, instance_name, dir_opt)
        port = resolve_create_port(
            system=container.system,
            config=container.config,
            fs=container.fs,
            stack_dir=stack_dir,
            requested=http_port,
        )
        plan = create_instance_plan(
            name=instance_name,
            stack_dir=stack_dir,
            http_port=port,
            odoo_image=image or DEFAULT_ODOO_IMAGE,
            pg_tag=pg_tag or container.config.default_pg_tag,
            config=container.config,
            docker=container.docker,
            fs=container.fs,
            registry_path=container.registry_path,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None

    if not apply_changes:
        render_plan(plan.steps, f"Instance create plan: {plan.name} (http port {plan.http_port})")
        return
    try:
        notes = apply_steps(plan.steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(plan.steps, notes)
    console.print(
        f"[green]✔[/green] instance {plan.name!r} ready at http://localhost:{plan.http_port}"
    )


@app.command("list")
def list_instances() -> None:
    """List registered instances."""
    container = deps.build()
    registry = load_registry(container.registry_path)
    if not registry.instances:
        console.print("no instances registered")
        return
    render_registry(list(registry.instances.values()))


@app.command("show")
def show(name: str) -> None:
    """Show one instance: manifest details and container state."""
    container = deps.build()
    try:
        stack_dir = _stack_dir_for(container, name)
        manifest = load_manifest(container.fs, stack_dir)
        if manifest is None:
            raise StackError(f"no manifest for instance {name!r} in {stack_dir}")
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(
        f"[bold]{manifest.name}[/bold] — Odoo {manifest.odoo_version} ({manifest.image}), "
        f"postgres {manifest.pg_tag}"
    )
    console.print(f"  directory: {manifest.dir}")
    console.print(f"  http port: {manifest.http_port}")
    console.print(f"  adopted:   {'yes' if manifest.adopted else 'no'}")
    try:
        console.print(container.docker.compose(["ps"], stack_dir))
    except OdooInstallerError:
        console.print("[dim]stack is not reachable via docker compose[/dim]")


@app.command("start")
def start(name: str) -> None:
    """Start the instance's stack (up -d; adopted stacks: compose start, no recreate)."""
    _lifecycle(name, "start")


@app.command("stop")
def stop(name: str) -> None:
    """Stop the instance's stack (docker compose stop)."""
    _lifecycle(name, "stop")


@app.command("restart")
def restart(name: str) -> None:
    """Restart the instance's stack (docker compose restart)."""
    _lifecycle(name, "restart")


@app.command("remove")
def remove(
    name: str,
    *,
    remove_data: Annotated[
        bool,
        typer.Option(
            "--remove-data",
            help="Also destroy the stack's named data volumes (compose down -v).",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirm the removal (required together with --apply)."),
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Remove an instance — adopted stacks included. Dry-run by default; --apply --yes runs."""
    container = deps.build()
    try:
        steps = remove_instance_plan(
            name=name,
            registry_path=container.registry_path,
            fs=container.fs,
            docker=container.docker,
            remove_data=remove_data,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not (apply_changes and yes):
        render_plan(steps, f"Instance remove plan: {name}")
        if apply_changes and not yes:
            console.print("[yellow]add --yes to confirm the removal[/yellow]")
        return
    try:
        notes = apply_steps(steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(steps, notes)
    console.print(f"[green]✔[/green] instance {name!r} removed")


def _stack_dir_for(container: deps.Container, name: str) -> Path:
    registry = load_registry(container.registry_path)
    entry = registry.instances.get(name)
    if entry is not None:
        return entry.dir
    return instance_dir(container.config, name, None)


def _lifecycle(name: str, action: str) -> None:
    container = deps.build()
    try:
        stack_dir = _stack_dir_for(container, name)
        manifest = load_manifest(container.fs, stack_dir)
        if manifest is None:
            raise StackError(f"no manifest for instance {name!r} in {stack_dir}")
        note = compose_action(action, stack_dir, container.docker, adopted=manifest.adopted)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] {name}: {action} — {note}")


@app.command("adopt")
def adopt(
    dir_path: Annotated[
        Path,
        typer.Argument(
            help="Directory of the existing compose stack.",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ],
    *,
    name_opt: Annotated[
        str | None,
        typer.Option("--name", help="Instance name (default: compose project name)."),
    ] = None,
    db_user: Annotated[
        str, typer.Option("--db-user", help="Postgres role inside the db container.")
    ] = "odoo",
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Adopt an existing compose stack; managed read-mostly (no file rewrites)."""
    container = deps.build()
    try:
        detected = detect_stack(container.docker, dir_path)
        instance_name = validate_instance_name(name_opt or detected.project)
        plan = adopt_instance_plan(
            name=instance_name,
            stack_dir=dir_path,
            detected=detected,
            db_user=db_user,
            fs=container.fs,
            registry_path=container.registry_path,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(
        f"detected: project [bold]{detected.project}[/bold], web service "
        f"[bold]{detected.web_service}[/bold] ({detected.web_image}) on port "
        f"{detected.http_port}, db service [bold]{detected.db_service}[/bold] "
        f"({detected.db_image})"
    )
    if not apply_changes:
        render_plan(plan.steps, f"Instance adopt plan: {plan.name}")
        return
    try:
        notes = apply_steps(plan.steps)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_results(plan.steps, notes)
    console.print(f"[green]✔[/green] instance {plan.name!r} adopted (read-mostly)")
