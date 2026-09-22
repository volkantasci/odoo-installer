"""`odoo-installer instance` — create and manage Odoo container stacks."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from odoo_installer.adapters.docker import ComposeContainerInfo
from odoo_installer.cli import deps
from odoo_installer.config import load_registry
from odoo_installer.console import console, error, progress_reporter, render_plan, render_registry
from odoo_installer.constants import DEFAULT_ODOO_IMAGE
from odoo_installer.core.health import instance_health
from odoo_installer.core.instances import (
    adopt_instance_plan,
    compose_action,
    create_instance_plan,
    detect_stack,
    instance_dir,
    instance_secret,
    load_manifest,
    remove_instance_plan,
    resolve_create_port,
    resolve_stack_extras,
    validate_instance_name,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import OdooInstallerError, StackError
from odoo_installer.schemas import StackExtras

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
    ingress_network: Annotated[
        str | None,
        typer.Option(
            "--ingress-network",
            help="Attach web to this external network under an alias and publish no host "
            "port (reverse-proxy routing); implies proxy_mode.",
        ),
    ] = None,
    ingress_alias: Annotated[
        str | None,
        typer.Option("--ingress-alias", help="Network alias (default: the instance name)."),
    ] = None,
    memory: Annotated[
        str | None,
        typer.Option("--memory", help="Web service memory limit, e.g. 2g (compose mem_limit)."),
    ] = None,
    cpus: Annotated[
        float | None,
        typer.Option("--cpus", help="Web service CPU limit (compose cpus)."),
    ] = None,
    proxy_mode: Annotated[
        bool | None,
        typer.Option(
            "--proxy-mode/--no-proxy-mode",
            help="odoo.conf proxy_mode (default: on with --ingress-network, off otherwise).",
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option("--workers", help="odoo.conf workers (default: threaded)."),
    ] = None,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Create an Odoo stack: render compose/.env/odoo.conf, start it, wait for health."""
    container = deps.build()
    try:
        instance_name = validate_instance_name(name)
        stack_dir = instance_dir(container.config, instance_name, dir_opt)
        manifest = load_manifest(container.fs, stack_dir)
        extras = StackExtras(
            ingress_network=ingress_network,
            ingress_alias=ingress_alias,
            memory_limit=memory,
            cpus=cpus,
            proxy_mode=proxy_mode,
            workers=workers,
        )
        effective = resolve_stack_extras(manifest, extras)
        if effective.ingress_network is not None and http_port is None:
            port = manifest.http_port if manifest is not None else 0
        else:
            port = resolve_create_port(
                system=container.system,
                config=container.config,
                fs=container.fs,
                stack_dir=stack_dir,
                requested=http_port,
                registry_path=container.registry_path,
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
            extras=extras,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None

    if not apply_changes:
        where = (
            f"ingress alias {plan.extras.ingress_alias or plan.name!r} "
            f"on {plan.extras.ingress_network}"
            if plan.extras.ingress_network
            else f"http port {plan.http_port}"
        )
        render_plan(plan.steps, f"Instance create plan: {plan.name} ({where})")
        return
    try:
        apply_steps(plan.steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if plan.extras.ingress_network:
        console.print(
            f"[green]✔[/green] instance {plan.name!r} ready on ingress network "
            f"{plan.extras.ingress_network!r} (alias {plan.extras.ingress_alias or plan.name})"
        )
    else:
        console.print(
            f"[green]✔[/green] instance {plan.name!r} ready at http://localhost:{plan.http_port}"
        )


@app.command("list")
def list_instances(
    *,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of a table."),
    ] = False,
) -> None:
    """List registered instances."""
    container = deps.build()
    registry = load_registry(container.registry_path)
    if as_json:
        typer.echo(
            json.dumps(
                [entry.model_dump(mode="json") for entry in registry.instances.values()],
                indent=2,
            )
        )
        return
    if not registry.instances:
        console.print("no instances registered")
        return
    render_registry(list(registry.instances.values()))


@app.command("show")
def show(
    name: str,
    *,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of rich text."),
    ] = False,
) -> None:
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
    containers, reachable = _containers_for(container, stack_dir)
    if as_json:
        payload = manifest.model_dump(mode="json")
        payload["reachable"] = reachable
        payload["containers"] = [asdict(info) for info in containers]
        typer.echo(json.dumps(payload, indent=2))
        return
    console.print(
        f"[bold]{manifest.name}[/bold] — Odoo {manifest.odoo_version} ({manifest.image}), "
        f"postgres {manifest.pg_tag}"
    )
    console.print(f"  directory: {manifest.dir}")
    if manifest.ingress_network:
        console.print(
            f"  ingress:   alias {manifest.ingress_alias or manifest.name} on "
            f"{manifest.ingress_network} (no host port)"
        )
    else:
        console.print(f"  http port: {manifest.http_port}")
    if manifest.memory_limit or manifest.cpus:
        limits = f"memory {manifest.memory_limit}" if manifest.memory_limit else ""
        limits += (", " if limits else "") + (f"cpus {manifest.cpus}" if manifest.cpus else "")
        console.print(f"  limits:    {limits}")
    console.print(f"  adopted:   {'yes' if manifest.adopted else 'no'}")
    if not reachable:
        console.print("[yellow]⚠ stack is not reachable via the container runtime[/yellow]")
        return
    if not containers:
        console.print("[yellow]⚠ no containers exist for this stack (never started?)[/yellow]")
        return
    for info in containers:
        console.print(f"  {info.service or info.name}: [bold]{info.state}[/bold] ({info.image})")


def _containers_for(
    container: deps.Container, stack_dir: Path
) -> tuple[list[ComposeContainerInfo], bool]:
    """Containers of the stack, plus whether the runtime answered at all."""
    try:
        return container.docker.compose_containers(stack_dir), True
    except OdooInstallerError:
        return [], False


@app.command("health")
def health(
    name: str,
    *,
    wait: Annotated[
        int,
        typer.Option("--wait", help="Poll up to this many seconds before reporting."),
    ] = 0,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON instead of rich text."),
    ] = False,
) -> None:
    """Probe the instance: HTTP /web/health (published) or the container healthcheck."""
    container = deps.build()
    try:
        stack_dir = _stack_dir_for(container, name)
        manifest = load_manifest(container.fs, stack_dir)
        if manifest is None:
            raise StackError(f"no manifest for instance {name!r} in {stack_dir}")
        healthy, detail = instance_health(manifest, container.docker, wait_s=wait)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if as_json:
        typer.echo(json.dumps({"instance": name, "healthy": healthy, "detail": detail}, indent=2))
    elif healthy:
        console.print(f"[green]✔ healthy[/green] {name}: {detail}")
    else:
        console.print(f"[red]✘ unhealthy[/red] {name}: {detail}")
    if not healthy:
        raise typer.Exit(code=1)


@app.command("logs")
def logs(
    name: str,
    *,
    tail: Annotated[int, typer.Option("--tail", help="Number of lines to show.")] = 80,
) -> None:
    """Show the stack's combined service logs (compose logs --tail)."""
    container = deps.build()
    try:
        stack_dir = _stack_dir_for(container, name)
        manifest = load_manifest(container.fs, stack_dir)
        if manifest is None:
            raise StackError(f"no manifest for instance {name!r} in {stack_dir}")
        output = container.docker.compose(["logs", "--tail", str(tail)], stack_dir)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    typer.echo(output or "(no logs)")


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
        apply_steps(steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] instance {name!r} removed")


@app.command("secret")
def secret(
    name: str,
    *,
    key: Annotated[
        str,
        typer.Option(
            "--key",
            help="Env key to print (default: ADMIN_PASSWD, the Odoo master password).",
        ),
    ] = "ADMIN_PASSWD",
) -> None:
    """Print an instance secret from .env (default: the Odoo master password)."""
    container = deps.build()
    try:
        stack_dir = _stack_dir_for(container, name)
        value = instance_secret(container.fs, stack_dir, key)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    typer.echo(value)


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
        apply_steps(plan.steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] instance {plan.name!r} adopted (read-mostly)")
