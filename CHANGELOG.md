# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-01

### Added

- `module approve <name...> --db DB [--instance NAME]`: whitelist modules whose
  quality is already proven on a running stack. Refuses anything that is not in
  `installed` state in the explicit database (verified via `ir_module_module` before
  anything is written), then records the entries in `tested.toml` — no test log
  required.
- Central whitelist repo: new config key `tested_repo_url` and
  `odoo-installer test pull [--apply]`. The pull refreshes a local cache clone of a
  small git repo whose root holds a `tested.toml` and merges its entries into the
  active whitelist — union by module name, newer `tested_at` wins. Approvals made on
  any machine (test PASSes or `module approve`) spread to every machine that pulls;
  the CLI itself does not need updating for new approvals, only the repo does.

## [0.5.2] - 2026-09-01

### Changed

- `module add --sparse` now performs a **blob-filtered partial clone**
  (`git clone --filter=blob:none --sparse --depth 1`) instead of a full shallow clone
  followed by a sparse-checkout trim: only the requested modules' blobs download, so
  huge repos (OCA/web, OCA/l10n-turkey, ...) cost megabytes, not the whole snapshot.
- The plan itself is now honest about the sparse scope: the first step reads
  `sparse-clone <url> ... (blob-filtered, only: <modules>)` instead of a bare
  `place <url> ...` that looked like a full-repo add.
- Re-running `module add --sparse` on an existing clone narrows the sparse set before
  checking out, keeping blob fetches minimal.

## [0.5.1] - 2026-09-01

### Fixed

- `module add` now explains the most common mistake: passing a MODULE name
  (e.g. `web_responsive`) where a REPO name (`web`) is expected. When the whitelist
  catalog knows the module, the error names the providing repo and prints the exact
  command (`oii module add web`); otherwise it points at `module search`.

## [0.5.0] - 2026-09-01

### Added

- **OCA dependency resolver.** `module install`/`upgrade` now read each target
  module's `__manifest__.py` dependencies. Dependencies provided by Odoo core are
  verified by listing the web container's core addons dir and never block; deps
  provided by already-mounted repos just work; a dependency whose provider repo is
  NOT mounted is refused with a clear message naming the provider — pass
  `--resolve-deps` to mount the provider repos automatically (sparse, via the same
  plan-first machinery) and include the dependencies in the install.
- **Whitelist records now carry dependency info:** `module test` and `module approve`
  store each module's OCA dependencies in tested.toml (`deps` field), so the central
  whitelist repo doubles as a module→repo/dependency catalog that the resolver
  queries — approvals made anywhere teach every machine how to install dependents.

## [0.3.2] - 2026-09-01

### Fixed

- **Module mounts now actually reach the container:** after `module add`/`module
  remove` the CLI runs `docker compose up -d <web>` instead of `docker compose
  restart`. A plain restart reuses the old container and would never mount the new
  volume, leaving the module invisible to `module install`/`test` inside Odoo.
- `module remove` now validates the edited compose file with `docker compose config`
  and restores the original on failure (previously only `module add` did).
- `module add` refuses a different repo whose short name would mount onto an already
  used container path (e.g. adding `myfork/web` while `OCA/web` is mounted at
  `/mnt/oca/web`) instead of writing a conflicting duplicate mount.
- Mount idempotency now accepts both the absolute and the relative (e.g.
  `./repos/oca-web`) form of a mount line, so a hand-written relative mount never
  gets a duplicate absolute twin.

### Changed

- After `module add` the CLI prints the next steps (`module test` → whitelist →
  `module install --db`) and adopted stacks are told to *recreate* the web service
  (`docker compose up -d web`), not restart it.

## [0.3.1] - 2026-09-01

### Added

- Live plan progress: whenever a plan is applied (`--apply`), every step is announced
  as `[i/n] description` the moment it starts and its result note (or
  `✔ already satisfied`) follows immediately — for `install`, `instance
  create/adopt/remove`, `module add/remove` and `db drop/reset` alike, instead of
  reporting everything only after the whole plan finished.

## [0.3.0] - 2026-09-01

### Added

- `instance secret <name> [--key KEY]`: prints one secret from the instance's `.env`
  on its own line (plain text, script-friendly). Default key is `ADMIN_PASSWD` — the
  Odoo master password; e.g. `--key POSTGRES_PASSWORD` reads the DB password. A
  missing key is a hard error that lists the available keys.

### Changed

- Usage guides (EN/TR) now document the secret command and the master-password lookup
  flow; DEVELOPMENT.md §2 and the README command list include `instance secret`.

## [0.2.0] - 2026-09-01

### Added

- `instance remove` now also removes **adopted** stacks (previously refused): it tears
  the stack down with its own compose file, deletes the stack directory and
  unregisters the instance. The only explicitly confirmed (`--apply --yes`) mutating
  action allowed on read-mostly adopted stacks.
- `--remove-data` on `instance remove` now destroys the **named volumes declared in
  the stack's compose file** (`docker compose down -v`) — not just the CLI-created
  pgdata volume — so adopted stacks can be fully decommissioned by the CLI.

### Changed

- Documentation: detailed usage guides added in English (`USAGE.md`) and Turkish
  (`USAGE.tr.md`), shipped in the sdist; troubleshooting entries for master-password
  lookup (the official odoo image passes no master password via env; the database
  manager form is never pre-filled server-side) and shared-port pitfalls; stale
  live-stack references replaced with generic examples.

## [0.1.1] - 2026-09-01

### Fixed

- DEVELOPMENT.md synced with the v0.1.0 implementation state: composition root
  (`cli/deps.py`) and `core/plan.py` added to the package layout, real schema model
  names, the `.env`/compose template contents in §4, `tested.toml` in the state model,
  and the removed `--debug` claim.
- The deferred integration test layer and the CI docker job are now recorded as a v1.1
  roadmap item with a v1.1 priority list.
- README install instructions no longer claim PyPI availability for the unpublished
  0.1.0 release.
- Removed the stale `--debug` traceback claim from the exceptions module docstring.

### Added

- First publication to PyPI (`pip install odoo-installer`).

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
