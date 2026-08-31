"""Tests for the typed error hierarchy (DEVELOPMENT.md §7)."""

from __future__ import annotations

import pytest

from odoo_installer import exceptions

_SUBCLASSES = [
    exceptions.ConfigError,
    exceptions.GitError,
    exceptions.GitHubError,
    exceptions.ModuleError,
    exceptions.PrerequisiteError,
    exceptions.StackError,
    exceptions.TestFailureError,
]


@pytest.mark.parametrize("exc_class", _SUBCLASSES)
def test_every_error_extends_the_base(
    exc_class: type[exceptions.OdooInstallerError],
) -> None:
    assert issubclass(exc_class, exceptions.OdooInstallerError)
    instance = exc_class("boom")
    assert str(instance) == "boom"
