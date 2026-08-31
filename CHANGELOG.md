# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-31

### Added

- Project scaffold: src-layout package, Typer CLI entry point (`odoo-installer`, alias
  `oii`), `--version` flag and `version` command, static constants for the Odoo 19.0
  stack, and the typed error hierarchy.
- Developer tooling: ruff (format + lint), mypy (strict), pytest with coverage, and
  unit tests for the CLI entry point.
- CI: lint/types and unit test matrix (Python 3.11–3.13) via GitHub Actions.
- `doctor` command: host checks for the docker engine and compose plugin, docker group
  membership (read from `/etc/group`, not stale process groups), git, disk space at the
  instances root, port availability on 8069–8099, and GitHub API reachability. Renders a
  rich table or `--json`; exits with code 4 when a critical check fails.
- `config show|set|path` sub-app backed by validated, atomic TOML persistence
  (`~/.config/odoo-installer/config.toml`); instance registry load/save helpers for M2.
- Host adapters (docker, system, github, filesystem) behind `Protocol` interfaces;
  unit tests run fully offline against fakes.
- `install` command: plan-first host prerequisite installation (docker engine, compose
  plugin, git) via pacman/apt with `--apply`; idempotent — satisfied hosts are no-ops.
- `instance` sub-app: `create` (dry-run plan → `--apply`, auto port allocation in the
  configured range, jinja-rendered `docker-compose.yml`/`.env`/`odoo.conf`, generated
  secrets persisted across re-runs, `docker compose up -d` + health wait),
  `list`, `show`, `start`, `stop`, `restart`, and `remove` (dry-run by default;
  execution requires `--apply --yes`; `--remove-data` destroys the pgdata volume).
- Instance state: registry (`registry.toml`) plus per-instance manifest
  (`.odoo-installer.json`); `create` re-runs are idempotent and pin the recorded port.
- Docker adapter additions: `compose`, `wait_healthy` (with log capture on failure),
  `logs`; system adapter package/service operations; filesystem adapter atomic
  writes with permission modes (`.env` 0600, `odoo.conf` 0644 for container readability).
- `instance adopt <dir>`: register an existing compose stack (detected purely from
  container labels — no compose file parsing) and manage it read-mostly: `start` uses
  `docker compose start` so adopted stacks are never recreated, and no stack files are
  rewritten (only the odoo-installer manifest is added).
- `db` sub-app: `list` (sizes via `pg_database_size`), `create` (idempotent),
  `drop` and `reset` — executed through `psql` in the db container. Database names are
  always explicit CLI arguments; `postgres`/`template0`/`template1` refuse to be
  dropped; `drop`/`reset` are plan-first and execute only with `--apply --yes`.
- `module` sub-app for OCA repositories and modules:
  `add` verifies the 19.0 branch via the GitHub API before cloning (never guesses —
  a repo whose default branch is 18.0 but has 19.0 is handled), clones into the
  instance's `repos/` (or the configured `repo_root` for adopted stacks), supports
  `--sparse` and mounting existing checkouts unmutated (`--repo`), appends the compose
  volume + `addons_path` with automatic backups and `docker compose config`
  validation, and restarts web only for stacks the CLI created (adopted stacks get a
  "restart with your own tooling" report instead);
  `list` shows modules with per-database install states (`--db`, `--json`);
  `search` queries the OCA GitHub org;
  `install`/`upgrade` run `odoo -i/-u --stop-after-init --http-port=8071` inside the
  web container against an explicit `--db` (scratch `oitest_*` recommended) and verify
  the resulting `ir_module_module` states;
  `remove` unmounts, optionally resets module states and purges the clone.
- `filesystem.write_text` now preserves an existing file's permission mode across
  atomic replacement — edits of container-mounted configs (odoo.conf) no longer
  accidentally become unreadable to the container's odoo user.
- `module test <name>`: installs the module on a throwaway `oitest_<module>`
  database, runs `--test-enable --test-tags=/<module>` inside the web container,
  captures the full log (XDG state dir for adopted stacks), and prints PASS/FAIL
  (exit 3 on failure). A PASS is recorded in the installable-addons whitelist
  (`~/.config/odoo-installer/tested.toml`) with repo, branch, commit and log path.
- Installable-addons whitelist enforcement: `module install`/`upgrade` refuse
  untested modules unless `--allow-untested` is passed; `module list` shows a
  Tested column.
- Shallow single-branch clones (`--depth 1 --branch 19.0`) for owned clones —
  big repos like OCA/web now cost ~22 MB instead of hundreds.
- `config edit`: opens `config.toml` in `$EDITOR`, validates the result before
  saving, and refuses invalid edits (nothing is written).
- `test suite`: batch-tests every module on an instance's addons_path (filter by
  `--only <repo>` or `--modules m1,m2`), one scratch DB per module, sequential;
  PASSes feed the whitelist; Markdown/JSON reports with `--output` (repeatable,
  e.g. `--output report.md --output report.json`); rich summary; exit 3 on any
  failure; `--keep-db` keeps scratch databases.
- Test failure classification: logs are parsed into failure kinds (test failure,
  import error, not installable, addons_path, manifest, traceback, exit code).
- Test tooling: `tests/unit/test_filesystem.py` covers the filesystem adapter's
  mode-preservation semantics directly; the docker/git/github/system adapters
  (thin subprocess/network wrappers exercised live) are omitted from coverage,
  which is pinned at ≥ 85%.
