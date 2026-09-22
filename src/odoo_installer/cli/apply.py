"""`odoo-installer apply` — converge an instance to an odoo-stack.toml spec."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.console import console, error, progress_reporter, render_plan
from odoo_installer.core.apply import build_apply_plan
from odoo_installer.core.plan import apply_steps
from odoo_installer.core.spec import load_spec
from odoo_installer.exceptions import OdooInstallerError


def apply(
    spec_path: Annotated[
        Path,
        typer.Argument(
            help="Path to odoo-stack.toml (the desired state of one instance).",
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
        ),
    ],
    *,
    apply_changes: Annotated[
        bool,
        typer.Option("--apply", help="Execute the plan (without it, this is a dry run)."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the plan as machine-readable JSON."),
    ] = False,
) -> None:
    """Converge an instance to its spec: stack, OCA repos, databases, modules.

    Idempotent — re-running on a converged spec reports every step as satisfied.
    On a fresh stack, repo/database/module steps are planned in detail only once
    the stack exists (the dry run shows that as one convergence step).
    """
    container = deps.build()
    try:
        spec = load_spec(spec_path)
        plan = build_apply_plan(
            spec,
            config=container.config,
            docker=container.docker,
            fs=container.fs,
            github=container.github,
            git=container.git,
            system=container.system,
            registry_path=container.registry_path,
            tested_path=container.tested_path,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "instance": plan.name,
                    "stack_dir": str(plan.stack_dir),
                    "created": plan.created,
                    "steps": [
                        {
                            "index": index,
                            "description": step.description,
                            "already_satisfied": step.already_satisfied,
                        }
                        for index, step in enumerate(plan.steps, start=1)
                    ],
                },
                indent=2,
            )
        )
        if not apply_changes:
            raise typer.Exit(code=0)

    if not apply_changes:
        title = (
            f"Apply plan: {plan.name} ({'new instance' if plan.created else 'existing instance'})"
        )
        render_plan(plan.steps, title)
        return
    try:
        apply_steps(plan.steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] instance {plan.name!r} converged to {spec_path.name}")
