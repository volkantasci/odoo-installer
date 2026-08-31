"""Shared CLI helpers."""

from __future__ import annotations

from odoo_installer.cli import deps
from odoo_installer.config import load_registry
from odoo_installer.core.instances import load_manifest
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import InstanceManifest


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
