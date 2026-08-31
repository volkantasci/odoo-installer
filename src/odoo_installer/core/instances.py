"""Instance lifecycle: create (plan-first), list/show, start/stop/restart, remove.

Every mutating operation returns a plan of Steps; the CLI renders it (dry-run) or
applies it (--apply). Idempotency: re-running create on an existing instance reuses
the persisted secrets, rewrites identical files (flagged as already satisfied) and
leaves a running stack untouched.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.system import SystemLike
from odoo_installer.config import load_registry, save_registry
from odoo_installer.constants import ODOO_VERSION
from odoo_installer.core.plan import Step
from odoo_installer.core.stack import StackParams, compose_yaml, env_file, odoo_conf, parse_env
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import (
    INSTANCE_NAME_PATTERN,
    GlobalConfig,
    InstanceManifest,
    RegistryEntry,
)

MANIFEST_NAME = ".odoo-installer.json"
ENV_NAME = ".env"
COMPOSE_NAME = "docker-compose.yml"
ODOO_CONF_NAME = "odoo.conf"
# .env is read only by the host-side docker compose (0600 is enough). config/odoo.conf
# is mounted into the container and must be readable by its `odoo` user, which has a
# different uid than the host user — hence 0644.
_ENV_MODE = 0o600
_CONF_MODE = 0o644


@dataclass
class InstancePlan:
    """Resolved instance values plus the ordered steps that materialize them."""

    name: str
    stack_dir: Path
    http_port: int
    odoo_image: str
    pg_tag: int
    steps: list[Step]


def validate_instance_name(name: str) -> str:
    if not re.fullmatch(INSTANCE_NAME_PATTERN, name):
        raise StackError(
            f"invalid instance name {name!r}: use lowercase letters, digits and '-', "
            "starting with a letter or digit (max 32 chars)"
        )
    return name


def allocate_port(system: SystemLike, config: GlobalConfig, requested: int | None) -> int:
    if requested is not None:
        if system.port_in_use(requested):
            raise StackError(f"port {requested} is already in use")
        return requested
    for port in range(config.port_range_start, config.port_range_end + 1):
        if not system.port_in_use(port):
            return port
    raise StackError(f"no free port in {config.port_range_start}-{config.port_range_end}")


def resolve_create_port(
    *,
    system: SystemLike,
    config: GlobalConfig,
    fs: FileSystemLike,
    stack_dir: Path,
    requested: int | None,
) -> int:
    """Port resolution for `instance create` (DEVELOPMENT.md §7 idempotency).

    1. explicit --http-port wins and must be free;
    2. an existing instance manifest pins the port — re-running create must never
       drift the port (its own running container holds it, so a busy check would
       wrongly allocate a new one);
    3. otherwise allocate the first free port in the configured range.
    """
    if requested is not None:
        if system.port_in_use(requested):
            raise StackError(f"port {requested} is already in use")
        return requested
    manifest = load_manifest(fs, stack_dir)
    if manifest is not None:
        return manifest.http_port
    return allocate_port(system, config, None)


def instance_dir(config: GlobalConfig, name: str, override: Path | None) -> Path:
    return override if override is not None else config.instances_root / name


def load_manifest(fs: FileSystemLike, stack_dir: Path) -> InstanceManifest | None:
    raw = fs.read_text(stack_dir / MANIFEST_NAME)
    if raw is None:
        return None
    try:
        return InstanceManifest.model_validate_json(raw)
    except ValueError as exc:
        raise StackError(f"corrupt instance manifest in {stack_dir}: {exc}") from exc


def save_manifest(fs: FileSystemLike, manifest: InstanceManifest) -> None:
    fs.write_text(manifest.dir / MANIFEST_NAME, manifest.model_dump_json(indent=2) + "\n")


def upsert_registry_entry(registry_path: Path, entry: RegistryEntry) -> None:
    registry = load_registry(registry_path)
    registry.instances[entry.name] = entry
    save_registry(registry, registry_path)


def remove_registry_entry(registry_path: Path, name: str) -> None:
    registry = load_registry(registry_path)
    registry.instances.pop(name, None)
    save_registry(registry, registry_path)


def create_instance_plan(
    *,
    name: str,
    stack_dir: Path,
    http_port: int,
    odoo_image: str,
    pg_tag: int,
    config: GlobalConfig,
    docker: DockerLike,
    fs: FileSystemLike,
    registry_path: Path,
) -> InstancePlan:
    """Build the create plan. Resolves secrets from the existing .env if present."""
    manifest = load_manifest(fs, stack_dir)
    if manifest is not None and manifest.adopted:
        raise StackError(
            f"instance {name!r} at {stack_dir} was adopted, not created by the CLI; "
            "refusing to rewrite it"
        )
    existing_env = _load_env(fs, stack_dir)
    pg_password = existing_env.get("POSTGRES_PASSWORD") or secrets.token_urlsafe(16)
    admin_passwd = existing_env.get("ADMIN_PASSWD") or secrets.token_urlsafe(16)

    params = StackParams(
        name=name,
        odoo_image=odoo_image,
        pg_tag=pg_tag,
        http_port=http_port,
        pg_password=pg_password,
        admin_passwd=admin_passwd,
    )

    steps: list[Step] = []
    steps.append(_dirs_step(fs, stack_dir))
    steps.append(
        _write_step(
            fs,
            stack_dir / COMPOSE_NAME,
            compose_yaml(params),
            f"render {COMPOSE_NAME}",
        )
    )
    steps.append(
        _write_step(
            fs,
            stack_dir / ENV_NAME,
            env_file(params),
            f"render {ENV_NAME} (contains secrets, mode 0600)",
            mode=_ENV_MODE,
        )
    )
    steps.append(
        _write_step(
            fs,
            stack_dir / "config" / ODOO_CONF_NAME,
            odoo_conf(params),
            f"render config/{ODOO_CONF_NAME} (readable by the container, mode 0644)",
            mode=_CONF_MODE,
        )
    )
    steps.append(_registry_step(registry_path, name, stack_dir, http_port))
    steps.append(_manifest_step(fs, name, stack_dir, odoo_image, pg_tag, http_port))
    steps.append(
        Step(
            description=f"start the stack (docker compose up -d, project {name!r})",
            run=lambda: docker.compose(["up", "-d"], stack_dir, timeout_s=900) or "started",
        )
    )
    steps.append(
        Step(
            description=f"wait for web container {name}-web-1 to become healthy",
            run=lambda: docker.wait_healthy(f"{name}-web-1", timeout_s=240),
        )
    )
    return InstancePlan(
        name=name,
        stack_dir=stack_dir,
        http_port=http_port,
        odoo_image=odoo_image,
        pg_tag=pg_tag,
        steps=steps,
    )


def _load_env(fs: FileSystemLike, stack_dir: Path) -> dict[str, str]:
    raw = fs.read_text(stack_dir / ENV_NAME)
    return parse_env(raw) if raw is not None else {}


def _dirs_step(fs: FileSystemLike, stack_dir: Path) -> Step:
    targets = [stack_dir / "config", stack_dir / "addons" / "local", stack_dir / "logs"]

    def run() -> str:
        for target in targets:
            fs.ensure_dir(target)
        return "directories ready"

    satisfied = all(fs.exists(target) for target in targets)
    return Step(
        description=f"create directory structure under {stack_dir}",
        run=run,
        already_satisfied=satisfied,
    )


def _write_step(
    fs: FileSystemLike,
    path: Path,
    content: str,
    description: str,
    mode: int | None = None,
) -> Step:
    def run() -> str:
        if fs.read_text(path) == content:
            return "unchanged"
        fs.write_text(path, content, mode)
        return f"written ({len(content)} bytes)"

    return Step(
        description=description,
        run=run,
        already_satisfied=fs.read_text(path) == content,
    )


def _registry_step(registry_path: Path, name: str, stack_dir: Path, http_port: int) -> Step:
    def run() -> str:
        registry = load_registry(registry_path)
        existing = registry.instances.get(name)
        entry = existing or RegistryEntry(name=name, dir=stack_dir, http_port=http_port)
        entry.dir = stack_dir
        entry.http_port = http_port
        upsert_registry_entry(registry_path, entry)
        return "updated" if existing is not None else "registered"

    return Step(description=f"register instance {name!r} in the registry", run=run)


def _manifest_step(
    fs: FileSystemLike,
    name: str,
    stack_dir: Path,
    odoo_image: str,
    pg_tag: int,
    http_port: int,
) -> Step:
    def run() -> str:
        existing = load_manifest(fs, stack_dir)
        manifest = existing or InstanceManifest(
            name=name,
            dir=stack_dir,
            odoo_version=ODOO_VERSION,
            image=odoo_image,
            pg_tag=pg_tag,
            http_port=http_port,
        )
        manifest.image = odoo_image
        manifest.pg_tag = pg_tag
        manifest.http_port = http_port
        save_manifest(fs, manifest)
        return "updated" if existing is not None else "created"

    return Step(description=f"write {MANIFEST_NAME}", run=run)


def compose_action(action: str, stack_dir: Path, docker: DockerLike) -> str:
    """Run a reversible lifecycle action directly (no plan needed)."""
    args = {"start": ["up", "-d"], "stop": ["stop"], "restart": ["restart"]}
    if action not in args:
        raise StackError(f"unknown lifecycle action {action!r}")
    return docker.compose(args[action], stack_dir) or action


def remove_instance_plan(
    *,
    name: str,
    registry_path: Path,
    fs: FileSystemLike,
    docker: DockerLike,
    remove_data: bool,
) -> list[Step]:
    """Build the removal plan; guards refuse anything the CLI did not create."""
    stack_dir = _registered_dir(name, registry_path)
    manifest = load_manifest(fs, stack_dir)
    if manifest is None:
        raise StackError(
            f"refusing to remove {name!r}: no {MANIFEST_NAME} in {stack_dir} "
            "(the directory was not created by odoo-installer)"
        )
    if manifest.adopted:
        raise StackError(f"refusing to remove adopted instance {name!r}")

    down_args = ["down", "--remove-orphans"] + (["-v"] if remove_data else [])

    def run_down() -> str:
        return docker.compose(down_args, stack_dir) or "removed"

    def run_delete() -> str:
        fs.remove_tree(stack_dir)
        return "deleted"

    def run_unregister() -> str:
        remove_registry_entry(registry_path, name)
        return "removed"

    steps: list[Step] = [
        Step(
            description="stop and remove containers"
            + (" and volumes" if remove_data else " (volumes kept)"),
            run=run_down,
        ),
        Step(
            description=f"delete instance directory {stack_dir}",
            run=run_delete,
        ),
        Step(
            description=f"remove instance {name!r} from the registry",
            run=run_unregister,
        ),
    ]
    return steps


def _registered_dir(name: str, registry_path: Path) -> Path:
    registry = load_registry(registry_path)
    entry = registry.instances.get(name)
    if entry is None:
        raise StackError(f"instance {name!r} is not registered")
    return entry.dir
