"""Rich console rendering helpers for the CLI layer."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from odoo_installer.core.plan import Step
from odoo_installer.schemas import CheckResult, CheckStatus, RegistryEntry

console = Console()

_MARK = {
    CheckStatus.OK: "[green]✔ ok[/green]",
    CheckStatus.WARN: "[yellow]⚠ warn[/yellow]",
    CheckStatus.FAIL: "[red]✘ fail[/red]",
}


def render_checks(checks: Sequence[CheckResult]) -> None:
    """Render doctor checks as a rich table plus a summary line."""
    table = Table(title="odoo-installer doctor")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    table.add_column("Fix hint", overflow="fold")
    for check in checks:
        table.add_row(check.name, _MARK[check.status], check.detail, check.fix_hint)
    console.print(table)
    counts: dict[CheckStatus, int] = dict.fromkeys(CheckStatus, 0)
    for check in checks:
        counts[check.status] += 1
    console.print(
        f"{len(checks)} checks: "
        f"[green]{counts[CheckStatus.OK]} ok[/green], "
        f"[yellow]{counts[CheckStatus.WARN]} warn[/yellow], "
        f"[red]{counts[CheckStatus.FAIL]} fail[/red]"
    )


def render_plan(steps: Sequence[Step], title: str) -> None:
    """Render a plan for dry-run inspection."""
    console.print(f"[bold]{title}[/bold]")
    for index, step in enumerate(steps, start=1):
        if step.already_satisfied:
            console.print(
                f"  {index:2d}. [green]✔[/green] {step.description} [dim](already satisfied)[/dim]"
            )
        else:
            console.print(f"  {index:2d}. [cyan]→[/cyan] {step.description}")
    console.print("[dim]dry run — re-run with --apply to execute[/dim]")


def render_results(steps: Sequence[Step], notes: Sequence[str]) -> None:
    """Render applied plan step results."""
    for step, note in zip(steps, notes, strict=True):
        console.print(f"[green]✔[/green] {step.description} — {note}")


def render_registry(entries: Sequence[RegistryEntry]) -> None:
    table = Table(title="instances")
    table.add_column("Name", style="bold")
    table.add_column("HTTP port")
    table.add_column("Directory", overflow="fold")
    table.add_column("Adopted")
    for entry in entries:
        table.add_row(
            entry.name, str(entry.http_port), str(entry.dir), "yes" if entry.adopted else ""
        )
    console.print(table)


def error(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
