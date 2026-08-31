"""OCA repository and module management (DEVELOPMENT.md §6 rules).

Rules implemented here:
- the 19.0 branch is verified via the GitHub API before any clone; never guessed;
- clones owned by the CLI live under the instance's repos/ dir (created instances) or
  the configured repo_root (adopted stacks) and are kept at origin/19.0;
- user checkouts passed with --repo are mounted as-is and never mutated;
- compose/odoo.conf edits are backup-protected; compose edits are validated with
  `docker compose config` and restored on failure;
- adopted stacks are never restarted by the CLI — the user's own tooling stays
  responsible for applying mounts (DEVELOPMENT.md §6.7).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from odoo_installer.adapters.docker import DockerLike
from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.git import GitLike
from odoo_installer.adapters.github import GitHubLike
from odoo_installer.constants import ODOO_VERSION
from odoo_installer.core.instances import (
    COMPOSE_NAME,
    MANIFEST_NAME,
    load_manifest,
    save_manifest,
)
from odoo_installer.core.plan import Step
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import GlobalConfig, InstanceManifest, RepoRecord

MANIFEST_FILE = "__manifest__.py"
CONTAINER_MOUNT_PREFIX = "/mnt/oca"


@dataclass
class ModulePlan:
    repo: str  # "OCA/<name>"
    name: str
    branch: str
    url: str
    host_path: Path
    container_path: str
    modules: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)


def split_repo(repo: str) -> tuple[str, str]:
    """Accept `OCA/<name>` or `<name>` (owner defaults to OCA)."""
    if "/" in repo:
        owner, name = repo.split("/", 1)
    else:
        owner, name = "OCA", repo
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner):
        raise StackError(f"invalid repository {repo!r}")
    return owner, name


def clone_target_path(config: GlobalConfig, manifest: InstanceManifest, name: str) -> Path:
    """Owned clones: inside the stack for created instances, repo_root for adopted."""
    if manifest.adopted:
        return config.repo_root / f"oca-{name}"
    return manifest.dir / "repos" / f"oca-{name}"


def discover_modules(fs: FileSystemLike, repo_path: Path) -> list[str]:
    """Directories containing __manifest__.py (DEVELOPMENT.md §6.5)."""
    if not fs.exists(repo_path):
        return []
    return [
        entry.name for entry in fs.subdirectories(repo_path) if fs.exists(entry / MANIFEST_FILE)
    ]


def available_modules(fs: FileSystemLike, manifest: InstanceManifest) -> dict[str, str]:
    """All modules visible to the instance: local addons + every mounted repo."""
    found: dict[str, str] = {}
    local_dir = manifest.dir / "addons" / "local"
    for module in discover_modules(fs, local_dir):
        found[module] = "local"
    for record in manifest.repos:
        for module in record.modules or discover_modules(fs, record.host_path):
            found.setdefault(module, record.repo)
    return found


def find_odoo_conf_host_path(compose_content: str, stack_dir: Path) -> Path | None:
    """Host path of the config mounted at /etc/odoo (dir mount or odoo.conf file)."""
    for line in compose_content.splitlines():
        file_match = re.search(r"-\s*([^\s:]+odoo\.conf):/etc/odoo/odoo\.conf", line)
        if file_match:
            return _resolve_host(file_match.group(1), stack_dir)
        dir_match = re.search(r"-\s*([^\s:]+):/etc/odoo(?:/)?(?::[\w.-]+)?\s*(?:#.*)?$", line)
        if dir_match:
            return _resolve_host(dir_match.group(1), stack_dir) / "odoo.conf"
    return None


def _resolve_host(host: str, stack_dir: Path) -> Path:
    path = Path(host)
    return path if path.is_absolute() else stack_dir / path


def compose_volume_edit(
    content: str, host_path: Path, container_path: str, web_service: str
) -> tuple[str, bool]:
    """Append `- <host>:<container>` to the service's volumes; (content, changed)."""
    if re.search(
        rf"-\s*{re.escape(str(host_path))}:{re.escape(container_path)}(?:\s|$)",
        content,
        re.M,
    ):
        return content, False
    lines, had_nl = _split(content)
    header, end = _service_block(lines, web_service)
    vol_idx, vol_indent = _volumes_key(lines, header, end, web_service)
    item_indent, insert_at = _volume_item_position(lines, vol_idx, vol_indent, end)
    lines.insert(insert_at, " " * item_indent + f"- {host_path}:{container_path}")
    return _join(lines, had_nl), True


def compose_volume_remove(content: str, host_path: Path, container_path: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"^\s*-\s*{re.escape(str(host_path))}:{re.escape(container_path)}\s*(?:#.*)?$",
        re.M,
    )
    if not pattern.search(content):
        return content, False
    new = pattern.sub("", content)
    new = re.sub(r"\n\n+", "\n\n", new)  # collapse blank holes left by removal
    return new, True


def conf_addons_edit(content: str, entry: str) -> tuple[str, bool]:
    match = re.search(r"^addons_path\s*=\s*(.*)$", content, re.M)
    if match:
        parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
        if entry in parts:
            return content, False
        parts.append(entry)
        return _replace_line_span(content, match, f"addons_path = {', '.join(parts)}"), True
    if re.search(r"^\[options\]\s*$", content, re.M):
        new = re.sub(r"(\[options\][ \t]*\n)", rf"\1addons_path = {entry}\n", content, count=1)
        return new, True
    raise StackError("odoo.conf has no [options] section; edit addons_path manually")


def conf_addons_remove(content: str, entry: str) -> tuple[str, bool]:
    match = re.search(r"^addons_path\s*=\s*(.*)$", content, re.M)
    if not match:
        return content, False
    parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
    if entry not in parts:
        return content, False
    remaining = [p for p in parts if p != entry]
    if not remaining:
        raise StackError(
            f"refusing to remove {entry!r}: it is the last addons_path entry; "
            "edit odoo.conf manually"
        )
    return _replace_line_span(content, match, f"addons_path = {', '.join(remaining)}"), True


def _split(content: str) -> tuple[list[str], bool]:
    had_nl = content.endswith("\n")
    body = content[:-1] if had_nl else content
    return body.split("\n"), had_nl


def _join(lines: list[str], had_nl: bool) -> str:
    return "\n".join(lines) + ("\n" if had_nl else "")


def _service_block(lines: list[str], service: str) -> tuple[int, int]:
    header = None
    for index, line in enumerate(lines):
        if re.match(rf"^  {re.escape(service)}:\s*(#.*)?$", line):
            header = index
            break
    if header is None:
        raise StackError(f"service {service!r} not found in the compose file")
    end = len(lines)
    for index in range(header + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.strip().startswith("#") and _indent(line) <= 2:
            end = index
            break
    return header, end


def _volumes_key(lines: list[str], header: int, end: int, service: str) -> tuple[int, int]:
    for index in range(header + 1, end):
        match = re.match(r"^(\s+)volumes:\s*(#.*)?$", lines[index])
        if match:
            return index, len(match.group(1))
    raise StackError(f"no 'volumes:' key found under service {service!r}; add the mount manually")


def _volume_item_position(
    lines: list[str], vol_idx: int, vol_indent: int, end: int
) -> tuple[int, int]:
    item_indent = None
    for index in range(vol_idx + 1, end):
        match = re.match(r"^(\s*)-\s", lines[index])
        if match and len(match.group(1)) > vol_indent:
            item_indent = len(match.group(1))
            insert_at = index + 1
            walk = index + 1
            while walk < end:
                next_item = re.match(r"^(\s*)-\s", lines[walk])
                if next_item and len(next_item.group(1)) == item_indent:
                    insert_at = walk + 1
                    walk += 1
                elif lines[walk].strip() == "":
                    walk += 1
                else:
                    break
            return item_indent, insert_at
    return vol_indent + 2, vol_idx + 1


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _replace_line_span(content: str, match: re.Match[str], replacement: str) -> str:
    return content[: match.start()] + replacement + content[match.end() :]


def _backup(fs: FileSystemLike, path: Path, content: str) -> Path:
    backup = path.with_name(f"{path.name}.oii-bak")
    fs.write_text(backup, content)
    return backup


def _compose_config_ok(docker: DockerLike, stack_dir: Path) -> bool:
    try:
        docker.compose(["config", "--quiet"], stack_dir, timeout_s=60)
        return True
    except Exception:
        return False


def module_add_plan(
    *,
    config: GlobalConfig,
    manifest: InstanceManifest,
    repo_arg: str,
    modules_opt: list[str] | None,
    sparse: bool,
    fork: str | None,
    existing_repo: Path | None,
    github: GitHubLike,
    git: GitLike,
    fs: FileSystemLike,
    docker: DockerLike,
) -> ModulePlan:
    owner, name = split_repo(repo_arg)
    full = f"{owner}/{name}"
    branch = ODOO_VERSION
    container_path = f"{CONTAINER_MOUNT_PREFIX}/{name}"
    state = {"changed": False}
    steps: list[Step] = []

    if existing_repo is not None:
        # eager, local-only checks: the CLI never mutates checkouts it does not own
        if not git.is_repo(existing_repo):
            raise StackError(f"{existing_repo} is not a git repository")
        url = git.remote_url(existing_repo)
        branch_now = git.active_branch(existing_repo)
        if branch_now is not None and branch_now != branch:
            raise StackError(
                f"{existing_repo} is on branch {branch_now!r}; switch it to "
                f"{branch!r} yourself — the CLI never mutates checkouts it does not own"
            )
        host_path = existing_repo
    else:
        origin_owner = fork or owner
        url = f"https://github.com/{origin_owner}/{name}.git"
        host_path = clone_target_path(config, manifest, name)
        # eager verification (DEVELOPMENT.md §6.1): a dry-run must fail fast on a
        # missing branch instead of rendering a plan that cannot execute
        if not github.branch_exists(f"{origin_owner}/{name}", branch):
            raise StackError(
                f"branch {branch!r} does not exist on {origin_owner}/{name} "
                "(checked via the GitHub API; refusing to guess a branch)"
            )

    def sync_clone() -> str:
        existed = git.is_repo(host_path)
        before = git.current_commit(host_path) if existed else None
        if existed:
            actual_url = git.remote_url(host_path)
            if actual_url.rstrip(".git").rstrip("/") != url.rstrip(".git").rstrip("/"):
                raise StackError(f"{host_path} is a clone of {actual_url}, expected {url}")
            git.fetch(host_path)
            git.checkout(host_path, f"origin/{branch}")
            note = "fetched and checked out"
        else:
            git.clone(url, host_path)
            git.checkout(host_path, f"origin/{branch}")
            note = "cloned and checked out"
        if sparse and modules_opt:
            git.sparse_checkout_set(host_path, modules_opt)
            note += " (sparse)"
        after = git.current_commit(host_path)
        if before != after:
            state["changed"] = True
        return f"{note} at {after[:8]}"

    if existing_repo is None:
        steps.append(
            Step(
                description=f"place {url} at branch {branch} in {host_path}",
                run=sync_clone,
            )
        )

    def discover() -> str:
        found = discover_modules(fs, host_path)
        if not found:
            hint = ""
            if modules_opt:
                hint = (
                    f" (requested: {', '.join(modules_opt)} — these may not exist "
                    f"in {full}@{branch}; check 'module search' or the repo tree)"
                )
            raise StackError(f"no modules with {MANIFEST_FILE} found in {host_path}{hint}")
        if modules_opt:
            missing = [m for m in modules_opt if m not in found]
            if missing:
                raise StackError(
                    f"modules not found in {full}@{branch}: {', '.join(missing)} "
                    f"(available: {', '.join(sorted(found))})"
                )
        shown = ", ".join(sorted(found))
        return shown if len(shown) <= 160 else f"{len(found)} modules"

    steps.append(Step(description=f"discover modules in {full}", run=discover))

    compose_path = manifest.dir / COMPOSE_NAME
    compose_content = fs.read_text(compose_path)
    if compose_content is None:
        raise StackError(f"{compose_path} not found")
    conf_path = find_odoo_conf_host_path(compose_content, manifest.dir)
    if conf_path is None:
        raise StackError(
            "cannot locate the /etc/odoo config mount in the compose file; "
            "add the addons_path entry manually"
        )

    def edit_compose() -> str:
        original = fs.read_text(compose_path)
        if original is None:
            raise StackError(f"{compose_path} not found")
        new, changed = compose_volume_edit(
            original, host_path, container_path, manifest.web_service
        )
        if not changed:
            return "unchanged"
        pre_ok = _compose_config_ok(docker, manifest.dir)
        backup = _backup(fs, compose_path, original)
        fs.write_text(compose_path, new)
        if pre_ok and not _compose_config_ok(docker, manifest.dir):
            fs.write_text(compose_path, original)
            raise StackError(
                f"docker compose rejected the edited file; original restored (backup: {backup})"
            )
        state["changed"] = True
        return f"mount appended (backup: {backup.name})"

    steps.append(
        Step(
            description=f"append {host_path}:{container_path} to the compose volumes",
            run=edit_compose,
        )
    )

    def edit_conf() -> str:
        original = fs.read_text(conf_path)
        if original is None:
            raise StackError(f"{conf_path} not found")
        new, changed = conf_addons_edit(original, container_path)
        if not changed:
            return "unchanged"
        backup = _backup(fs, conf_path, original)
        fs.write_text(conf_path, new)
        state["changed"] = True
        return f"addons_path += {container_path} (backup: {backup.name})"

    steps.append(
        Step(description=f"append {container_path} to odoo.conf addons_path", run=edit_conf)
    )

    def record() -> str:
        current = load_manifest(fs, manifest.dir) or manifest
        found = discover_modules(fs, host_path)
        record_modules = modules_opt or found
        record = RepoRecord(
            repo=full,
            url=url,
            branch=branch,
            commit=git.current_commit(host_path),
            host_path=host_path,
            container_path=container_path,
            modules=record_modules,
            sparse=sparse and bool(modules_opt),
        )
        current.repos = [r for r in current.repos if r.repo.split("/")[-1] != name]
        current.repos.append(record)
        save_manifest(fs, current)
        return "recorded"

    steps.append(Step(description=f"record {full} in {MANIFEST_NAME}", run=record))

    if not manifest.adopted:

        def restart() -> str:
            if not state["changed"]:
                return "skipped (nothing changed)"
            return docker.compose(["restart", manifest.web_service], manifest.dir) or "restarted"

        steps.append(
            Step(
                description=f"restart web service {manifest.web_service!r} "
                "to apply the new addons_path",
                run=restart,
            )
        )

    return ModulePlan(
        repo=full,
        name=name,
        branch=branch,
        url=url,
        host_path=host_path,
        container_path=container_path,
        steps=steps,
    )


def module_remove_plan(
    *,
    config: GlobalConfig,
    manifest: InstanceManifest,
    repo_arg: str,
    purge_repo: bool,
    db_opt: str | None,
    dbms_execute_sql: Callable[..., str],
    git: GitLike,
    fs: FileSystemLike,
    docker: DockerLike,
) -> ModulePlan:
    """Reverse of add: unmount, optionally reset module states, optionally purge."""
    _owner, name = split_repo(repo_arg)
    record = next((r for r in manifest.repos if r.repo.split("/")[-1] == name), None)
    if record is None:
        raise StackError(f"repo {name!r} is not mounted in this instance")
    state = {"changed": False}
    steps: list[Step] = []

    if db_opt is not None:

        def unstate() -> str:
            names = ", ".join(f"'{m}'" for m in record.modules)
            return (
                dbms_execute_sql(
                    docker,
                    manifest.dir,
                    manifest.db_service,
                    manifest.db_user,
                    db_opt,
                    f"UPDATE ir_module_module SET state = 'uninstalled' WHERE name IN ({names})",
                )
                or "states reset"
            )

        steps.append(
            Step(
                description=f"reset module states to 'uninstalled' in db {db_opt!r} "
                "(data tables remain; a real uninstall happens inside Odoo)",
                run=unstate,
            )
        )

    compose_path = manifest.dir / COMPOSE_NAME

    def edit_compose() -> str:
        original = fs.read_text(compose_path)
        if original is None:
            raise StackError(f"{compose_path} not found")
        new, changed = compose_volume_remove(original, record.host_path, record.container_path)
        if not changed:
            return "unchanged"
        backup = _backup(fs, compose_path, original)
        fs.write_text(compose_path, new)
        state["changed"] = True
        return f"mount removed (backup: {backup.name})"

    steps.append(
        Step(
            description=f"remove {record.container_path} mount from the compose file",
            run=edit_compose,
        )
    )

    conf_path = find_odoo_conf_host_path(fs.read_text(compose_path) or "", manifest.dir)
    if conf_path is not None:

        def edit_conf() -> str:
            original = fs.read_text(conf_path)
            if original is None:
                raise StackError(f"{conf_path} not found")
            new, changed = conf_addons_remove(original, record.container_path)
            if not changed:
                return "unchanged"
            backup = _backup(fs, conf_path, original)
            fs.write_text(conf_path, new)
            state["changed"] = True
            return f"addons_path -= {record.container_path} (backup: {backup.name})"

        steps.append(
            Step(
                description=f"remove {record.container_path} from odoo.conf addons_path",
                run=edit_conf,
            )
        )

    def forget() -> str:
        current = load_manifest(fs, manifest.dir) or manifest
        current.repos = [r for r in current.repos if r.repo.split("/")[-1] != name]
        save_manifest(fs, current)
        return "removed from manifest"

    steps.append(Step(description=f"forget {record.repo} in {MANIFEST_NAME}", run=forget))

    if purge_repo:
        owned = (
            record.host_path.is_relative_to(config.repo_root)
            or record.host_path.is_relative_to(manifest.dir)
        ) and git.is_repo(record.host_path)

        def purge() -> str:
            if not owned:
                return "skipped (not an odoo-installer clone)"
            fs.remove_tree(record.host_path)
            return f"deleted {record.host_path}"

        steps.append(Step(description=f"delete the repo clone at {record.host_path}", run=purge))

    if not manifest.adopted:

        def restart() -> str:
            if not state["changed"]:
                return "skipped (nothing changed)"
            return docker.compose(["restart", manifest.web_service], manifest.dir) or "restarted"

        steps.append(Step(description=f"restart web service {manifest.web_service!r}", run=restart))

    return ModulePlan(
        repo=record.repo,
        name=name,
        branch=record.branch,
        url=record.url,
        host_path=record.host_path,
        container_path=record.container_path,
        steps=steps,
    )
