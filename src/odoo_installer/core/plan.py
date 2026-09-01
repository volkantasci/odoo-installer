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


StepReporter = Callable[[int, int, "Step", str | None], None]
"""Progress hook: called with (index, total, step, note=None) before a step runs and
with (index, total, step, note) after it finished (note = its result or
"already satisfied")."""


def apply_steps(steps: list[Step], on_step: StepReporter | None = None) -> list[str]:
    """Execute steps in order; abort on the first failure. Returns result notes.

    When `on_step` is given it is called before each step runs (note=None) and again
    after it finished (with its note), so the CLI can stream live [i/n] progress
    instead of reporting everything only at the end.
    """
    notes: list[str] = []
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        if on_step is not None:
            on_step(index, total, step, None)
        if step.already_satisfied:
            note = "already satisfied"
        else:
            try:
                note = step.run()
            except OdooInstallerError:
                raise
            except Exception as exc:
                raise OdooInstallerError(f"step failed: {step.description}: {exc}") from exc
        notes.append(note)
        if on_step is not None:
            on_step(index, total, step, note)
    return notes
