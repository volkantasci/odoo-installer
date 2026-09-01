"""Rich console rendering helpers for the CLI layer."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from rich.console import Console
from rich.table import Table

from odoo_installer.core.dbms import DatabaseInfo
from odoo_installer.core.plan import Step
from odoo_installer.core.tester import TestOutcome
from odoo_installer.schemas import CheckResult, CheckStatus, RegistryEntry, RepoSummary

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


def progress_reporter() -> Callable[[int, int, Step, str | None], None]:
    """Build a live progress hook for `apply_steps`.

    Before a step runs it prints `[i/total] description`; after it finishes it prints
    the result note (`✔ already satisfied` included), so long plans stream their
    progress instead of reporting only at the end.
    """

    def report(index: int, total: int, step: Step, note: str | None) -> None:
        if note is None:
            console.print(f"[bold]\\[{index}/{total}][/bold] {step.description}")
        else:
            console.print(f"  [green]✔[/green] {note}")

    return report


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


def render_databases(databases: Sequence[DatabaseInfo]) -> None:
    table = Table(title="databases")
    table.add_column("Database", style="bold")
    table.add_column("Size")
    for info in databases:
        table.add_row(info.name, info.size)
    console.print(table)


def render_module_rows(rows: Sequence[dict[str, str]], db: str | None) -> None:
    table = Table(title="modules" if db is None else f"modules (db {db})")
    table.add_column("Module", style="bold")
    has_source = bool(rows) and "source" in rows[0]
    if has_source:
        table.add_column("Source")
        table.add_column("Commit")
    has_tested = any("tested" in row for row in rows)
    if has_tested:
        table.add_column("Tested")
    table.add_column("State")
    for row in rows:
        cells = [row["module"]]
        if has_source:
            cells += [row.get("source", ""), row.get("commit", "")]
        if has_tested:
            cells.append(row.get("tested", ""))
        cells.append(row.get("state", ""))
        table.add_row(*cells)
    console.print(table)


def render_test_outcome(outcome: TestOutcome) -> None:
    mark = "[green]✔ PASS[/green]" if outcome.passed else "[red]✘ FAIL[/red]"
    console.print(
        f"{mark} {outcome.module} on scratch db {outcome.db!r} "
        f"({outcome.duration_s:.0f}s, exit {outcome.exit_code})"
    )
    if outcome.failures:
        console.print("[red]failing tests:[/red]")
        for failure in outcome.failures[:10]:
            console.print(f"  {failure}")
        if len(outcome.failures) > 10:
            console.print(f"  ... and {len(outcome.failures) - 10} more")
    if outcome.log_path is not None:
        console.print(f"[dim]log: {outcome.log_path}[/dim]")


def render_suite_summary(outcomes: Sequence[TestOutcome]) -> None:
    table = Table(title="test suite summary")
    table.add_column("Module", style="bold")
    table.add_column("Result")
    table.add_column("Duration (s)")
    table.add_column("Failure kinds", overflow="fold")
    for outcome in outcomes:
        mark = "[green]✔ PASS[/green]" if outcome.passed else "[red]✘ FAIL[/red]"
        table.add_row(
            outcome.module,
            mark,
            f"{outcome.duration_s:.0f}",
            ", ".join(outcome.kinds) or "—",
        )
    console.print(table)
    passed = sum(1 for o in outcomes if o.passed)
    failed = len(outcomes) - passed
    console.print(
        f"{len(outcomes)} modules: [green]{passed} passed[/green], [red]{failed} failed[/red]"
    )


def render_search_results(query: str, results: Sequence[RepoSummary]) -> None:
    table = Table(title=f"OCA repos matching {query!r}")
    table.add_column("Repository", style="bold")
    table.add_column("Default branch")
    table.add_column("Description", overflow="fold")
    for item in results:
        table.add_row(item.full_name, item.default_branch, item.description)
    console.print(table)


def error(message: str) -> None:
    console.print(f"[red]Error:[/red] {message}")
