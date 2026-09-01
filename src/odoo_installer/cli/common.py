"""Shared CLI helpers."""

from __future__ import annotations

from odoo_installer.cli import deps
from odoo_installer.config import load_registry, record_tested_module
from odoo_installer.constants import ODOO_VERSION
from odoo_installer.core.instances import load_manifest
from odoo_installer.core.tester import TestOutcome
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import InstanceManifest, TestedModule


def resolve_instance(container: deps.Container, instance_opt: str | None) -> InstanceManifest:
    """Pick the target instance: explicit --instance, or the only registered one."""
    registry = load_registry(container.registry_path)
    if instance_opt is not None:
        entry = registry.instances.get(instance_opt)
        if entry is None:
            raise StackError(f"instance {instance_opt!r} is not registered")
    elif len(registry.instances) == 1:
        entry = next(iter(registry.instances.values()))
    else:
        names = ", ".join(sorted(registry.instances)) or "none"
        raise StackError(f"multiple instances registered ({names}); specify --instance")
    manifest = load_manifest(container.fs, entry.dir)
    if manifest is None:
        raise StackError(f"no manifest for instance at {entry.dir}")
    return manifest


def record_tested_pass(
    container: deps.Container,
    manifest: InstanceManifest,
    module: str,
    source: str,
    outcome: TestOutcome,
) -> None:
    """Record a PASSing module in the installable-addons whitelist (tested.toml)."""
    repo_record = next((r for r in manifest.repos if module in r.modules or r.repo == source), None)
    record_tested_module(
        TestedModule(
            name=module,
            repo=source,
            branch=repo_record.branch if repo_record else ODOO_VERSION,
            commit=repo_record.commit if repo_record else "",
            db=outcome.db,
            log_path=str(outcome.log_path) if outcome.log_path else "",
        ),
        path=container.tested_path,
    )


def record_approved(
    container: deps.Container,
    manifest: InstanceManifest,
    module: str,
    source: str,
    db: str,
) -> None:
    """Record a verified installed module in the whitelist (tested.toml).

    Used by `module approve`: the evidence is the module's `installed` state in an
    explicit database, so there is no test log to reference.
    """
    repo_record = next((r for r in manifest.repos if module in r.modules or r.repo == source), None)
    record_tested_module(
        TestedModule(
            name=module,
            repo=source,
            branch=repo_record.branch if repo_record else ODOO_VERSION,
            commit=repo_record.commit if repo_record else "",
            db=db,
            log_path="",
        ),
        path=container.tested_path,
    )
