"""`oii apply` — converge an instance to its odoo-stack.toml desired state.

Two-phase by necessity, not by taste: repo/database/module plans are built from
the instance manifest, which only exists once the stack does. An existing stack
gets one fully detailed plan. A fresh stack gets the create plan plus a single
convergence step that plans the rest at execution time, when the manifest is
real — a placeholder manifest would poison the recorded state. The pieces being
converged are the same idempotent ones the interactive commands use, so apply
is safe to re-run and to loop.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import functools
import shlex
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.git import GitLike
from odoo_installer.adapters.github import GitHubLike
from odoo_installer.adapters.system import SystemLike
from odoo_installer.config import get_tested_module
from odoo_installer.constants import DEFAULT_ODOO_IMAGE
from odoo_installer.core.dbms import (
    FIRST_INIT_PENDING,
    create_database,
    database_comment,
    force_drop_database,
    login_count,
    module_states,
    set_database_comment,
)
from odoo_installer.core.instances import (
    create_instance_plan,
    instance_dir,
    instance_secret,
    load_manifest,
    resolve_create_port,
    validate_instance_name,
)
from odoo_installer.core.modules import (
    available_modules,
    list_core_addons,
    module_add_plan,
    module_remove_plan,
)
from odoo_installer.core.plan import Step
from odoo_installer.core.runner import install_modules, set_admin_credentials
from odoo_installer.core.spec import DatabaseDefaults, StackSpec, spec_to_extras
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import GlobalConfig, InstanceManifest

DbmsExecuteSql = Callable[..., str]


@dataclass
class ApplyPlan:
    """Everything `oii apply` resolved, plus the ordered steps."""

    name: str
    stack_dir: Path
    created: bool
    steps: list[Step] = field(default_factory=list)


@contextlib.contextmanager
def apply_lock(registry_path: Path, name: str) -> Iterator[None]:
    """Exclusive, non-blocking per-instance lock held for a whole apply.

    The lock file lives in a `locks/` directory next to the registry, so it
    exists before the stack directory does (a fresh create has no stack dir yet).
    """
    lock_dir = registry_path.parent / "locks"
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        handle = (lock_dir / f"apply-{name}.lock").open("a")
    except OSError as exc:
        raise StackError(f"cannot create the apply lock for {name}: {exc}") from exc
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise
            raise StackError(f"another apply is running for {name}") from None
        yield
    finally:
        handle.close()  # closing releases the flock


def build_apply_plan(
    spec: StackSpec,
    *,
    config: GlobalConfig,
    docker: ComposeLike,
    fs: FileSystemLike,
    github: GitHubLike,
    git: GitLike,
    system: SystemLike,
    registry_path: Path,
    tested_path: Path,
) -> ApplyPlan:
    instance_name = validate_instance_name(spec.name)
    stack_dir = instance_dir(config, instance_name, spec.dir)
    manifest = load_manifest(fs, stack_dir)
    extras = spec_to_extras(spec)

    port = _resolve_port(spec, manifest, config, fs, stack_dir, registry_path, system)
    instance_plan = create_instance_plan(
        name=instance_name,
        stack_dir=stack_dir,
        http_port=port,
        odoo_image=spec.image or DEFAULT_ODOO_IMAGE,
        pg_tag=spec.pg_tag or config.default_pg_tag,
        config=config,
        docker=docker,
        fs=fs,
        registry_path=registry_path,
        extras=extras,
    )
    steps = list(instance_plan.steps)

    if manifest is None:
        # fresh stack: the rest is planned once the manifest exists (see module
        # docstring) — the dry run shows it as one honest convergence step
        steps.append(
            Step(
                description="converge repos, databases and module installs "
                "(planned in detail once the stack exists)",
                run=lambda: _converge_rest(
                    spec,
                    config=config,
                    docker=docker,
                    fs=fs,
                    github=github,
                    git=git,
                    tested_path=tested_path,
                    stack_dir=stack_dir,
                ),
            )
        )
        return ApplyPlan(name=instance_name, stack_dir=stack_dir, created=True, steps=steps)

    steps.extend(
        _rest_steps(
            spec,
            manifest=manifest,
            config=config,
            docker=docker,
            fs=fs,
            github=github,
            git=git,
            tested_path=tested_path,
        )
    )
    return ApplyPlan(name=instance_name, stack_dir=stack_dir, created=False, steps=steps)


def _resolve_port(
    spec: StackSpec,
    manifest: InstanceManifest | None,
    config: GlobalConfig,
    fs: FileSystemLike,
    stack_dir: Path,
    registry_path: Path,
    system: SystemLike,
) -> int:
    if spec.ingress is not None:
        return manifest.http_port if manifest is not None else 0
    # spec.http_port is a REQUEST: it must be free on the wire and not reserved
    # by another registered instance (rootless podman would otherwise silently
    # double-bind via its userspace port forwarder). Re-runs on the instance's
    # own pinned port are accepted, exactly like `instance create --http-port`.
    return resolve_create_port(
        system=system,
        config=config,
        fs=fs,
        stack_dir=stack_dir,
        requested=spec.http_port,
        registry_path=registry_path,
    )


def _rest_steps(
    spec: StackSpec,
    *,
    manifest: InstanceManifest,
    config: GlobalConfig,
    docker: ComposeLike,
    fs: FileSystemLike,
    github: GitHubLike,
    git: GitLike,
    tested_path: Path,
) -> list[Step]:
    """Detailed convergence steps against a real manifest (repos, dbs, installs)."""
    steps: list[Step] = []
    current = manifest
    mounted = {record.repo: record for record in current.repos}
    wanted = {repo.repo_arg: repo for repo in spec.repos}
    state: dict[str, bool] = {"changed": False}

    for repo_arg, repo in wanted.items():
        plan = module_add_plan(
            config=config,
            manifest=current,
            repo_arg=repo_arg,
            modules_opt=repo.modules or None,
            sparse=bool(repo.modules),
            fork=None,
            existing_repo=None,
            github=github,
            git=git,
            fs=fs,
            docker=docker,
            state=state,
        )
        steps.extend(plan.steps)
        current = load_manifest(fs, manifest.dir) or current

    for repo_full in sorted(set(mounted) - set(wanted)):
        plan = module_remove_plan(
            config=config,
            manifest=current,
            repo_arg=repo_full,
            purge_repo=True,
            db_opt=None,
            dbms_execute_sql=_dbms_noop,
            git=git,
            fs=fs,
            docker=docker,
        )
        steps.extend(plan.steps)
        current = load_manifest(fs, manifest.dir) or current

    for db_name, db_spec in spec.databases.items():
        steps.append(
            Step(
                description=f"ensure database {db_name!r} exists",
                run=functools.partial(
                    create_database,
                    docker,
                    manifest.dir,
                    manifest.db_service,
                    manifest.db_user,
                    db_name,
                ),
            )
        )
        if db_spec.install:
            steps.append(
                _install_step(
                    docker=docker,
                    fs=fs,
                    stack_dir=manifest.dir,
                    db=db_name,
                    modules=db_spec.install,
                    allow_untested=db_spec.allow_untested,
                    defaults=db_spec.defaults,
                    tested_path=tested_path,
                )
            )
    return steps


def _converge_rest(
    spec: StackSpec,
    *,
    config: GlobalConfig,
    docker: ComposeLike,
    fs: FileSystemLike,
    github: GitHubLike,
    git: GitLike,
    tested_path: Path,
    stack_dir: Path,
) -> str:
    """Execution-time continuation for fresh stacks: plan + run the rest."""
    from odoo_installer.console import progress_reporter
    from odoo_installer.core.plan import apply_steps

    manifest = load_manifest(fs, stack_dir)
    if manifest is None:
        raise StackError(f"no manifest in {stack_dir} after stack creation")
    steps = _rest_steps(
        spec,
        manifest=manifest,
        config=config,
        docker=docker,
        fs=fs,
        github=github,
        git=git,
        tested_path=tested_path,
    )
    if not steps:
        return "nothing further to converge"
    apply_steps(steps, on_step=progress_reporter())
    return f"converged {len(steps)} further step(s)"


def _install_step(
    *,
    docker: ComposeLike,
    fs: FileSystemLike,
    stack_dir: Path,
    db: str,
    modules: list[str],
    allow_untested: bool,
    defaults: DatabaseDefaults | None,
    tested_path: Path,
) -> Step:
    """Install `modules` into `db`, verifying visibility + whitelist at run time.

    Plan-time verification is impossible for fresh stacks (repos are not cloned
    and the container is not up yet), so the step applies the same gates as
    `module install` when it runs — with identical error messages — and skips
    when everything requested is already installed.
    """

    def run() -> str:
        manifest = load_manifest(fs, stack_dir)
        if manifest is None:
            raise StackError(f"no manifest in {stack_dir}; apply the stack first")
        available = available_modules(fs, manifest)
        missing = [m for m in modules if m not in available]
        core: set[str] = set()
        if missing:
            core = list_core_addons(docker, manifest)
            unexplained = [m for m in missing if m not in core]
            if unexplained:
                raise StackError(
                    f"modules not visible to this instance: {', '.join(unexplained)}; "
                    "add their repos to the spec's [[repos]]"
                )
        untested = [
            m for m in modules if m not in core and get_tested_module(m, path=tested_path) is None
        ]
        if untested and not allow_untested:
            raise StackError(
                "not tested yet: "
                + ", ".join(untested)
                + " — run 'module test <name>' first, or set allow_untested = true "
                "for this database in the spec"
            )
        states = _states_safe(docker, manifest, db, modules)
        # a successful module-state query proves Odoo's tables exist
        initialized = states is not None or _db_initialized(docker, manifest, db)
        # checked BEFORE the "already installed" return: an init killed after
        # `odoo -i` but before the credentials were set looks fully installed
        interrupted = initialized and (
            database_comment(docker, manifest.dir, manifest.db_service, manifest.db_user, db)
            == FIRST_INIT_PENDING
        )
        if (
            not interrupted
            and states is not None
            and all(states.get(m) == "installed" for m in modules)
        ):
            return f"{db!r}: all requested modules already installed"
        recreated = ""
        if interrupted:
            _refuse_if_logins(docker, manifest, db)
            recreated = (
                f"interrupted first init of {db!r} found (pending marker); "
                "database dropped and re-created for a clean first init; "
            )
            from odoo_installer.console import console

            console.print(
                f"[yellow]interrupted first init of {db!r} found (pending marker): "
                "dropping and re-creating the database for a clean first init[/yellow]"
            )
            try:
                force_drop_database(docker, manifest.dir, manifest.db_service, manifest.db_user, db)
                create_database(docker, manifest.dir, manifest.db_service, manifest.db_user, db)
            except Exception as redo_err:
                raise StackError(
                    f"interrupted first init of {db!r} found, but dropping and re-creating "
                    f"the database failed: {redo_err}"
                ) from redo_err
            initialized = False
        first_init = not initialized
        login = _secret_or(fs, stack_dir, "ODOO_ADMIN_LOGIN") or "admin"
        password = _secret_or(fs, stack_dir, "ODOO_ADMIN_PASSWORD") if first_init else None
        # Odoo picks the chart of accounts when `account` is installed, from the
        # company's country. So with a country the first init is staged:
        # base -> ORM defaults (country, ...) -> the remaining apps.
        staged = (
            first_init and password is not None and defaults is not None and bool(defaults.country)
        )

        def apply_defaults(pw: str) -> None:
            # Odoo initializes a fresh db with login/password admin/admin; the
            # generated per-instance credentials and locale defaults are applied
            # via the ORM (raw SQL would bypass password hashing)
            set_admin_credentials(
                docker,
                manifest.dir,
                manifest.web_service,
                db,
                login,
                pw,
                lang=defaults.lang if defaults is not None else None,
                country=defaults.country if defaults is not None else None,
                timezone=defaults.timezone if defaults is not None else None,
                currency=defaults.currency if defaults is not None else None,
                base_url=defaults.base_url if defaults is not None else None,
            )

        load_language = defaults.lang if first_init and defaults is not None else None
        pw = password
        marker = {"state": "none"}  # none | pending | cleared

        def first_init_sequence() -> str:
            def install(mods: list[str], language: str | None = None) -> str:
                return install_modules(
                    docker, manifest.dir, manifest.web_service, db, mods, load_language=language
                )

            def set_marker(comment: str | None) -> None:
                set_database_comment(
                    docker, manifest.dir, manifest.db_service, manifest.db_user, db, comment
                )
                marker["state"] = "pending" if comment else "cleared"

            # durable marker: if apply dies after Odoo created its tables (even
            # SIGKILL) but before the real credentials are set, the next apply
            # sees it and redoes the init instead of leaving admin/admin behind
            if first_init and pw is not None:
                set_marker(FIRST_INIT_PENDING)
            if staged and pw is not None:
                output = install(["base"], load_language)
                apply_defaults(pw)
                marker["state"] = "applied"
                set_marker(None)
                apps = [m for m in modules if m != "base"]
                if apps:
                    output = install(apps) or output
                note = output or f"installed {', '.join(modules)} into {db!r}"
                note += f"; admin login {login!r} password applied"
                note += "; staged: base → defaults → apps"
            else:
                output = install(modules, load_language)
                note = output or f"installed {', '.join(modules)} into {db!r}"
                if pw is None:
                    return note
                apply_defaults(pw)
                marker["state"] = "applied"
                set_marker(None)
                note += f"; admin login {login!r} password applied"
            if defaults is not None and defaults.lang is not None:
                note += f"; defaults {defaults.lang}/{defaults.country or '-'}"
            return note

        if not first_init:
            return first_init_sequence()
        try:
            return recreated + first_init_sequence()
        except Exception as err:
            # Odoo already created its tables, so the next apply would see an
            # initialized database, skip the defaults and leave admin/admin on a
            # routed tenant. An oii-managed db at this point holds no Odoo data.
            what = str(err) if isinstance(err, StackError) else f"{type(err).__name__}: {err}"
            if recreated:
                what = f"{recreated}the redo failed: {what}"
            if marker["state"] in ("applied", "cleared"):
                # the real admin credentials are set: never drop (the owner may
                # already have logged in); the next apply continues the install
                raise StackError(
                    f"{what}; database {db!r} has its admin credentials and defaults applied, "
                    "so oii keeps it: the next apply continues the install"
                ) from err
            try:
                force_drop_database(docker, manifest.dir, manifest.db_service, manifest.db_user, db)
            except Exception as drop_err:
                follow_up = {
                    "pending": "the pending first-init marker makes the next apply drop and "
                    "redo it",
                }.get(marker["state"], f"drop it manually before the next apply ({db!r})")
                raise StackError(
                    f"{what}; database {db!r} could not be removed after the failed first "
                    f"init ({drop_err}); {follow_up}"
                ) from err
            raise StackError(
                f"{what}; database {db!r} was removed so the next apply starts a clean first init"
            ) from err

    return Step(
        description=f"install modules {', '.join(modules)} into db {db!r} "
        "(visibility and whitelist verified at run time)",
        run=run,
    )


def _refuse_if_logins(docker: ComposeLike, manifest: InstanceManifest, db: str) -> None:
    """Hard guard before dropping an interrupted first init: only an exact "0" passes."""
    try:
        count = login_count(docker, manifest.dir, manifest.db_service, manifest.db_user, db)
        error: str | None = None if count == "0" else f"res_users_log count was {count!r}"
    except Exception as exc:
        error = f"could not read res_users_log ({exc})"
    if error is None:
        return
    name = getattr(manifest, "name", "<instance>")
    clear_sql = f'COMMENT ON DATABASE "{db}" IS NULL'
    clear = (
        f"cd {shlex.quote(str(manifest.dir))} && {docker.runtime} compose exec -T "
        f"{shlex.quote(manifest.db_service)} psql -U {shlex.quote(manifest.db_user)} "
        f"-d postgres -c {shlex.quote(clear_sql)}"
    )
    raise StackError(
        f"database {db!r} carries the pending first-init marker but oii cannot prove nobody "
        f"logged in ({error}), so oii will not drop it. Its admin credentials may still be "
        "Odoo's default. To verify, try admin/admin; the intended credentials are printed by "
        f"`oii instance secret {name} --key ODOO_ADMIN_LOGIN` and "
        f"`oii instance secret {name} --key ODOO_ADMIN_PASSWORD`. If the database holds "
        f"nothing of value, the preferred fix is `oii db drop {db} --instance {name} --apply "
        "--yes`, then apply again. Otherwise reset the admin password and clear the marker "
        f"with: {clear} (clearing the marker skips the first-init defaults: "
        "lang/country/currency/timezone/base_url)"
    )


def _db_initialized(docker: ComposeLike, manifest: InstanceManifest, db: str) -> bool:
    """True when Odoo already initialized the database (ir_module_module exists).

    Fails safe: unexpected psql output, or tables without an Odoo registry,
    raise instead of guessing (a wrong "not initialized" can lead to a drop).
    """

    def query(sql: str) -> str:
        return docker.compose(
            [
                "exec", "-T", manifest.db_service, "psql", "-U", manifest.db_user,
                "-d", db, "-At", "-c", sql,
            ],
            manifest.dir,
        ).strip()  # fmt: skip

    registry = query(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'ir_module_module'"
    )
    if registry == "1":
        return True
    if registry != "":
        raise StackError(f"unexpected psql output while checking database {db!r}: {registry!r}")
    tables = query("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    if tables == "0":
        return False
    if not (tables.isdigit() and int(tables) > 0):
        raise StackError(f"unexpected psql output while checking database {db!r}: {tables!r}")
    raise StackError(
        f"database {db!r} has tables but no Odoo registry (psql said {tables!r}); "
        "refusing to initialise or drop it"
    )


def _states_safe(
    docker: ComposeLike, manifest: InstanceManifest, db: str, modules: list[str]
) -> dict[str, str] | None:
    try:
        return module_states(
            docker, manifest.dir, manifest.db_service, manifest.db_user, db, modules
        )
    except StackError:
        return None  # fresh db: nothing installed yet


def _secret_or(fs: FileSystemLike, stack_dir: Path, key: str) -> str | None:
    try:
        return instance_secret(fs, stack_dir, key)
    except StackError:
        return None


def _dbms_noop(*_args: object, **_kwargs: object) -> str:
    return ""
