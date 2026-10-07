# odoo-installer

[![CI](https://github.com/volkantasci/odoo-installer/actions/workflows/ci.yml/badge.svg)](https://github.com/volkantasci/odoo-installer/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/odoo-installer)](https://pypi.org/project/odoo-installer/)
[![Python](https://img.shields.io/pypi/pyversions/odoo-installer)](https://pypi.org/project/odoo-installer/)
[![License](https://img.shields.io/pypi/l/odoo-installer)](LICENSE)

**One CLI for your Odoo 19.0 fleet.** Create and manage container stacks (rootless
Podman or Docker), install OCA modules at the correct branch, prove they work before
they ship, and share approvals across machines — with plan-first safety everywhere.

- 🦭 **Podman-first, Docker-compatible** — every instance is a compose stack on your
  chosen runtime (`container_runtime = auto|podman|docker`, `auto` prefers rootless
  podman); Odoo is never installed natively.
- 📄 **Declarative desired state** — `oii apply odoo-stack.toml` converges an
  instance end to end: stack, OCA repos, databases, installed modules. Idempotent,
  `--json` plannable, safe to loop (built for hosting control planes).
- 💾 **Backups built in** — `oii backup create/verify/restore/prune`: streamed
  pg_dump + filestore with checksums; restore is plan-first and gated.
- 🌐 **Ingress mode** — attach instances to a reverse-proxy network by alias, no
  host ports, resource limits and odoo.conf knobs per instance.
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

Documentation: **[docs/](docs/README.md)** — the multi-page guide
(**[English](docs/en/README.md)** · **[Türkçe](docs/tr/README.md)**) — plus the
single-page **[USAGE.md](USAGE.md)** (English) and
**[USAGE.tr.md](USAGE.tr.md)** (Türkçe).

## Installation

```bash
pip install odoo-installer            # from PyPI
# or from a checkout:
pip install .
```

Requires Python ≥ 3.11, a working `docker` engine with the `compose` plugin, and
`git`. Isolated daily-use install: `pipx install odoo-installer`. Shell completion:
`oii --install-completion`.

Run `oii doctor` to verify the host.

## Quick start

```bash
oii doctor                      # host checks; exit 4 on critical failure
oii install --apply             # install missing host prerequisites

oii instance create dev --apply # new stack: compose + .env + odoo.conf
oii db create odoo --instance dev

oii module search "responsive"  # find OCA repos on GitHub
oii module add web --sparse --modules web_responsive --apply
oii module test web_responsive  # scratch-DB test run; PASS -> whitelist
oii module install web_responsive --db odoo

oii test suite --output report.md --output report.json
oii instance adopt ~/Projects/my-odoo --apply  # manage an existing stack
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
