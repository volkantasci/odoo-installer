# odoo-installer

Professional CLI to install, configure and manage **Odoo 19.0** Docker stacks, with
correct-branch OCA module management and automated installability testing of OCA modules.

- **Docker-only runtime** — never installs Odoo on the host; every instance is a compose stack.
- **Plan-first safety** — destructive actions print a plan and run as dry-run until you pass `--apply`.
- **Correct OCA branches** — the 19.0 branch is verified via the GitHub API before any clone.
- **Tested-only installs** — `module install` refuses modules that have not passed a real
  test run; passing runs are recorded in an installable-addons whitelist (`tested.toml`).
- **Idempotent** — every action can be re-run safely (ports pin, secrets persist, re-runs no-op).

The development plan, architecture, decisions, and milestones live in
[DEVELOPMENT.md](DEVELOPMENT.md).

Detailed usage guide: [USAGE.md](USAGE.md) (English) · [USAGE.tr.md](USAGE.tr.md)
(Türkçe).

## Installation

```bash
pip install odoo-installer            # from PyPI (0.4.0+)
# or from a checkout:
pip install .
```

Requires Python ≥ 3.11, a working `docker` engine with the `compose` plugin, and `git`.
Run `odoo-installer doctor` to verify the host. Shell completion:
`odoo-installer --install-completion` (bash/zsh/fish).

## Quick start

```bash
odoo-installer doctor                      # host checks; exit 4 on critical failure
odoo-installer install --apply             # install missing host prerequisites (pacman/apt)

odoo-installer instance create dev --apply # new stack: compose + .env + odoo.conf, port 8069-8099
odoo-installer db create odoo --instance dev

odoo-installer module search "responsive"  # find OCA repos on GitHub
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive  # scratch-DB test run; PASS -> whitelist
odoo-installer module install web_responsive --db odoo

odoo-installer test suite --output report.md --output report.json
odoo-installer instance adopt ~/Projects/my-odoo --apply      # manage an existing stack
```

The whitelist is the contract: only modules that pass `module test` (or the `test suite`)
appear as installable; everything else requires an explicit `--allow-untested`.

## Command line

```bash
odoo-installer --version                  # also: oii --version, python -m odoo_installer --version
odoo-installer doctor [--json]            # host prerequisite checks; exit 4 on critical failure
odoo-installer config show|set|edit       # global configuration (config.toml)
odoo-installer install [--apply]          # host prerequisites (docker, compose, git); plan-first
odoo-installer instance create <name> [--apply]   # new Odoo stack (dry-run by default)
odoo-installer instance adopt <dir> [--apply]     # manage an existing compose stack (read-mostly)
odoo-installer instance list|show|secret|start|stop|restart|remove
odoo-installer db list|create|drop|reset          # drop/reset need --apply --yes
odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH] [--apply]
odoo-installer module list [--instance NAME] [--json] | search <query>
odoo-installer module test <module>          # scratch-db test run; PASS -> whitelist
odoo-installer module approve <module...> --db DB  # whitelist verified installed modules
odoo-installer module install|upgrade <module...> --db DB   # refuses untested modules
odoo-installer module remove <repo> [--purge-repo] [--apply]
odoo-installer test suite [--only <repo>] [--modules m1,m2]
                          [--output report.{md,json}] [--keep-db]
odoo-installer test pull [--apply]          # merge central whitelist repo (tested_repo_url)
```

The full, precise command surface is specified in [DEVELOPMENT.md](DEVELOPMENT.md) §2.

Exit codes: `0` success · `1` error · `3` test failures (`module test`, `test suite`) ·
`4` critical host check failed (`doctor`).

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
