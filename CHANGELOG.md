# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] - 2026-11-06

### Added

- **odoo.conf knobs `max_cron_threads`, `limit_memory_soft`, `limit_memory_hard`.**
  `[settings]` in `odoo-stack.toml` accepts them; memory values are strings
  (`"512"`, `"1536m"`, `"2g"`; k/m/g are 1024 powers, decimals are rejected) and
  are rendered into odoo.conf as bytes. Like the other knobs they persist in the
  manifest: an unspecified value keeps the manifest's, an explicit one wins.
  Each limit must be at least `256m` (Odoo applies the hard one as `RLIMIT_AS`,
  so `"0"` would keep every worker from starting), and the soft limit may not
  exceed the hard one when both are given; such a spec is rejected at load time.
- **Per-database first-initialisation defaults.** `oii apply` can now carry
  `[databases.<name>.defaults]` with `lang`, `country`, `timezone` and
  `currency`. On the database's first init only, the language is activated via
  Odoo's `--load-language`, and the ORM sets the admin/company locale, country,
  timezone, company currency and the default partner language. Later applies
  never touch those values, so customer changes win. Unknown country/currency/
  timezone values are skipped by the ORM rather than failing the install.

## [0.8.1] - 2026-09-23

### Fixed

- **`odoo.conf` rendered `proxy_mode = Trueworkers = 2`** when `workers` was
  set: a Jinja `{%- if %}` swallowed the newline and glued the two options onto
  one line — Odoo aborted with `optparse.OptionValueError` before serving.
  Found by the first real violetear deployment; the integration apply-spec now
  sets `workers` so a broken conf can never pass a health gate again.
- **Fresh creates sweep same-name leftovers before `up -d`.** A previous stack
  with the same project name (died mid-create, or deleted without
  `instance remove`) leaves containers/volumes behind — and postgres NEVER
  re-initializes an existing data dir, so the old `POSTGRES_PASSWORD` silently
  mismatched the freshly generated one and the web container crash-looped on
  auth. First-time create now runs `compose down -v --remove-orphans` first;
  manifest-backed re-runs never sweep (data-destructive). Found live on
  rootless podman during the violetear acceptance run.

## [0.8.0] - 2026-09-22

### Added

- **`oii apply` — declarative desired state.** An `odoo-stack.toml` describes one
  instance end to end: stack knobs (`image`, `pg_tag`, `http_port` or `[ingress]`),
  `[[repos]]` (OCA GitHub URLs, optional sparse module lists), `[databases.<name>]`
  with `install` module lists, `[resources]` (memory/cpus) and `[settings]`
  (proxy_mode/list_db/workers). `apply` converges the instance to the spec by
  assembling the same idempotent plans the interactive commands use — stack
  ensure, repo add/remove diff, database creation, module installs — and is safe
  to re-run (second apply reports satisfied steps). Fresh stacks converge in two
  phases: the repo/db/module detail is planned once the stack exists, because
  those plans are built from the manifest. `--json` prints the plan. This is the
  primitive a hosting control plane loops on.
- **Backups: `oii backup create|list|verify|prune|restore`.** pg_dump `-Fc` +
  filestore tar streamed through the runtime's own stdio (`compose exec -T`) —
  container-uid-owned bytes never need host-side ownership fixes — plus a
  checksummed `manifest.json` per backup. `restore` is plan-first `--apply --yes`:
  stop web, recreate the db, pg_restore, swap the filestore via a throwaway
  container, start, wait healthy — and refuses corrupted backups. `prune` keeps
  the newest N (plan-first). Optional `backup_hook` config ships each backup
  offsite (runs with `OII_BACKUP_DIR` set).
- **Ingress mode.** `instance create --ingress-network NAME [--ingress-alias slug]`
  (or the spec's `[ingress]`): the web service joins an external network under an
  alias and publishes no host port — reverse-proxy routing, voslodoo/violetear
  style. Implies `proxy_mode`. The db service never joins the ingress network.
- **`instance health [--wait N] [--json]`** — HTTP `/web/health` for published
  stacks, container healthcheck for ingress stacks. **`instance logs [--tail]`**.
- **`module upgrade-repos`** (v1.1 roadmap item): fetch + checkout the tip of each
  mounted repo's branch, record the new commits, report which mounted modules
  changed between commits, and recreate the web service when something moved.
  The in-Odoo upgrade stays explicit (`module upgrade <changed> --db ...`).
- **Per-instance Odoo admin credentials.** `.env` now carries
  `ODOO_ADMIN_LOGIN`/`ODOO_ADMIN_PASSWORD` (generated at create); apply's install
  step passes them via `-r/-w` only for a database's FIRST initialization, so
  later installs never reset a changed password.

### Changed

- **Filestore is a named compose volume** (`filestore:`) instead of the image's
  anonymous volume: survives plain `down`, removed by `down -v`, and streams
  cleanly for backups. Stacks created before 0.8.0 keep working; their Odoo
  filestore data stays in the old anonymous volume until re-created (copy it
  manually if it matters).
- **Compose template**: `mem_limit`/`cpus` from `[resources]`; odoo.conf renders
  `workers`, `proxy_mode`, `list_db`.
- **`spec.http_port` (and `--http-port`) are requests**: apply validates them
  against live ports and registry reservations (rootless podman's userspace
  port forwarder would otherwise silently double-bind).

## [0.7.0] - 2026-09-22

### Added

- **Podman support (rootless-first).** New `container_runtime` config key
  (`auto` | `podman` | `docker`, default `auto` prefers Podman when usable).
  All engine interaction goes through one runtime-agnostic compose adapter;
  podman's `ps` JSON shape (Labels as a map, Ports as a list) and its
  no-healthcheck `inspect` failure are normalized, so every command — create,
  db, module, test, adopt — works unchanged under either runtime.
- **Honest podman doctor checks.** Under podman, `doctor` verifies the rootless
  socket is actually listening (`podman compose version` succeeds even when it
  is not, but `up -d` would fail), and warns when linger or
  `podman-restart.service` are disabled (rootless containers then stop at
  logout/boot). `install` plans the fixes: `podman.socket`, linger,
  `podman-restart.service`.
- **`instance list --json` / `instance show --json` / `db list --json`.**
  `instance show` now reports per-container states structurally
  (`reachable`, `containers[].state`) instead of echoing `compose ps` text.
- **Integration test layer** (`pytest -m integration`, opt-in via
  `OII_INTEGRATION=1`): a full real-stack lifecycle on rootless podman —
  create → wait-healthy → db create/list → stop/start → remove — inside a
  throwaway XDG config and a session-scoped `podman system service` socket.

### Fixed

- **Port reservations survive stopped stacks.** Port allocation now skips (and
  `--http-port` validates against) ports claimed in the registry by other
  instances — a stopped stack holds no socket, but its claim must not be
  handed to a new instance. Re-running `create` with an explicit `--http-port`
  equal to the instance's pinned port is accepted again instead of "in use".

## [0.6.4] - 2026-09-12

### Added

- **`module install`/`module upgrade` now accept Odoo CORE modules** (`sale`,
  `account`, `l10n_generic_coa`, ...): visibility is verified against the web
  container's core addons listing (with an honest "is the stack running?" error
  when it is down), and the tested-addons whitelist does not gate core modules.
  Scratch-DB scenarios like "chart of accounts + sale + OCA accounting module" now
  work end to end.
- **`module test --with sale`:** install extra core/OCA modules into the scratch DB
  in a SEPARATE setup stage BEFORE the test stage — accounting modules whose test
  data needs a chart of accounts / journals no longer fail for missing setup
  (false FAILs). Verified live: `partner_statement` tests passed only this way —
  Odoo 19 applies chart templates AFTER the module install loop, so a single
  combined `-i` run runs the tests before the journals exist. A broken setup stage
  is reported as a FAIL with its log; `--test-tags /<module>` still scopes the
  EXECUTED tests to the module itself. (Note: `l10n_generic_coa` does not exist in
  Odoo 19.0 — `account` brings the default chart itself.)

### Fixed

- **Recreate guarantee across dependency provisions:** the main plan's recreate now
  shares its changed-state with the dependency plans, so a re-add whose ONLY change
  is a new provider mount still recreates the web service (previously the new
  mount could sit dead in compose until the next manual recreate).
- **List format consistency:** `module install`/`upgrade`/`approve` accept both
  `a b c` and `a,b,c` (previously a comma list was treated as ONE module name),
  matching `module add --modules`.

## [0.6.3] - 2026-09-12

### Fixed

- **Whole-repo adds now provision cross-repo dependencies too.** `oii module add
  <repo>` without `--modules` previously reported "no external dependencies — 0
  unmet" while `date_range`/`report_xlsx`-style providers were actually missing.
  The module set is only known after the clone, so provisioning is now deferred to
  a late phase: right after the repo is placed, every discovered module's
  cross-repo deps are re-resolved (catalog + probing), their provider repos are
  sparse-cloned at 19.0 and mounted, and the web service is recreated once.
  Unresolvable names in the bulk path are warnings, not aborts.
- Dependency probing no longer requires a running web container: when the core
  listing is unavailable, cross-repo providers are still discovered and
  provisioned; only the unexplainable names are tolerated with a loud warning
  (module-based adds still abort on unexplainable deps when the container IS up).
- Dry-run "Dependency plan" sections now state that the mount goes live together
  with the main repo's single recreate (the dep plans intentionally do not
  recreate).

## [0.6.2] - 2026-09-12

### Added

- **Automatic cross-repo dependency provisioning in `module add`:** dependencies that
  live in a DIFFERENT OCA repo (e.g. `account_financial_report` needs `date_range`
  from OCA/server-ux and `report_xlsx` from OCA/reporting-engine) are discovered and
  provisioned automatically — provider repos are sparse-cloned at the 19.0 branch into
  the instance's repos dir, mounted, written to addons_path and recorded BEFORE the
  main repo, and the web service is recreated once at the end. Disable with
  `--no-resolve-deps`.
- Provider discovery: the whitelist catalog (tested.toml) is asked first; anything it
  cannot explain is probed across the OCA org's repos (org listing via the public API
  once, then parallel raw-manifest probes — no API rate-limit cost per probe). The
  walk is transitive, so a dep's own cross-repo deps are resolved in the same run.
  Dry-run plans SHOW each discovered provider as a separate "Dependency plan".
- An already-mounted sparse repo whose clone lacks a needed dep is now EXTENDED
  (sparse set grows) by both `module add` and `module install --resolve-deps`
  (`to_extend` resolution), instead of failing later with "module not found".
- `module install --resolve-deps` now also falls back to OCA probing for deps the
  whitelist catalog does not know.
- Renamed OCA repos keep working: the branch check follows GitHub redirects
  (e.g. `OCA/account-financial-report` → `OCA/account-financial-reporting`).

## [0.6.1] - 2026-09-12

### Fixed

- The `module add` dependency step no longer floods the plan with every Odoo core
  addon (~600 lines): `core` now lists only the actual core dependencies of the
  requested modules, long buckets are truncated to the first 8 names with a
  `… (+N more)` tail, and the post-run summary counts only non-empty buckets
  (including the previously missing `available` count).

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

## [0.6.0] - 2026-09-01

### Added

- **Dependency visibility in `module add` dry-run:** for `--modules m1,m2`, the plan
  verifies and SHOWS each module's dependencies, read from GitHub raw manifests
  (no clone needed). Every dependency is classified: `core` (verified by listing
  the web container's core addons), `same-repo` (sibling modules in the same repo),
  `other-repo` (provider named from the whitelist catalog; mounted later by
  `install --resolve-deps`), `already available` (mounted/local), and
  `unknown provider` (with an honest "container offline" label when the core list
  cannot be obtained).
- Same-repo sibling dependencies now join the sparse clone automatically, so a
  later `module install` cannot fail with "module not found" for a sibling it
  depends on. A `verify dependencies` step re-checks against the real manifests
  after the clone and aborts with actionable guidance if something is unmet.

## [0.5.3] - 2026-09-01

### Fixed

- **Critical regression from 0.5.2's blob-filtered sparse clone:** a second
  `module add <repo> --sparse --modules X` NARROWED the sparse checkout to X
  (`git sparse-checkout set` replaces the pattern list), silently deleting every
  previously mounted module's files from the clone while they stayed "installed" in
  the database — Odoo then failed with "Could not get content for ..." asset errors
  and a broken page ("A css error occured").
- The sparse set and the manifest record now EXTEND with the union of previously
  requested modules and the new ones; narrowing never happens implicitly.
- The recorded module list no longer loses previously requested modules on re-add.

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
