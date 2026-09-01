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

from odoo_installer.adapters.docker import DockerLike, host_port_for
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


def instance_secret(fs: FileSystemLike, stack_dir: Path, key: str = "ADMIN_PASSWD") -> str:
    """Read one secret from the instance's .env (default: the Odoo master password).

    Raises StackError when the instance has no .env or the key is absent — never
    guesses or falls back to odoo.conf, so the printed value is always the one the
    stack actually runs with.
    """
    env_path = stack_dir / ENV_NAME
    raw = fs.read_text(env_path)
    if raw is None:
        raise StackError(f"no {ENV_NAME} in {stack_dir} (instance not created by this CLI?)")
    values = parse_env(raw)
    if key not in values:
        raise StackError(
            f"{key!r} not found in {env_path}; available keys: {', '.join(sorted(values))}"
        )
    return values[key]


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


def compose_action(action: str, stack_dir: Path, docker: DockerLike, adopted: bool = False) -> str:
    """Run a reversible lifecycle action directly (no plan needed).

    Adopted stacks are managed read-mostly: `start` uses `docker compose start`,
    which only boots existing containers and can never recreate them from a
    changed compose file.
    """
    args = {
        "start": ["start"] if adopted else ["up", "-d"],
        "stop": ["stop"],
        "restart": ["restart"],
    }
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
    """Build the removal plan; guards refuse anything the CLI did not create.

    Adopted stacks CAN be removed — the tool is read-mostly (§6.7), but removal is an
    explicit, `--yes`-gated destructive action, not a silent rewrite. `--remove-data`
    maps to `compose down -v`, which destroys the named volumes declared in the
    stack's own compose file (bind-mounted data goes with the directory).
    """
    stack_dir = _registered_dir(name, registry_path)
    manifest = load_manifest(fs, stack_dir)
    if manifest is None:
        raise StackError(
            f"refusing to remove {name!r}: no {MANIFEST_NAME} in {stack_dir} "
            "(the directory was not created by odoo-installer)"
        )

    down_args = ["down", "--remove-orphans"] + (["-v"] if remove_data else [])
    down_note = "removed" + (" with volumes" if remove_data else "")

    def run_down() -> str:
        return docker.compose(down_args, stack_dir) or down_note

    def run_delete() -> str:
        fs.remove_tree(stack_dir)
        return "deleted"

    def run_unregister() -> str:
        remove_registry_entry(registry_path, name)
        return "removed"

    kind = "adopted stack" if manifest.adopted else "instance"
    steps: list[Step] = [
        Step(
            description=f"stop and remove the {kind}'s containers"
            + (" and volumes" if remove_data else " (volumes kept)"),
            run=run_down,
        ),
        Step(
            description=f"delete the {kind} directory {stack_dir}",
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


@dataclass
class DetectedStack:
    """Result of inspecting an existing compose project's containers."""

    project: str
    web_service: str
    db_service: str
    web_image: str
    db_image: str
    http_port: int


def detect_stack(docker: DockerLike, stack_dir: Path) -> DetectedStack:
    """Classify an existing compose project's containers into web/db services.

    Detection uses container labels only — the compose file is never parsed, so
    stacks with env-var interpolation or multiple config files still adopt.
    """
    containers = docker.compose_containers(stack_dir)
    if not containers:
        raise StackError(
            f"no compose containers found for {stack_dir} "
            "(the stack was never created or was removed)"
        )
    project = ""
    web: str | None = None
    db: str | None = None
    web_image = db_image = ""
    web_ports = ""
    for container in containers:
        project = container.project or project
        if "postgres" in container.image and db is None:
            db = container.service
            db_image = container.image
        elif (
            "odoo" in container.image or host_port_for(container.ports, 8069) is not None
        ) and web is None:
            web = container.service
            web_image = container.image
            web_ports = container.ports
    if web is None or db is None:
        found = ", ".join(sorted({c.service for c in containers if c.service})) or "none"
        raise StackError(
            f"cannot identify the web/db services in {stack_dir} (found services: {found})"
        )
    http_port = host_port_for(web_ports, 8069)
    if http_port is None:
        raise StackError(
            f"web service {web!r} publishes no host port for container port 8069; "
            "a stack the CLI cannot reach cannot be adopted"
        )
    return DetectedStack(
        project=project,
        web_service=web,
        db_service=db,
        web_image=web_image,
        db_image=db_image,
        http_port=http_port,
    )


def _guess_odoo_version(web_image: str) -> str:
    tag = web_image.rsplit(":", 1)[-1]
    return "19.0" if tag in {"19", "19.0"} else tag


def _guess_pg_tag(db_image: str) -> int:
    tag = db_image.rsplit(":", 1)[-1]
    digits = tag.split("-", 1)[0]
    return int(digits) if digits.isdigit() else 0


def adopt_instance_plan(
    *,
    name: str,
    stack_dir: Path,
    detected: DetectedStack,
    db_user: str,
    fs: FileSystemLike,
    registry_path: Path,
) -> InstancePlan:
    """Plan for adopting an existing stack: manifest + registry only (read-mostly)."""
    manifest = load_manifest(fs, stack_dir)
    if manifest is not None:
        raise StackError(
            f"{stack_dir} already has {MANIFEST_NAME} "
            "(it was created or adopted by odoo-installer before)"
        )
    registry = load_registry(registry_path)
    existing = registry.instances.get(name)
    if existing is not None and existing.dir != stack_dir:
        raise StackError(f"instance name {name!r} is already registered for {existing.dir}")
    odoo_version = _guess_odoo_version(detected.web_image)
    pg_tag = _guess_pg_tag(detected.db_image)

    def write_manifest() -> str:
        save_manifest(
            fs,
            InstanceManifest(
                name=name,
                dir=stack_dir,
                odoo_version=odoo_version,
                image=detected.web_image,
                pg_tag=pg_tag,
                http_port=detected.http_port,
                adopted=True,
                web_service=detected.web_service,
                db_service=detected.db_service,
                db_user=db_user,
            ),
        )
        return "created"

    def register() -> str:
        upsert_registry_entry(
            registry_path,
            RegistryEntry(
                name=name,
                dir=stack_dir,
                http_port=detected.http_port,
                adopted=True,
            ),
        )
        return "registered"

    return InstancePlan(
        name=name,
        stack_dir=stack_dir,
        http_port=detected.http_port,
        odoo_image=detected.web_image,
        pg_tag=pg_tag,
        steps=[
            Step(
                description=f"write {MANIFEST_NAME} into {stack_dir} (adopted, read-mostly)",
                run=write_manifest,
            ),
            Step(
                description=f"register instance {name!r} in the registry (adopted)",
                run=register,
            ),
        ],
    )
