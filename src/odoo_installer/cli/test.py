"""`odoo-installer test` — batch test suite for an instance's modules.

Runs each module's tests sequentially (Odoo limitation: one scratch DB at a time),
feeds PASSes into the installable-addons whitelist, and renders a summary with an
optional Markdown/JSON report file. Exit code 3 when any module fails.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.cli.common import record_tested_pass, resolve_instance
from odoo_installer.config import instance_logs_dir
from odoo_installer.console import console, error, render_suite_summary, render_test_outcome
from odoo_installer.core.modules import available_modules
from odoo_installer.core.tester import TestOutcome, drop_scratch_db, run_module_test
from odoo_installer.exceptions import OdooInstallerError

app = typer.Typer(no_args_is_help=True, help="Batch-test an instance's modules.")

_INSTANCE_HELP = "Target instance (default: the only registered instance)."


def _repo_matches(source: str, only: str) -> bool:
    return only in (source, source.split("/")[-1])


def _write_report(path: Path, instance_name: str, outcomes: list[TestOutcome]) -> None:
    """Write the suite report; format chosen by suffix (.json or .md)."""
    payload = {
        "instance": instance_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(outcomes),
        "passed": sum(1 for o in outcomes if o.passed),
        "failed": sum(1 for o in outcomes if not o.passed),
        "results": [
            {
                "module": o.module,
                "db": o.db,
                "passed": o.passed,
                "exit_code": o.exit_code,
                "kinds": o.kinds,
                "failures": o.failures,
                "duration_s": round(o.duration_s, 1),
                "log_path": str(o.log_path) if o.log_path else "",
            }
            for o in outcomes
        ],
    }
    if path.suffix == ".json":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif path.suffix == ".md":
        lines = [
            "# odoo-installer test suite report",
            "",
            f"- instance: `{instance_name}`",
            f"- generated: {payload['generated_at']}",
            f"- total: {payload['total']} · passed: {payload['passed']} · "
            f"failed: {payload['failed']}",
            "",
            "| Module | Result | Duration (s) | Failure kinds |",
            "|---|---|---|---|",
        ]
        for o in outcomes:
            lines.append(
                f"| {o.module} | {'PASS' if o.passed else 'FAIL'} | "
                f"{o.duration_s:.0f} | {', '.join(o.kinds) or '—'} |"
            )
        failed = [o for o in outcomes if not o.passed]
        if failed:
            lines += ["", "## Failures", ""]
            for o in failed:
                lines += [
                    f"### {o.module} (exit {o.exit_code})",
                    "",
                    f"- db: `{o.db}`",
                    f"- kinds: {', '.join(o.kinds) or '—'}",
                    f"- log: `{o.log_path or 'n/a'}`",
                    "",
                ]
                lines += [f"    {line}" for line in o.failures[:10]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise OdooInstallerError("report file must end in .md or .json")


@app.command("suite")
def suite(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    only: Annotated[
        str | None,
        typer.Option("--only", help="Restrict to one source repo, e.g. 'web' or 'OCA/web'."),
    ] = None,
    modules_opt: Annotated[
        str | None,
        typer.Option("--modules", help="Comma-separated explicit module list."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Write a .md or .json report file.")
    ] = None,
    keep_db: Annotated[
        bool, typer.Option("--keep-db", help="Keep each module's scratch database.")
    ] = False,
) -> None:
    """Test every (or filtered) module on the instance's addons_path, in order."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        available = available_modules(container.fs, manifest)
        if modules_opt:
            names = [m.strip() for m in modules_opt.split(",") if m.strip()]
            missing = [m for m in names if m not in available]
            if missing:
                raise OdooInstallerError(
                    f"modules not visible to this instance: {', '.join(missing)}"
                )
        else:
            names = sorted(available)
            if only:
                names = [m for m in names if _repo_matches(available[m], only)]
        if not names:
            console.print("nothing to test (no modules on this instance's addons_path)")
            return
        logs_dir = instance_logs_dir(manifest)
        outcomes = []
        for index, module in enumerate(names, start=1):
            console.print(
                f"[bold]\\[{index}/{len(names)}][/bold] {module} [dim]({available[module]})[/dim]"
            )
            outcome = run_module_test(
                container.docker,
                manifest.dir,
                manifest.web_service,
                manifest.db_service,
                manifest.db_user,
                container.fs,
                logs_dir,
                module,
            )
            render_test_outcome(outcome)
            if outcome.passed:
                record_tested_pass(container, manifest, module, available[module], outcome)
            if not keep_db:
                drop_scratch_db(
                    container.docker,
                    manifest.dir,
                    manifest.db_service,
                    manifest.db_user,
                    module,
                )
            outcomes.append(outcome)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None

    render_suite_summary(outcomes)
    if output is not None:
        try:
            _write_report(output, manifest.name, outcomes)
        except OdooInstallerError as exc:
            error(str(exc))
            raise typer.Exit(code=1) from None
        console.print(f"[green]✔[/green] report written: {output}")
    failed = sum(1 for o in outcomes if not o.passed)
    if failed:
        raise typer.Exit(code=3)
