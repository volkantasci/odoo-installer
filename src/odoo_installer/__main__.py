"""Allow running the CLI via `python -m odoo_installer`."""

from __future__ import annotations

from odoo_installer.cli.main import app

if __name__ == "__main__":
    app()
