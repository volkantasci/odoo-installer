"""Typed error hierarchy for odoo-installer.

The CLI renders user-facing messages from these and maps them to exit codes
(DEVELOPMENT.md §7).
"""

from __future__ import annotations


class OdooInstallerError(Exception):
    """Base class for every odoo-installer error."""


class PrerequisiteError(OdooInstallerError):
    """A host prerequisite is missing or broken (doctor/install)."""


class StackError(OdooInstallerError):
    """A compose stack could not be created, started or inspected."""


class GitError(OdooInstallerError):
    """A git operation failed."""


class GitHubError(OdooInstallerError):
    """A GitHub API request failed or returned an unexpected payload."""


class ConfigError(OdooInstallerError):
    """Configuration could not be loaded, merged or saved."""


class ModuleError(OdooInstallerError):
    """An OCA module operation failed."""


class TestFailureError(OdooInstallerError):
    """One or more module tests failed."""

    __test__ = False  # not a pytest test class despite the name


__all__ = [
    "ConfigError",
    "GitError",
    "GitHubError",
    "ModuleError",
    "OdooInstallerError",
    "PrerequisiteError",
    "StackError",
    "TestFailureError",
]
