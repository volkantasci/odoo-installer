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
odoo-installer --version    # also: oii --version, python -m odoo_installer --version
```

The full planned command surface (doctor, install, instance, module, db, test) is
specified in [DEVELOPMENT.md](DEVELOPMENT.md) §2 and lands milestone by milestone.

## License

[MIT](LICENSE)
