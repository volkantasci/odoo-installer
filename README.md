# odoo-installer

[![CI](https://github.com/volkantasci/odoo-installer/actions/workflows/ci.yml/badge.svg)](https://github.com/volkantasci/odoo-installer/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/odoo-installer)](https://pypi.org/project/odoo-installer/)
[![Python](https://img.shields.io/pypi/pyversions/odoo-installer)](https://pypi.org/project/odoo-installer/)
[![License](https://img.shields.io/pypi/l/odoo-installer)](LICENSE)

**One CLI for your Odoo 19.0 fleet.** Create and manage Docker stacks, install OCA
modules at the correct branch, prove they work before they ship, and share approvals
across machines — with plan-first safety everywhere.

- 🐳 **Docker-only runtime** — every instance is a compose stack; Odoo is never
  installed natively.
- 📋 **Plan-first safety** — every mutation prints its exact plan (live `[i/n]`
  progress) and runs only with `--apply` — plus `--yes` when destructive.
- 🌿 **Correct OCA branches** — `origin/19.0` is verified via the GitHub API before
  any clone; never guessed.
- ✅ **Tested-only installs** — `module install` refuses modules that have not passed
  a real test run (or been approved on a proven stack).
- 🔗 **Dependency resolver** — reads each module's `__manifest__.py`, verifies core
  deps against the running container and mounts the OCA repos that provide the rest
  (`--resolve-deps`).
- 🗂️ **Central approvals** — the whitelist lives in a git repo: `module approve`
  records proven modules, `test pull` spreads them to every machine. No CLI update
  needed for new approvals.
- 🔁 **Idempotent** — re-runs are safe: ports pin, secrets persist, satisfied steps
  report `already satisfied`.

The development plan, architecture, decisions and milestones live in
[DEVELOPMENT.md](DEVELOPMENT.md).

Detailed usage guide: **[USAGE.md](USAGE.md)** (English) ·
**[USAGE.tr.md](USAGE.tr.md)** (Türkçe).

## Installation

```bash
pip install odoo-installer            # from PyPI
# or from a checkout:
pip install .
```

Requires Python ≥ 3.11, a working `docker` engine with the `compose` plugin, and
`git`. Isolated daily-use install: `pipx install odoo-installer`. Shell completion:
`odoo-installer --install-completion`.

Run `odoo-installer doctor` to verify the host.

## Quick start

```bash
odoo-installer doctor                      # host checks; exit 4 on critical failure
odoo-installer install --apply             # install missing host prerequisites

odoo-installer instance create dev --apply # new stack: compose + .env + odoo.conf
odoo-installer db create odoo --instance dev

odoo-installer module search "responsive"  # find OCA repos on GitHub
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive  # scratch-DB test run; PASS -> whitelist
odoo-installer module install web_responsive --db odoo

odoo-installer test suite --output report.md --output report.json
odoo-installer instance adopt ~/Projects/my-odoo --apply  # manage an existing stack
```

## Commands at a glance

| Command | Purpose |
|---------|---------|
| `doctor [--json]` | host diagnostics (exit 4 on critical failure) |
| `install [--apply]` | host prerequisites — plan-first |
| `config show\|set\|edit\|path` | global configuration |
| `instance create\|adopt\|list\|show\|secret\|start\|stop\|restart\|remove` | stack lifecycle |
| `db list\|create\|drop\|reset` | databases (drop/reset: `--apply --yes`) |
| `module add\|list\|search\|install\|upgrade\|remove\|test\|approve` | OCA repos and modules |
| `test suite\|pull` | batch testing with reports · central whitelist sync |
| `version` | print the version |

The full, precise command surface is specified in [DEVELOPMENT.md](DEVELOPMENT.md) §2;
the detailed usage guide (options, examples, recipes, troubleshooting) is
[USAGE.md](USAGE.md).

Exit codes: `0` success · `1` error · `2` usage error · `3` test failures ·
`4` critical host check failed.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pre-commit install

pytest          # unit tests (offline, fake adapters)
ruff check .    # lint
ruff format .   # format
mypy            # types
python -m build # wheel + sdist
```

## License

[MIT](LICENSE)
