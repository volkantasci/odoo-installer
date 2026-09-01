"""Central installable-addons whitelist: pull from a shared git repo.

`tested_repo_url` (config.toml) points at a small git repo whose root holds a
`tested.toml`. `test pull` refreshes a local cache clone and MERGES its entries into
the active whitelist (`~/.config/odoo-installer/tested.toml`): union by module name,
keeping the newer `tested_at` on a clash. Local PASS records and central approvals
therefore both count for `module install` gating — approving a module on one machine
spreads to every machine that pulls.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from odoo_installer.adapters.filesystem import FileSystemLike
from odoo_installer.adapters.git import GitLike
from odoo_installer.config import default_tested_path, load_tested_registry, save_tested_registry
from odoo_installer.constants import APP_NAME
from odoo_installer.core.plan import Step
from odoo_installer.exceptions import OdooInstallerError
from odoo_installer.schemas import TestedRegistry


def tested_repo_cache_dir() -> Path:
    """Local cache clone of the whitelist repo (XDG cache dir)."""
    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)) / "tested-repo"


def merge_tested_registries(
    local: TestedRegistry, incoming: TestedRegistry
) -> tuple[TestedRegistry, int, int]:
    """Union by module name; on a name clash the newer `tested_at` wins.

    Returns (merged, added, updated).
    """
    merged = TestedRegistry(modules=dict(local.modules))
    added = updated = 0
    for name, record in incoming.modules.items():
        current = merged.modules.get(name)
        if current is None:
            merged.modules[name] = record
            added += 1
        elif record.tested_at > current.tested_at:
            merged.modules[name] = record
            updated += 1
    return merged, added, updated


@dataclass
class TestedPullPlan:
    """Steps to refresh the whitelist from the central repo (+ mutable summary)."""

    url: str
    cache_dir: Path
    steps: list[Step] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def tested_pull_plan(
    *,
    url: str,
    git: GitLike,
    fs: FileSystemLike,
    active_path: Path | None = None,
) -> TestedPullPlan:
    """Build the `test pull` plan: refresh cache clone, merge into the whitelist."""
    cache = tested_repo_cache_dir()
    target = active_path or default_tested_path()
    state: dict[str, int] = {}

    def sync_clone() -> str:
        if fs.exists(cache):
            # the whitelist repo is tiny; a fresh clone is simpler and branch-agnostic
            fs.remove_tree(cache)
        git.clone(url, cache)
        return f"cloned {url} into {cache}"

    def merge() -> str:
        raw = fs.read_text(cache / "tested.toml")
        if raw is None:
            raise OdooInstallerError(
                f"no tested.toml at the root of {cache} — is {url!r} a whitelist repo?"
            )
        try:
            incoming = TestedRegistry.model_validate(tomllib.loads(raw))
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            raise OdooInstallerError(f"invalid tested.toml in {cache}: {exc}") from exc
        local = load_tested_registry(target)
        merged, added, updated = merge_tested_registries(local, incoming)
        if added or updated:
            save_tested_registry(merged, target)
        state["added"] = added
        state["updated"] = updated
        state["total"] = len(merged.modules)
        if added or updated:
            return f"merged: +{added} added, {updated} updated (total {len(merged.modules)})"
        return f"already up to date ({len(merged.modules)} approved modules)"

    steps = [
        Step(description=f"refresh the whitelist repo clone of {url}", run=sync_clone),
        Step(description=f"merge the repo's tested.toml into {target}", run=merge),
    ]
    return TestedPullPlan(url=url, cache_dir=cache, steps=steps, summary=state)
