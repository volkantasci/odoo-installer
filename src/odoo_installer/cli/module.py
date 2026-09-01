"""`odoo-installer module` — OCA repository and module management.

Safety (DEVELOPMENT.md §6/§7): the 19.0 branch is verified via the GitHub API before
cloning; user checkouts (--repo) are never mutated; adopted stacks get file edits only
with explicit --yes and are never restarted (the CLI reports the restart instead);
module install/upgrade always require an explicit --db (use oitest_* scratch names).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from odoo_installer.cli import deps
from odoo_installer.cli.common import record_approved, record_tested_pass, resolve_instance
from odoo_installer.config import (
    get_tested_module,
    instance_logs_dir,
    load_tested_registry,
)
from odoo_installer.console import (
    console,
    error,
    progress_reporter,
    render_module_rows,
    render_plan,
    render_search_results,
    render_test_outcome,
)
from odoo_installer.core.dbms import execute_sql, module_states
from odoo_installer.core.modules import (
    available_modules,
    module_add_plan,
    module_manifest_deps,
    module_remove_plan,
    resolve_dependencies,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.core.runner import install_modules
from odoo_installer.core.tester import drop_scratch_db, run_module_test
from odoo_installer.exceptions import OdooInstallerError
from odoo_installer.schemas import InstanceManifest, TestedModule

app = typer.Typer(no_args_is_help=True, help="Manage OCA repos and Odoo modules.")

_APPLY_HELP = "Execute the plan (without it, this is a dry run)."
_INSTANCE_HELP = "Target instance (default: the only registered instance)."
_DB_HELP = "Target database (required; use oitest_* scratch names for testing)."


@app.command("add")
def add(
    repo: Annotated[
        str, typer.Argument(help="OCA repo, e.g. 'OCA/server-tools' or 'server-tools'.")
    ],
    *,
    modules_opt: Annotated[
        str | None,
        typer.Option("--modules", help="Comma-separated module list (default: all discovered)."),
    ] = None,
    sparse: Annotated[
        bool, typer.Option("--sparse", help="Sparse-checkout only the requested modules.")
    ] = False,
    repo_path: Annotated[
        str | None,
        typer.Option(
            "--repo",
            help="Mount an existing local checkout instead of cloning (never mutated).",
        ),
    ] = None,
    fork: Annotated[
        str | None,
        typer.Option("--fork", help="Clone from your fork (origin=<fork>, branch verified there)."),
    ] = None,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Explicit confirmation for file edits on ADOPTED stacks (required there).",
        ),
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Add an OCA repo: verify the 19.0 branch, clone/mount, extend addons_path."""
    container = deps.build()
    module_names = [m.strip() for m in modules_opt.split(",") if m.strip()] if modules_opt else None
    try:
        manifest = resolve_instance(container, instance)
        plan = module_add_plan(
            config=container.config,
            manifest=manifest,
            repo_arg=repo,
            modules_opt=module_names,
            sparse=sparse,
            fork=fork,
            existing_repo=Path(repo_path) if repo_path else None,
            github=container.github,
            git=container.git,
            fs=container.fs,
            docker=container.docker,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(
        f"repo [bold]{plan.repo}[/bold] at branch [bold]{plan.branch}[/bold] -> "
        f"{plan.host_path}:{plan.container_path}"
    )
    if not apply_changes:
        render_plan(plan.steps, f"Module add plan: {plan.repo}")
        return
    if manifest.adopted and not yes:
        console.print(
            "[yellow]this adopted stack's files would be edited; add --yes to confirm "
            "(DEVELOPMENT.md §6.7)[/yellow]"
        )
        return
    try:
        apply_steps(plan.steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if manifest.adopted:
        console.print(
            "[yellow]adopted stack: recreate it with your own tooling "
            "(e.g. `docker compose up -d web`) to apply the new mount — the CLI "
            "did not touch the running containers[/yellow]"
        )
    else:
        console.print(f"[green]✔[/green] {plan.repo} added")
    console.print(
        "[dim]next: `module test <module>` to whitelist it, then "
        "`module install <module> --db <db>`[/dim]"
    )


@app.command("list")
def list_modules(
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    db: Annotated[
        str | None, typer.Option("--db", help="Show install state from this database.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List modules visible to the instance (local addons + mounted OCA repos)."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        rows: list[dict[str, str]] = []
        for module, source in sorted(available_modules(container.fs, manifest).items()):
            record = next((r for r in manifest.repos if r.repo == source), None)
            rows.append(
                {
                    "module": module,
                    "source": source,
                    "commit": record.commit[:8] if record else "",
                    "state": "",
                }
            )
        tested = load_tested_registry(container.tested_path).modules
        for row in rows:
            entry = tested.get(row["module"])
            row["tested"] = entry.tested_at.strftime("%Y-%m-%d") if entry else ""
        if db is not None:
            states = module_states(
                container.docker,
                manifest.dir,
                manifest.db_service,
                manifest.db_user,
                db,
                [row["module"] for row in rows],
            )
            for row in rows:
                row["state"] = states.get(row["module"], "not in db")
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        console.print("no modules found (add an OCA repo first)")
        return
    render_module_rows(rows, db)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search term(s) within the OCA GitHub org.")],
    *,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results.")] = 10,
) -> None:
    """Search OCA repositories on GitHub."""
    container = deps.build()
    try:
        results = container.github.search_repos(query, limit=limit)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not results:
        console.print("no repositories matched")
        return
    render_search_results(query, results)


def _run_modules(
    modules: list[str],
    *,
    db: str,
    instance: str | None,
    upgrade: bool,
    allow_untested: bool = False,
    resolve_deps: bool = False,
) -> None:
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        available = available_modules(container.fs, manifest)
        missing = [m for m in modules if m not in available]
        if missing:
            raise OdooInstallerError(
                f"modules not visible to this instance: {', '.join(missing)}; "
                "run 'module add' first"
            )

        # dependency resolution: extend the module list with resolvable OCA deps and,
        # with --resolve-deps, mount the provider repos they live in
        catalog = load_tested_registry(container.tested_path).modules
        if not resolve_deps:
            cheap = _catalog_clash(container, manifest, modules, available, catalog)
            if cheap:
                raise OdooInstallerError(
                    "missing OCA dependencies need mounting: "
                    + "; ".join(f"{dep} <- {repo} (provides {dep})" for dep, repo in cheap)
                    + " — re-run with --resolve-deps to mount them automatically"
                )
        else:
            resolution = resolve_dependencies(
                fs=container.fs,
                manifest=manifest,
                docker=container.docker,
                targets=modules,
                catalog=catalog,
            )
            if resolution.unresolved:
                raise OdooInstallerError(
                    "unresolvable dependencies (not core, not mounted, not in the "
                    f"whitelist catalog): {', '.join(resolution.unresolved)} — try "
                    "'module search' to find the providing repo"
                )
            for repo_full, branch, dep_modules in resolution.to_mount:
                add_plan = module_add_plan(
                    config=container.config,
                    manifest=manifest,
                    repo_arg=repo_full,
                    modules_opt=dep_modules,
                    sparse=True,
                    fork=None,
                    existing_repo=None,
                    github=container.github,
                    git=container.git,
                    fs=container.fs,
                    docker=container.docker,
                )
                console.print(
                    f"[bold]resolving dependency[/bold] {repo_full} @ {branch} "
                    f"(provides {', '.join(dep_modules)})"
                )
                apply_steps(add_plan.steps, on_step=progress_reporter())
                manifest = resolve_instance(container, instance)
            modules = resolution.to_install

        untested = [m for m in modules if get_tested_module(m, path=container.tested_path) is None]
        if untested and not allow_untested:
            raise OdooInstallerError(
                "not tested yet: "
                + ", ".join(untested)
                + " — run 'module test <name>' first, or pass --allow-untested"
            )
        output = install_modules(
            container.docker,
            manifest.dir,
            manifest.web_service,
            db,
            modules,
            upgrade=upgrade,
        )
        states = module_states(
            container.docker,
            manifest.dir,
            manifest.db_service,
            manifest.db_user,
            db,
            modules,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    tail = "\n".join(output.splitlines()[-12:])
    if tail.strip():
        console.print(f"[dim]{tail}[/dim]")
    rows = [{"module": m, "state": states.get(m, "not in db")} for m in modules]
    render_module_rows(rows, db)
    verb = "upgraded" if upgrade else "installed"
    bad = [m for m in modules if states.get(m) != "installed"]
    if bad:
        error(f"modules not in 'installed' state: {', '.join(bad)}")
        raise typer.Exit(code=1)
    console.print(f"[green]✔[/green] {verb}: {', '.join(modules)}")


def _catalog_clash(
    container: deps.Container,
    manifest: InstanceManifest,
    modules: list[str],
    available: dict[str, str],
    catalog: dict[str, TestedModule],
) -> list[tuple[str, str]]:
    """Cheap (no docker) pre-check: targets whose deps are catalog-known OCA modules
    that are NOT provided locally. Returns (dep, providing_repo) pairs."""
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for target in modules:
        for dep in module_manifest_deps(container.fs, manifest, target):
            if dep in available or dep in seen:
                continue
            entry = catalog.get(dep)
            if entry is not None and entry.repo != "local":
                missing.append((dep, entry.repo))
                seen.add(dep)
    return missing


@app.command("install")
def install(
    modules: Annotated[list[str], typer.Argument(help="Module names.")],
    *,
    db: Annotated[str, typer.Option("--db", help=_DB_HELP)],
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    allow_untested: Annotated[
        bool,
        typer.Option(
            "--allow-untested",
            help="Skip the tested-addons whitelist check (whitelist: tested.toml).",
        ),
    ] = False,
    resolve_deps: Annotated[
        bool,
        typer.Option(
            "--resolve-deps",
            help="Mount unmounted OCA repos that provide missing dependencies "
            "(per the whitelist catalog) and include the deps in the install.",
        ),
    ] = False,
) -> None:
    """Install modules into an explicit database (odoo -i, scratch DBs recommended)."""
    _run_modules(
        modules,
        db=db,
        instance=instance,
        upgrade=False,
        allow_untested=allow_untested,
        resolve_deps=resolve_deps,
    )


@app.command("upgrade")
def upgrade(
    modules: Annotated[list[str], typer.Argument(help="Module names.")],
    *,
    db: Annotated[str, typer.Option("--db", help=_DB_HELP)],
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    allow_untested: Annotated[
        bool,
        typer.Option(
            "--allow-untested",
            help="Skip the tested-addons whitelist check (whitelist: tested.toml).",
        ),
    ] = False,
    resolve_deps: Annotated[
        bool,
        typer.Option(
            "--resolve-deps",
            help="Mount unmounted OCA repos that provide missing dependencies "
            "(per the whitelist catalog) and include the deps in the upgrade.",
        ),
    ] = False,
) -> None:
    """Upgrade modules in an explicit database (odoo -u)."""
    _run_modules(
        modules,
        db=db,
        instance=instance,
        upgrade=True,
        allow_untested=allow_untested,
        resolve_deps=resolve_deps,
    )


@app.command("remove")
def remove(
    repo: Annotated[str, typer.Argument(help="Repo to unmount, e.g. 'server-utils'.")],
    *,
    db: Annotated[
        str | None,
        typer.Option("--db", help="Also reset the repo's modules to 'uninstalled' in this db."),
    ] = None,
    purge_repo: Annotated[
        bool, typer.Option("--purge-repo", help="Also delete the odoo-installer clone.")
    ] = False,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Explicit confirmation for file edits on ADOPTED stacks."),
    ] = False,
    apply_changes: Annotated[bool, typer.Option("--apply", help=_APPLY_HELP)] = False,
) -> None:
    """Remove a repo from the instance: unmount, forget, optionally purge."""
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        plan = module_remove_plan(
            config=container.config,
            manifest=manifest,
            repo_arg=repo,
            purge_repo=purge_repo,
            db_opt=db,
            dbms_execute_sql=execute_sql,
            git=container.git,
            fs=container.fs,
            docker=container.docker,
        )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    if not apply_changes:
        render_plan(plan.steps, f"Module remove plan: {plan.repo}")
        return
    if manifest.adopted and not yes:
        console.print("[yellow]add --yes to confirm edits on this adopted stack[/yellow]")
        return
    try:
        apply_steps(plan.steps, on_step=progress_reporter())
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(f"[green]✔[/green] {plan.repo} removed")


@app.command("test")
def test(
    module: Annotated[str, typer.Argument(help="Module to test on a scratch database.")],
    *,
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
    keep_db: Annotated[
        bool, typer.Option("--keep-db", help="Keep the scratch database for debugging.")
    ] = False,
) -> None:
    """Test a module: install on a scratch DB, run its tests, record PASS.

    A PASS is recorded in the installable-addons whitelist (tested.toml); `module
    install` refuses untested modules unless --allow-untested is given.
    """
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        available = available_modules(container.fs, manifest)
        if module not in available:
            raise OdooInstallerError(
                f"module {module!r} is not visible to this instance; run 'module add' first"
            )
        outcome = run_module_test(
            container.docker,
            manifest.dir,
            manifest.web_service,
            manifest.db_service,
            manifest.db_user,
            container.fs,
            instance_logs_dir(manifest),
            module,
        )
        if not keep_db:
            drop_scratch_db(
                container.docker,
                manifest.dir,
                manifest.db_service,
                manifest.db_user,
                module,
            )
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    render_test_outcome(outcome)
    if not outcome.passed:
        raise typer.Exit(code=3)
    record_tested_pass(container, manifest, module, available[module], outcome)
    console.print(
        f"[green]✔[/green] {module} recorded as tested/installable "
        f"(whitelist: {container.tested_path})"
    )


@app.command("approve")
def approve(
    modules: Annotated[list[str], typer.Argument(help="Module names to whitelist.")],
    *,
    db: Annotated[str, typer.Option("--db", help=_DB_HELP)],
    instance: Annotated[str | None, typer.Option("--instance", help=_INSTANCE_HELP)] = None,
) -> None:
    """Whitelist modules that are verified 'installed' in an explicit database.

    For modules whose quality is already proven on a running stack (e.g. approved on
    the production instance): the command refuses anything that is not in
    `installed` state in --db, then records the entries in tested.toml.
    """
    container = deps.build()
    try:
        manifest = resolve_instance(container, instance)
        available = available_modules(container.fs, manifest)
        missing = [m for m in modules if m not in available]
        if missing:
            raise OdooInstallerError(
                f"modules not visible to this instance: {', '.join(missing)}; "
                "run 'module add' first"
            )
        states = module_states(
            container.docker,
            manifest.dir,
            manifest.db_service,
            manifest.db_user,
            db,
            modules,
        )
        bad = [m for m in modules if states.get(m) != "installed"]
        if bad:
            raise OdooInstallerError(
                "refusing to approve — not in 'installed' state in db "
                f"{db!r}: " + ", ".join(f"{m} ({states.get(m, 'not in db')})" for m in bad)
            )
        for m in modules:
            record_approved(container, manifest, m, available[m], db)
    except OdooInstallerError as exc:
        error(str(exc))
        raise typer.Exit(code=1) from None
    console.print(
        f"[green]✔[/green] approved (whitelist: {container.tested_path}): {', '.join(modules)}"
    )
