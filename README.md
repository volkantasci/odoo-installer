# odoo-installer

Professional CLI to install, configure and manage **Odoo 19.0** Docker stacks, with
correct-branch OCA module management and automated installability testing of core and
OCA modules.

> **Status:** work in progress (milestone M0 — scaffold). The development plan,
> architecture, decisions, and milestones live in [DEVELOPMENT.md](DEVELOPMENT.md).

## Development quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pre-commit install

pytest          # unit tests
ruff format .   # format
ruff check .    # lint
mypy            # types

odoo-installer --version
```

## Command line

Once installed (editable or from a wheel), the tool exposes:

```bash
odoo-installer --version                  # also: oii --version, python -m odoo_installer --version
odoo-installer doctor [--json]            # host prerequisite checks; exit 4 on critical failure
odoo-installer config show|set|path       # global configuration (config.toml)
odoo-installer install [--apply]          # host prerequisites (docker, compose, git); plan-first
odoo-installer instance create <name> [--apply]   # new Odoo stack (dry-run by default)
odoo-installer instance adopt <dir> [--apply]     # manage an existing compose stack (read-mostly)
odoo-installer instance list|show|start|stop|restart|remove
odoo-installer db list|create|drop|reset          # drop/reset need --apply --yes
```

The full planned command surface (module, db, test) is
specified in [DEVELOPMENT.md](DEVELOPMENT.md) §2 and lands milestone by milestone.

## License

[MIT](LICENSE)
