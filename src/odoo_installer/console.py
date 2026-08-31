"""Rich console rendering helpers for the CLI layer."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from odoo_installer.schemas import CheckResult, CheckStatus

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


def error(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
