"""Tests for the plan executor (DEVELOPMENT.md §3.1 rule 4)."""

from __future__ import annotations

import pytest

from odoo_installer.core.plan import Step, apply_steps
from odoo_installer.exceptions import OdooInstallerError, StackError


def test_apply_steps_runs_in_order_and_collects_notes() -> None:
    calls: list[str] = []

    def one() -> str:
        calls.append("one")
        return "did one"

    def two() -> str:
        calls.append("two")
        return "did two"

    notes = apply_steps([Step("one", one), Step("two", two)])
    assert calls == ["one", "two"]
    assert notes == ["did one", "did two"]


def test_apply_steps_skips_already_satisfied() -> None:
    calls: list[str] = []

    def touch() -> str:
        calls.append("touched")
        return "touched"

    steps = [Step("already done", touch, already_satisfied=True), Step("real", touch)]
    assert apply_steps(steps) == ["already satisfied", "touched"]
    assert calls == ["touched"]


def test_apply_steps_wraps_unexpected_errors() -> None:
    def boom() -> str:
        raise ValueError("bad value")

    with pytest.raises(OdooInstallerError, match="boom step"):
        apply_steps([Step("boom step", boom)])


def test_apply_steps_lets_domain_errors_through() -> None:
    def fail() -> str:
        raise StackError("docker said no")

    with pytest.raises(StackError, match="docker said no"):
        apply_steps([Step("f", fail)])


def test_apply_steps_aborts_on_first_failure() -> None:
    calls: list[str] = []

    def fail() -> str:
        raise StackError("stop here")

    def never() -> str:
        calls.append("never")
        return "never"

    with pytest.raises(StackError):
        apply_steps([Step("f", fail), Step("n", never)])
    assert calls == []
