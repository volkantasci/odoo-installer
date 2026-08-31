"""Tests for the CLI entry point (M0)."""

from __future__ import annotations

from typer.testing import CliRunner

from odoo_installer import __version__
from odoo_installer.cli.main import app
from odoo_installer.constants import APP_NAME

runner = CliRunner()


def test_version_flag_prints_name_and_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert APP_NAME in result.output
    assert __version__ in result.output


def test_short_version_flag() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_command_prints_version_only() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_help_lists_version_flag() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.output
    assert "version" in result.output  # the version subcommand
