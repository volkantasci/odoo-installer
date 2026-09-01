# DEVELOPMENT.md — `odoo-installer`

Development guide for **odoo-installer**: a professional, pip-installable Python CLI that
installs, configures, and manages **Odoo 19.0 Docker stacks** and their modules — including
correct-branch OCA module management and automated installability testing of every core and
OCA module.

This document is the source of truth for architecture, scope, conventions, and milestones.
Any change to an approved decision must be reflected here first.

---

## 1. Approved decisions

Locked in with the project owner before implementation:

| # | Decision | Choice |
|---|----------|--------|
| D1 | Runtime model | **Docker only.** The CLI never installs Odoo natively. It generates and manages `docker compose` stacks (web + db) and runs all Odoo commands inside containers. |
| D2 | Odoo version | **19.0 only** for v1. The version is a constant (`ODOO_VERSION = "19.0"`), not a user-facing matrix. Default image: `odoo:19.0` (Docker Hub, active; dated tags like `19.0-20260817` exist). |
| D3 | Host OS support | **Arch first** (pacman adapter, tested for real on this machine), **Debian/Ubuntu next** (apt adapter in a later milestone). |
| D4 | Language & packaging | Python `>= 3.11`, src layout, `hatchling` build backend, console script `odoo-installer` (+ short alias `oii`), developed and used from a local `.venv`. |
| D5 | CLI framework | **Typer + Rich** (typed commands, tables, shell completion). |
| D6 | Config | **TOML**: global `~/.config/odoo-installer/config.toml`, per-instance manifest `<stack>/.odoo-installer.json`, global registry `~/.config/odoo-installer/registry.toml`. |
| D7 | Safety | System-changing and destructive commands are **plan-first**: without `--apply` / `--yes` they print exactly what they would do and exit 0. Idempotent re-runs are a requirement. |
| D8 | Git access | Plain `git` via `subprocess` (no GitPython). GitHub metadata via **httpx**. |

### Non-goals for v1

- Native (systemd / non-Docker) Odoo installation.
- Odoo versions other than 19.0 (the code keeps the version a single constant so later support is cheap).
- GUI / TUI.
- Database backup/restore, SMTP setup wizard, reverse-proxy/TLS generation (future roadmap).

---

## 2. Product scope — command surface

```text
odoo-installer doctor [--json]
    Host diagnostics: docker engine, compose plugin, git, disk space, port conflicts,
    github.com reachability, user-in-docker-group. Exit code 4 when a critical check fails.

odoo-installer install [--apply]
    Install HOST PREREQUISITES only (docker engine, compose plugin, git) via pacman/apt.
    Never installs Odoo itself — that is what the stack is for.

odoo-installer instance create <name> [--dir PATH] [--http-port N] [--image TAG] [--pg-tag N] [--apply]
    Render a complete compose stack (compose file, .env, config/odoo.conf), `up -d`,
    wait for /web/health, register the instance.
odoo-installer instance list | show <name>
odoo-installer instance start|stop|restart <name>
odoo-installer instance remove <name> [--remove-data] [--yes]
    remove defaults to keeping volumes/DBs; --remove-data destroys the stack's named
    volumes (compose down -v). Works for adopted stacks too.
odoo-installer instance adopt <dir>
    Register an EXISTING compose stack (e.g. ~/Projects/my-odoo) without rewriting it.
    Adopted stacks are managed read-mostly: exec/psql/logs are allowed; file rewriting is not
    (the one mutating exception is an explicit `instance remove --apply --yes`).

odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH] [--apply]
    Clone OCA/<repo> at the branch matching 19.0, mount it into the stack, rewrite
    addons_path, restart web. --repo mounts an existing local checkout instead of cloning.
odoo-installer module list [--instance NAME] [--json]
odoo-installer module search <query>
    GitHub API: find OCA repos and the modules they contain for 19.0.
odoo-installer module install <name...> [--db DB]
odoo-installer module upgrade <name...> [--db DB]
    Run `odoo -d <db> -i/-u <name> --stop-after-init --http-port=8071` inside the web container.
odoo-installer module remove <name...> [--db DB] [--purge-repo] [--yes]

odoo-installer db list [--instance] | create <db> [--instance]
    The database name is always an explicit positional argument, never a default.
odoo-installer db drop|reset <db> [--instance] [--yes] [--apply]
    Executed through psql in the db container. drop/reset always require --yes.

odoo-installer module test <name> [--instance] [--keep-db]
    Install the module on a throwaway DB (oitest_<module>_<ts>), run its tests
    (--test-enable --test-tags /<module>), capture and parse the log, print PASS/FAIL.
odoo-installer test suite [--instance <name>] [--only <repo>] [--modules m1,m2]
                          [--output report.{md,json}] [--keep-db]
    Batch over the modules of every repo on the stack's addons_path (filter by
    repo or module list); one scratch DB (oitest_<module>) per module, sequential;
    PASS results are recorded in tested.toml; Markdown/JSON report + rich summary
    table. Exit 3 if any module fails.

odoo-installer config show | set <key> <value> | edit | path
odoo-installer version
```

Manual, step-by-step usage is a first-class goal: every composite action
(`install`, `instance create`, `module add`) is decomposable into the individual commands
above, and every step is idempotent so users can drive installation manually.

---

## 3. Architecture

### 3.1 Layering

```text
┌─────────────────────────────────────────────────────────┐
│ cli/        Typer commands: parse → core → render (rich) │  thin, no logic
├─────────────────────────────────────────────────────────┤
│ core/       Business logic, pure Python, no direct I/O   │  fully unit-testable
│   prereqs, stack, instances, modules, runner, tester,    │
│   plan, dbms                                            │
├─────────────────────────────────────────────────────────┤
│ adapters/   The ONLY code that touches the world          │  behind Protocols
│   docker, git, github, system, filesystem               │
├─────────────────────────────────────────────────────────┤
│ schemas.py  pydantic models (GlobalConfig, Registry,     │
│   InstanceManifest, RepoRecord, TestedModule, ...)       │
│ config.py   config resolution + persistence              │
│ console.py  rich output helpers, plan/dry-run rendering  │
│ exceptions.py  typed error hierarchy                     │
└─────────────────────────────────────────────────────────┘
```

Rules:

1. **cli/ commands never import adapters.** Commands build inputs, call `core`, render
   results. The single exception is the composition root `cli/deps.py`, which wires the
   real adapters into a `Container` (rule 2).
2. **core/ depends on adapters only through `typing.Protocol` interfaces** (e.g.
   `DockerLike`, `GitLike`, `SystemLike`), injected as constructor arguments. Tests pass
   fakes; production wires real adapters in `cli/`.
3. **All external effects go through adapters** — no `subprocess`, `httpx`, or raw file
   writes outside `adapters/` and `config.py`.
4. Every mutating core function returns a **plan object** (list of concrete steps) that the
   CLI either renders (dry-run) or executes (`--apply`). This makes dry-run exact by
   construction — the printed plan *is* the executed code path.

### 3.2 Package layout

```text
src/odoo_installer/
├── __init__.py            # __version__
├── __main__.py            # python -m odoo_installer
├── constants.py           # ODOO_VERSION="19.0", DEFAULT_IMAGE="odoo:19.0", ports, names
├── exceptions.py
├── schemas.py             # GlobalConfig, Registry(Entry), InstanceManifest, RepoRecord, TestedModule/Registry
├── config.py              # TOML load/merge/save, path resolution (platformdirs)
├── console.py             # rich console, tables, plan renderer, --json output
├── cli/
│   ├── main.py            # Typer app assembly, global callbacks, version, completion
│   ├── deps.py            # composition root: builds Container with real adapters (rule 2)
│   ├── common.py          # shared command helpers (instance resolution, tested-pass recording)
│   ├── doctor.py, install.py, instance.py, module.py, db.py, test.py, config.py
├── core/
│   ├── prereqs.py         # host prerequisite checks + install plans (pacman/apt)
│   ├── stack.py           # compose/odoo.conf/.env rendering, health wait, addons_path rewrite
│   ├── instances.py       # registry + per-instance manifest CRUD
│   ├── modules.py         # OCA repo resolution, cloning, module discovery
│   ├── runner.py          # odoo command execution inside the web container
│   ├── tester.py          # scratch-DB test runs, log parsing, report building
│   ├── plan.py            # Step model + apply_steps executor (dry-run/--apply)
│   └── dbms.py            # database list/create/drop/reset via psql
├── adapters/
│   ├── docker.py          # `docker` / `docker compose` subprocess wrapper
│   ├── git.py             # clone/fetch/checkout/sparse-checkout/rev-parse
│   ├── github.py          # httpx: repo search, branch existence, rate-limit handling
│   ├── system.py          # distro detect (Arch/Debian), pacman/apt command building
│   └── filesystem.py      # paths, atomic file writes, dir scaffolding
├── templates/             # docker-compose.yml.j2, odoo.conf.j2, .env.j2 (jinja2)
└── py.typed
tests/
├── conftest.py            # normalizes TERM/NO_COLOR/FORCE_COLOR so rich output stays plain text in assertions
└── unit/                  # fakes only, offline, < 5 s
    └── fakes.py           # FakeDocker, FakeGit, FakeGitHub, FakeSystem, FakeFs

`tests/integration/` (real git/docker, marker `integration`) is deferred to v1.1 — see §8.
```

### 3.3 Dependencies

Runtime: `typer`, `rich`, `pydantic>=2`, `httpx`, `jinja2`, `tomli-w` (reads use stdlib
`tomllib`), `platformdirs`.
Dev: `pytest`, `pytest-cov`, `pytest-mock`, `ruff`, `mypy`, `pre-commit`, `build`, `twine`.

---

## 4. The generated Docker stack

Default instances root: `~/odoo-instances/`. One directory per instance:

```text
~/odoo-instances/<name>/
├── docker-compose.yml       # rendered from templates/
├── .env                     # COMPOSE_PROJECT_NAME, ODOO_IMAGE, PG_TAG, HTTP_PORT, POSTGRES_PASSWORD, ADMIN_PASSWD
├── config/odoo.conf         # addons_path rewritten by `module add`
├── addons/local/            # user's own modules (mounted as /mnt/extra-addons)
├── repos/<oca-repo>/        # OCA clones (each mounted as /mnt/oca/<repo>)
├── logs/                    # captured test/install logs (test-<module>-<ts>.log)
└── .odoo-installer.json     # instance manifest (see §5)
```

Reference compose shape (what the template must render):

```yaml
services:
  web:
    image: odoo:19.0            # .env: ODOO_IMAGE
    restart: unless-stopped
    depends_on: { db: { condition: service_healthy } }
    ports: ["8069:8069"]        # .env: HTTP_PORT
    environment:
      DB_HOST: db
      DB_PORT: "5432"
      DB_USER: odoo
      DB_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ./config:/etc/odoo
      - ./addons/local:/mnt/extra-addons
      # module add appends one line per OCA repo: ./repos/<repo>:/mnt/oca/<repo>
    command: ["odoo", "-c", "/etc/odoo/odoo.conf"]
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8069/web/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 30s
  db:
    image: postgres:17          # .env: PG_TAG (configurable)
    restart: unless-stopped
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U odoo"]
      interval: 5s
      timeout: 5s
      retries: 30
volumes: { pgdata: }
```

- The db service is **not** published on the host; all DB access goes through the stack.
- `addons_path` in `odoo.conf` starts as `/mnt/extra-addons` and gains `/mnt/oca/<repo>`
  entries when repos are added; `module add` rewrites the file and restarts `web`.
- Port allocation: first free port in 8069–8099 unless `--http-port` is given. A port
  is "free" at allocation time only — a stopped stack does not reserve its port, so two
  instances can end up sharing one; start them one at a time or pin ports explicitly.
- Master password: `create` generates a random `admin_passwd`, bakes it into
  `config/odoo.conf` and records it as `ADMIN_PASSWD` in `.env`. The official odoo
  image provides the master password through NO environment variable (its entrypoint
  only wires the DB connection vars), and the database-manager form is never pre-filled
  server-side — a "pre-filled" password field is the browser's saved-password autofill.

---

## 5. State model

| File | Scope | Content |
|------|-------|---------|
| `~/.config/odoo-installer/config.toml` | global user config | instance root, default ports, default pg tag, GitHub token env var name |
| `~/.config/odoo-installer/registry.toml` | instance registry | `name → {dir, http_port, created_at, adopted: bool}` |
| `~/.config/odoo-installer/tested.toml` | installable-addons whitelist | `module → {repo, branch, commit, db, log_path}`; written by `module test` / `test suite` PASSes; `module install`/`upgrade` refuse modules that are not listed unless `--allow-untested` |
| `<stack>/.odoo-installer.json` | per instance | schema_version, odoo_version, image, pg_tag, applied steps, added repos `{repo, url, branch, commit, modules, mount}`, adopted flag |
| `<stack>/repos/<repo>/` | OCA clones | git state is the truth for branch/commit; manifest records the last synced commit |

Config precedence: **CLI flags > instance manifest > global config.toml > constants.**
All config writes are atomic (write temp file + rename).

---

## 6. OCA integration rules

The tool must behave exactly like the documented OCA workflow:

1. **Branch rule.** An OCA repo is always checked out at `origin/19.0` — verified to exist
   via the GitHub API *before* cloning. The tool never guesses or falls back to `master`/`main`.
   A missing `19.0` branch is a hard error naming the repo.
2. **Remotes.** Clones get `origin = https://github.com/OCA/<repo>.git`. If the user
   supplies `--fork <user>`, `origin` is the fork and `upstream` is OCA (mirrors the
   manual workflow).
3. **Sparse mode.** `--sparse` uses `git sparse-checkout` limited to the requested modules
   (plus their manifest dirs) to keep clones small; default is a full clone.
4. **Existing checkouts.** `--repo <path>` mounts an existing local checkout instead of
   cloning — this is how the tool coexists with the `~/dev/<repo>` + `~/dev/<repo>-deploy`
   worktree pattern used on this machine: the CLI mounts whatever path it is told to and
   never switches branches in a checkout it does not own.
5. **Module discovery.** A module = a directory containing `__manifest__.py`. Discovery
   scans mounted repos; `module list` merges filesystem state with
   `ir_module_module` state (via psql) and reports install state per DB.
6. **Install/upgrade semantics.** Runs inside the `web` container as
   `odoo -d <db> -i/-u <module> --stop-after-init --http-port=8071` (alternate port
   convention avoids clashing with the serving process — same as manual practice).
7. **Adopted stacks are read-mostly.** `instance adopt` never rewrites compose files;
   it may only append addons mounts if explicitly confirmed, otherwise reports what the
   user must add by hand. The single mutating exception is `instance remove --apply
   --yes`, which tears the stack down (with `--remove-data`, its named volumes too) and
   deletes the stack directory — an explicit, confirmed destructive action, never a
   silent rewrite.

---

## 7. Safety, idempotency, errors

- **Plan-first:** `install`, `instance create/remove`, `module add/remove`,
  `db drop/reset`, and any host package operation print a numbered plan of the exact
  commands and file writes, then require `--apply` (or `--yes` for prompts) to execute.
- **Idempotency:** every step checks current state first (package installed? repo already
  cloned at right commit? addons_path already contains the entry?) and reports
  `already satisfied` instead of redoing work. Re-running a completed install is a no-op.
- **Exit codes:** `0` success · `1` runtime error · `2` usage error (Typer default) ·
  `3` test failures (test suite) · `4` doctor critical check failed.
- **Error hierarchy** (`exceptions.py`): `OdooInstallerError` base → `PrerequisiteError`,
  `StackError`, `GitError`, `GitHubError`, `ConfigError`, `ModuleError`, `TestFailureError`.
  The CLI renders user-facing messages and maps errors to the exit codes above
  (no `--debug` flag exists in v1.0).
- **Live instance care:** commands that could touch a production `odoo` DB require an
  explicit `--db` value (never a default) when the stack is adopted.
  Scratch DBs used by `test` are named `oitest_*` and dropped afterwards unless `--keep-db`.

---

## 8. Testing strategy

Pyramid, enforced by CI:

| Level | Scope | Rules |
|-------|-------|-------|
| Unit (`tests/unit/`) | core + cli against `FakeDocker`, `FakeGit`, `FakeGitHub`, `FakeSystem`, `tmp_path` | offline, deterministic, < 5 s, no markers; every core function's plan generation AND execution paths covered |
| Integration (`tests/integration/`, marker `integration`, opt-in via `OII_INTEGRATION=1`) — **deferred to v1.1** | real `git clone` of a small OCA repo, real `docker compose up` on an ephemeral port, full `instance create → module add → module install → test module` cycle on a throwaway stack | planned: run locally and in a CI docker job; tear down everything in `finally` |
| Live smoke (manual, documented) | any adopted stack | read-mostly commands + one scratch-DB module test; never mutates the production DB. Note: this machine currently has no live stack (the former `~/Projects/odoo-docker` was decommissioned) |

**Deferral note (recorded at v0.1.0):** the integration layer and its CI docker job
were deferred to v1.1 — the M4/M5 acceptance relied on the unit layer plus the
live-stack smoke instead. The `integration` marker remains registered in
`pyproject.toml`, but until the layer lands `pytest -m integration` selects zero tests
and exits 5, so it is **not** part of the v0.1.0 quality gates.

Quality gates (every milestone, all green before merge):

```bash
ruff format --check . && ruff check .
mypy src
pytest                                  # unit
# v1.1: pytest -m integration           # when docker/git available
pytest --cov=src/odoo_installer --cov-report=term-missing   # keep ≥ 85% overall
```

Log-parsing tests use inline recorded-style fixture logs (shaped from real 19.0 runs)
covering: pass, test failure, import error, missing manifest, "not installable",
addons-path warning.

CI (GitHub Actions): job `lint` (name `lint & types`; ruff format/check, mypy) and job
`unit` on Python 3.11/3.12/3.13. The docker-based `integration` job lands together with
the v1.1 integration layer; the workflow file documents this.

---

## 9. Packaging & release

```toml
[project]
name = "odoo-installer"
requires-python = ">=3.11"
dependencies = [ ... ]           # see §3.3
[project.scripts]
odoo-installer = "odoo_installer.cli.main:app"
oii = "odoo_installer.cli.main:app"
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- Developed with `pip install -e ".[dev]"` in `.venv`; used exactly like that on this machine.
- Versioning: SemVer, single source in `src/odoo_installer/__init__.py`
  (`hatchling` reads it via `[tool.hatch.version]`).
- Release: `python -m build`, `twine check dist/*`, changelog in `CHANGELOG.md`
  (Keep a Changelog). v1 target release: `0.1.0` at M6.

---

## 10. Milestones

Each milestone ends with all quality gates green and a demo of the listed "done" behavior.
One logical change per commit; Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`,
`test:`) on branches `feat/<slug>` — this repo is not an OCA repo, so OCA commit prefixes
do not apply here.

### M0 — Scaffold
pyproject, src layout, `.venv`, Typer app with `--version`, ruff/mypy/pytest configured,
pre-commit, CI workflow, `python -m odoo_installer` works.
**Done when:** `pip install -e ".[dev]" && odoo-installer --version` succeeds; CI green.

### M1 — Config + doctor
`config.py` (TOML load/merge/save, precedence), `constants.py`, registry read/write,
`doctor` with all host checks, rich table + `--json`, exit code 4 semantics.
**Done when:** doctor reflects this machine's real state (docker present, 8069 busy);
unit tests cover config precedence and every check's pass/fail branch.

### M2 — Host prereqs + instance lifecycle
`install` (pacman adapter, plan-first, `--apply`), `instance create/list/show/start/stop/
restart/remove`, template rendering (compose/.env/odoo.conf), health wait, registry +
manifest writes, port auto-allocation.
**Done when:** a real instance `oitest` is created on this machine (dry-run → apply),
answers `/web/health`, `remove` leaves nothing behind; re-running `create` is a no-op.

### M3 — Adoption + databases
`instance adopt` (detect web/db services, ports, existing addons mounts), `db
list/create/drop/reset` via psql exec.
**Done when:** `~/Projects/odoo-docker` is adopted, `db list` matches `psql -l`, `db drop`
refuses without `--yes`.

### M4 — OCA modules
`module add` (branch verification, clone/sparse/existing-checkout, mount + addons_path
rewrite + restart), `module list/search/install/upgrade/remove`, GitHub search adapter.
**Done when:** an OCA module is added from GitHub at `origin/19.0`, installed into a
scratch DB inside the adopted stack, and listed with correct install state; integration
test runs the same flow against a throwaway stack.

### M5 — Test suite
`test module` (scratch DB, `--test-tags /<module>`, log capture to `logs/`, parser),
`test suite` with per-module scratch DBs, md/json reports, rich summary, exit code 3.
**Done when:** `test suite` on the adopted stack produces a correct PASS/FAIL report for
every module on the addons_path; fixture-log unit tests prove each failure class parses.

### M6 — Polish & release ✔ (v0.1.0, 2026-08-31)
README, `--help` UX pass, shell completion (`--install-completion`), error message audit,
coverage ≥ 85%, `python -m build` + `twine check`, CHANGELOG, tag `0.1.0`, optional
TestPyPI publish.
**Done:** coverage 90.7% (filesystem adapter unit-tested; subprocess adapters omitted with
rationale in `pyproject.toml`), wheel + sdist pass `twine check` and a clean-venv smoke
test, README/CHANGELOG finalized, `v0.1.0` tagged. TestPyPI publish left as an optional
follow-up; published to PyPI as 0.1.1 (2026-09-01).

**Deferral note:** the "integration test runs the same flow against a throwaway stack"
clauses in the M4/M5 acceptance criteria were satisfied via the unit layer + live-stack
smoke instead; the throwaway-stack integration test layer is deferred to v1.1 (see §8).

### v1.1 roadmap (priority order)

1. **Integration test layer** (`tests/integration/`, marker `integration`) and the CI
   docker job — the biggest open gap: automated end-to-end
   `instance create → module add → module install → test module` on a throwaway stack,
   run locally and in CI.
2. `module upgrade-repos` — re-sync OCA clones to their recorded 19.0 branches.
3. apt adapter validation on a real Debian/Ubuntu machine (D3's "later milestone").
4. Publish to PyPI — ✔ done (0.1.1, 2026-09-01); README switched back to
   `pip install odoo-installer`.
5. Backlog from §1 non-goals: DB backup/restore, SMTP setup wizard, reverse-proxy/TLS
   generation.

---

## 11. Local development setup

```bash
cd /home/volkan/Projects/dev/odoo-installer
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pre-commit install
pytest                                  # unit suite
odoo-installer --version
```

Notes for this machine: system Python is 3.14 (Arch); if a pinned dev dependency lags on
3.14, create the venv with an older interpreter rather than dropping the floor below 3.11.
There is currently no live Odoo stack on this machine (the former manual stack at
`~/Projects/odoo-docker` was decommissioned) — port auto-allocation and the adopted-stack
care rules in §7 exist because adopted stacks may be production.

## 12. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Python 3.14 + pinned deps lag | floor stays 3.11; pin dev deps; venv may use an older interpreter |
| Odoo weekly image tags drift | default `odoo:19.0`; `--image` override recorded in the manifest |
| OCA branch moves fast (ocabot bumps) | manifest stores last synced commit; `module upgrade-repos` (deferred to v1.1) re-syncs |
| Log parsing fragility | parser matched against recorded fixture logs from real runs; exit code is primary signal |
| Destructive ops on production stacks | plan-first + `--yes`, explicit `--db`, adopted stacks read-mostly (only explicit removal mutates), scratch DB naming `oitest_*` |
| GitHub rate limits | `GITHUB_TOKEN`/`GH_TOKEN` env support; graceful degradation to offline discovery |
