"""Executable plans: render-first, execute on --apply (DEVELOPMENT.md §3.1 rule 4).

A plan is an ordered list of steps. Dry-run renders the descriptions; apply runs the
`run` callables in order and aborts on the first failure.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from odoo_installer.exceptions import OdooInstallerError


@dataclass
class Step:
    """One plan step: a description to render and the action that executes it."""

    description: str
    run: Callable[[], str]
    already_satisfied: bool = False


def apply_steps(steps: list[Step]) -> list[str]:
    """Execute steps in order; abort on the first failure. Returns result notes."""
    notes: list[str] = []
    for step in steps:
        if step.already_satisfied:
            notes.append("already satisfied")
            continue
        try:
            notes.append(step.run())
        except OdooInstallerError:
            raise
        except Exception as exc:
            raise OdooInstallerError(f"step failed: {step.description}: {exc}") from exc
    return notes
