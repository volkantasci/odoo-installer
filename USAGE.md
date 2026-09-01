# odoo-installer — Usage Guide

A detailed, practical guide to installing, configuring and managing **Odoo 19.0 Docker
stacks** with `odoo-installer` — including correct-branch OCA module management and
automated installability testing.

For architecture, design decisions and the development plan, see
[DEVELOPMENT.md](DEVELOPMENT.md). This guide documents the commands as they behave in
v0.1.x.

---

## Table of contents

1. [What the tool does and does not do](#1-what-the-tool-does-and-does-not-do)
2. [Installation](#2-installation)
3. [Core concepts](#3-core-concepts)
4. [Command reference](#4-command-reference)
5. [Configuration files and state](#5-configuration-files-and-state)
6. [Common workflows](#6-common-workflows)
7. [Safety rules and exit codes](#7-safety-rules-and-exit-codes)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. What the tool does and does not do

`odoo-installer` manages Odoo 19.0 **only through Docker**. It never installs Odoo
natively on the host: every instance is a `docker compose` stack (a `web` service and a
`db` service) generated, started, and managed by the CLI. On top of that it provides:

- **OCA module management** — clones OCA repositories at the verified `origin/19.0`
  branch, mounts them into a stack, and rewrites `addons_path` for you.
- **Installability testing** — installs each module on a throwaway scratch database,
  runs its test suite inside the container, parses the log, and records PASSes in an
  installable-addons whitelist. `module install` refuses untested modules.
- **Plan-first safety** — every destructive or system-changing command prints exactly
  what it would do and exits without doing anything until you pass `--apply` (and
  `--yes` for destructive confirmations). Idempotent re-runs are guaranteed.

**Non-goals (v1):** native (non-Docker) Odoo, other Odoo versions, GUI/TUI, database
backup/restore, SMTP wizard, reverse-proxy/TLS generation.

### Requirements

- Python ≥ 3.11
- Docker engine + the `compose` plugin
- `git`
- Linux host (Arch Linux is the reference platform; Debian/Ubuntu package adapters are
  in place but less battle-tested)

Run `odoo-installer doctor` to verify your host.

---

## 2. Installation

```bash
pip install odoo-installer            # from PyPI (0.1.1+)
# or from a checkout:
pip install .
# or, for development:
pip install -e ".[dev]"
```

Enable shell completion (bash/zsh/fish):

```bash
odoo-installer --install-completion
```

The CLI is also available as `oii` and via `python -m odoo_installer`.

---

## 3. Core concepts

### 3.1 Instances

An **instance** is one Odoo stack in its own directory (default root:
`~/odoo-instances/`). Each instance gets:

```text
~/odoo-instances/<name>/
├── docker-compose.yml       # rendered from templates
├── .env                     # image, pg tag, http port, generated secrets
├── config/odoo.conf         # addons_path rewritten by `module add`
├── addons/local/            # your own modules (mounted as /mnt/extra-addons)
├── repos/<oca-repo>/        # OCA clones (each mounted as /mnt/oca/<repo>)
├── logs/                    # captured test logs (test-<module>-<ts>.log)
└── .odoo-installer.json     # instance manifest
```

The `db` service is **not** published on the host — all database access goes through
the stack (psql inside the `db` container).

### 3.2 Plan-first (dry-run by default)

Commands that change anything (`install`, `instance create/remove`, `module add/remove`,
`db drop/reset`) print a numbered plan of the exact commands and file writes and exit 0
**without executing anything** until you add `--apply`. Destructive operations
additionally require `--yes`. The printed plan *is* the executed code path — dry-run is
exact by construction. When a plan is applied, every step is announced live as
`[i/n] description` followed by its result, so you always know which stage is running:

```console
$ odoo-installer instance create dev --apply
[1/8] create the instance directory
  ✔ created
[2/8] render docker-compose.yml
  ✔ written
...
[8/8] start the stack (docker compose up -d) and wait for /web/health
  ✔ healthy
✔ instance 'dev' ready at http://localhost:8069
```

### 3.3 Adopted stacks

`instance adopt <dir>` registers an **existing** compose stack (e.g. a stack you built
by hand before using the tool) without rewriting its files. Adopted stacks are managed
**read-mostly**:

- `start/stop/restart`, `exec`, `psql`, and log access work normally.
- `start` uses `docker compose start` — the stack is never recreated.
- File edits (e.g. `module add` appending a mount) require an explicit `--yes`, and the
  CLI **never restarts** an adopted stack — it tells you to restart with your own
  tooling instead.
- The one mutating exception is `instance remove --apply --yes`, which tears the stack
  down and deletes its directory (see §4.4).

### 3.4 The tested-addons whitelist

`module test` and `test suite` record every PASS in `~/.config/odoo-installer/tested.toml`
(module → repo, branch, commit, db, log path). `module install`/`module upgrade`
**refuse** any module that has no whitelist entry, unless you pass `--allow-untested`.
This is the contract of the tool: only tested modules are installable.

### 3.5 Scratch databases

`module test` and `test suite` never touch your real databases. Each module is tested
on a throwaway database named `oitest_<module>`, which is dropped afterwards unless you
pass `--keep-db`. Database names are **always explicit** CLI arguments — there is no
default database.

---

## 4. Command reference

Global options: `--version` / `-V` (show version and exit), `--help` everywhere.
There is also a `version` command that prints the bare version number.

### 4.1 `doctor` — host diagnostics

```bash
odoo-installer doctor [--json]
```

Checks: docker engine, compose plugin, docker group membership, git, disk space at the
instances root, port availability in the configured range (8069–8099), and github.com
reachability. Renders a table (or JSON) and **exits with code 4** when a critical check
fails.

```console
$ odoo-installer doctor --json | head
```

### 4.2 `install` — host prerequisites

```bash
odoo-installer install [--apply]
```

Installs **host prerequisites only** — docker engine, the compose plugin, and git —
through pacman (Arch) or apt (Debian/Ubuntu). It never installs Odoo itself; that is
what stacks are for. Without `--apply` it prints the plan; with `--apply` it executes.
On a satisfied host it reports that nothing needs to be done (re-runs are no-ops).

### 4.3 `config` — global configuration

```bash
odoo-installer config show [--json]        # resolved configuration
odoo-installer config set <key> <value>    # set one key (validated)
odoo-installer config edit                 # open $VISUAL/$EDITOR in-place, validated
odoo-installer config path                 # print the config file path
```

Keys and defaults (see §5.1 for the full table):

| Key | Default | Meaning |
|-----|---------|---------|
| `instances_root` | `~/odoo-instances` | where new stacks are created |
| `repo_root` | `~/odoo-repos` | where the CLI clones OCA repos for adopted stacks |
| `default_pg_tag` | `17` | postgres image tag |
| `port_range_start` / `port_range_end` | `8069` / `8099` | auto-allocation range (must be ≥ 1024) |
| `github_token_env` | `GITHUB_TOKEN` | env var name holding a GitHub token |

Unknown keys are rejected — typos in `config.toml` fail loudly. `set` coerces and
validates values with pydantic; `edit` validates the result before saving and saves
nothing if the file is invalid.

```bash
odoo-installer config set port_range_end 8095
odoo-installer config set github_token_env GH_TOKEN
```

### 4.4 `instance` — stack lifecycle

#### Create

```bash
odoo-installer instance create <name> [--dir PATH] [--http-port N] [--image TAG]
                            [--pg-tag N] [--apply]
```

Renders the complete stack (`docker-compose.yml`, `.env`, `config/odoo.conf`), starts it
with `docker compose up -d`, waits for `/web/health`, and registers the instance.

- **Port:** first free port in the configured range (8069–8099) unless `--http-port` is
  given. The allocated port is pinned in the manifest, so re-runs keep it.
- **Secrets:** the postgres password and admin password are generated on first run and
  persisted in `.env` — re-runs never rotate them.
- **Idempotency:** re-running `create` for an existing, healthy instance is a no-op.
- Default image is `odoo:19.0`; override with `--image` (recorded in the manifest).

```console
$ odoo-installer instance create dev            # dry-run: prints the plan
$ odoo-installer instance create dev --apply    # execute
✔ instance 'dev' ready at http://localhost:8069
```

#### List / show / secret / lifecycle

```bash
odoo-installer instance list
odoo-installer instance show <name>       # manifest details + docker compose ps
odoo-installer instance secret <name> [--key KEY]   # print a .env secret
odoo-installer instance start <name>      # created: up -d · adopted: compose start
odoo-installer instance stop <name>       # docker compose stop
odoo-installer instance restart <name>    # docker compose restart
```

`secret` prints one value from the instance's `.env` on its own line (plain text, so it
pipes cleanly). The default key is `ADMIN_PASSWD` — the Odoo master password; other
keys such as `POSTGRES_PASSWORD` work with `--key`. A missing key is a hard error that
lists the available keys.

#### Remove

```bash
odoo-installer instance remove <name> [--remove-data] [--yes] [--apply]
```

Dry-run by default; executes only with `--apply --yes`. By default the stack's data
volumes (and with them your databases) are **kept**; `--remove-data` destroys the named
volumes declared in the compose file (`docker compose down -v`); bind-mounted data goes
away with the stack directory. Works for **adopted stacks too** — removal is the one
explicitly confirmed destructive action allowed on them. When re-creating an instance,
its data is preserved unless you asked for it to be destroyed.

#### Adopt an existing stack

```bash
odoo-installer instance adopt <dir> [--name NAME] [--db-user odoo] [--apply]
```

Detects the stack purely from container labels (compose project, web/db services,
images, published port), writes only the odoo-installer manifest and registry entry,
and never rewrites the stack files. See §3.3 for the read-mostly rules.

```console
$ odoo-installer instance adopt ~/Projects/my-odoo --apply
detected: project my-odoo, web service web (odoo:19.0) on port 8069, ...
✔ instance 'my-odoo' adopted (read-mostly)
```

### 4.5 `db` — databases

All database operations are executed through `psql` in the instance's `db` container.
The database name is **always** an explicit positional argument.

```bash
odoo-installer db list [--instance NAME]                  # names + sizes
odoo-installer db create <db> [--instance NAME]           # idempotent
odoo-installer db drop <db> [--instance NAME] [--yes] [--apply]
odoo-installer db reset <db> [--instance NAME] [--yes] [--apply]
```

- `create` reports `already exists` when the database is present.
- `drop`/`reset` are plan-first and execute only with `--apply --yes`. They print a red
  warning in dry-run.
- `reset` = drop + recreate (empty database).
- The protected databases `postgres`, `template0` and `template1` are refused.
- `--instance` defaults to the only registered instance; with several registered
  instances it must be given.

```console
$ odoo-installer db create odoo --instance dev
✔ database 'odoo': created
```

### 4.6 `module` — OCA repositories and modules

#### Add a repo

```bash
odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH]
                         [--fork USER] [--instance NAME] [--yes] [--apply]
```

- `<oca-repo>` may be `server-tools` or `OCA/server-tools`.
- The **19.0 branch is verified via the GitHub API before cloning** — a repo without a
  `19.0` branch is a hard error. The tool never guesses or falls back to `master`.
- Clones are shallow, single-branch (`--depth 1 --branch 19.0`).
- `--modules m1,m2`: record only these modules (the whole repo is still mounted unless
  `--sparse` is used).
- `--sparse`: git sparse-checkout limited to the requested modules — keeps big repos
  (e.g. OCA/web) small.
- `--repo PATH`: mount an **existing local checkout** instead of cloning. The CLI never
  switches branches or mutates a checkout it does not own.
- `--fork USER`: clone from your fork (`origin = your fork`, `upstream = OCA`).
- Afterwards the CLI appends the compose volume + `addons_path` entry (with automatic
  backups and `docker compose config` validation) and restarts `web` — for stacks it
  created. On adopted stacks it requires `--yes` and reports the restart for you to do.

```console
$ odoo-installer module add web --sparse --modules web_responsive --apply
repo web at branch 19.0 -> ~/odoo-instances/dev/repos/web:/mnt/oca/web
✔ web added
```

#### List / search

```bash
odoo-installer module list [--instance NAME] [--db DB] [--json]
odoo-installer module search <query> [--limit N]
```

`list` merges filesystem discovery with `ir_module_module` state: for each module it
shows the source repo, the recorded commit, and — with `--db` — the install state in
that database, plus a Tested column from the whitelist. `search` queries the OCA GitHub
organization.

#### Install / upgrade

```bash
odoo-installer module install <name...> --db DB [--instance NAME] [--allow-untested]
odoo-installer module upgrade <name...> --db DB [--instance NAME] [--allow-untested]
```

- Runs inside the `web` container:
  `odoo -d <db> -i/-u <name> --stop-after-init --http-port=8071` (an alternate port so
  the serving process on 8069 is never disturbed).
- `--db` is **required** — there is no default database. For experiments use scratch
  names (`oitest_*`).
- Refuses modules without a tested.toml entry unless `--allow-untested` is given.
- Verifies the resulting `ir_module_module` states afterwards and exits 1 if any module
  is not in `installed` state.

```console
$ odoo-installer module install web_responsive --db oitest_try
✔ installed: web_responsive
```

#### Remove

```bash
odoo-installer module remove <repo> [--db DB] [--purge-repo] [--instance NAME]
                           [--yes] [--apply]
```

Unmounts the repo and rewrites `addons_path` (with backups). With `--db`, the repo's
modules are reset to `uninstalled` in that database first. `--purge-repo` also deletes
the clone directory. Adopted stacks need `--yes` with `--apply`.

#### Test one module

```bash
odoo-installer module test <name> [--instance NAME] [--keep-db]
```

The heart of the whitelist workflow:

1. creates/drops any stale scratch database `oitest_<name>`,
2. installs the module there,
3. runs `odoo --test-enable --test-tags=/<name>` inside the web container,
4. captures the full log to `logs/test-<name>-<ts>.log`,
5. parses the log into failure kinds (test failure, import error, "not installable",
   missing manifest, addons_path warning, bare exit code),
6. prints PASS/FAIL and exits 3 on failure,
7. on PASS records the module in `tested.toml` (repo, branch, commit, log path).

```console
$ odoo-installer module test web_responsive
PASS web_responsive (3.2s) — log: .../logs/test-web_responsive-20260901.log
✔ web_responsive recorded as tested/installable (whitelist: .../tested.toml)
```

### 4.7 `test suite` — batch testing

```bash
odoo-installer test suite [--instance NAME] [--only REPO] [--modules m1,m2]
                          [--output report.md] [--output report.json] [--keep-db]
```

Tests **every module on the instance's addons_path**, sequentially (Odoo limitation:
one scratch database at a time), with a fresh `oitest_<module>` scratch DB per module.
PASSes feed the whitelist. `--only` restricts to one source repo (`web` or `OCA/web`);
`--modules` pins an explicit list. `--output` is repeatable and writes a Markdown
and/or JSON report. Exits **3** when any module fails.

```console
$ odoo-installer test suite --only web --output report.md --output report.json
[1/12] web_responsive (web)
PASS web_responsive (3.1s)
...
12 modules: 11 passed, 1 failed   → exit 3
✔ report written: report.md
✔ report written: report.json
```

---

## 5. Configuration files and state

All files live under the XDG config dir (`~/.config/odoo-installer/`); all writes are
atomic (temp file + rename).

| File | Purpose |
|------|---------|
| `config.toml` | global user config (see table in §4.3) |
| `registry.toml` | instance registry: `name → {dir, http_port, created_at, adopted}` |
| `tested.toml` | installable-addons whitelist: `module → {repo, branch, commit, db, log_path}` |
| `<stack>/.odoo-installer.json` | per-instance manifest: schema version, odoo version, image, pg tag, added repos `{repo, url, branch, commit, modules, mount}`, adopted flag |
| `<stack>/repos/<repo>/` | OCA clones — git state is the truth for branch/commit |

Config precedence: **CLI flags > instance manifest > global config.toml > constants.**

GitHub access: the CLI reads a token from the env var named by `github_token_env`
(default `GITHUB_TOKEN`) to raise rate limits; without a token it degrades gracefully
to offline discovery.

---

## 6. Common workflows

### 6.1 Bootstrap a new machine

```bash
odoo-installer doctor                # verify the host (exit 4 = fix first)
odoo-installer install               # dry-run: what would be installed
odoo-installer install --apply       # docker engine, compose plugin, git
odoo-installer doctor                # should be all green now
```

### 6.2 A fresh dev instance with an OCA module, the manual way

```bash
odoo-installer instance create dev --apply
odoo-installer db create odoo --instance dev

odoo-installer module search "responsive"
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive      # scratch DB, PASS → whitelist
odoo-installer module install web_responsive --db odoo
```

Each step is decomposable and idempotent — if anything fails you can fix and re-run
just that step.

### 6.3 Work on your fork of an OCA repo

```bash
odoo-installer module add server-tools --fork myuser --apply
# origin = https://github.com/myuser/server-tools.git, upstream = OCA
```

### 6.4 Use your existing local checkout (worktree pattern)

```bash
odoo-installer module add web --repo ~/dev/web-deploy --apply
# mounts the checkout as-is; the CLI never switches its branch
```

### 6.5 Full installability report for a stack

```bash
odoo-installer test suite --output report.md --output report.json
# exit 3 when any module fails; PASSes are whitelisted
```

### 6.6 Adopt the production stack and inspect it safely

```bash
odoo-installer instance adopt ~/Projects/my-odoo --apply
odoo-installer db list --instance my-odoo         # must match psql -l
odoo-installer module list --instance my-odoo --db odoo
odoo-installer module test web_responsive         # scratch DB only, never the odoo DB
```

Read-mostly commands plus scratch-DB testing only — the adopted stack's files and the
production `odoo` database are never touched without explicit, guarded actions.

### 6.7 Upgrading modules safely

```bash
odoo-installer module test my_module --keep-db          # verify on a scratch DB first
odoo-installer module upgrade my_module --db odoo       # only if PASSed the whitelist
```

---

## 7. Safety rules and exit codes

- **Plan-first:** `install`, `instance create/remove`, `module add/remove`,
  `db drop/reset` print a numbered plan and require `--apply` (plus `--yes` for
  destructive prompts) to execute.
- **Idempotency:** every step checks current state first (package installed? repo
  cloned at the right commit? addons_path already contains the entry?) and reports
  `already satisfied` instead of redoing work.
- **Explicit database names:** the CLI never invents a database name.
- **Adopted stacks:** never rewritten without `--yes`, never restarted by the CLI.
- **Scratch DBs:** `oitest_*` names, dropped after use unless `--keep-db`.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | runtime error (e.g. module not installed, plan step failed) |
| 2 | usage error (Typer default) |
| 3 | test failures (`module test`, `test suite`) |
| 4 | `doctor` found a critical check failure |

Scripts can rely on these codes, e.g. `odoo-installer doctor || exit 1` style gating,
or treating 3 as "fix the module".

---

## 8. Troubleshooting

**`doctor` exits 4.**
Read the FAIL row — it names the check and a fix hint. Common cases: missing compose
plugin, user not in the `docker` group, port range occupied.

**"module ... not visible to this instance; run 'module add' first".**
The module is not on the instance's addons_path. `module add` the repo (or mount your
checkout with `--repo`).

**"not tested yet: ... — run 'module test <name>' first".**
The tested.toml whitelist has no entry for the module. Run `module test <name>` (or
`test suite`), or bypass deliberately with `--allow-untested`.

**"repo ... has no 19.0 branch".**
The OCA repo does not carry a 19.0 branch. Either wait for it or point `--repo` at a
checkout you prepared yourself.

**GitHub rate limiting / empty search results.**
Set a token: `export GITHUB_TOKEN=ghp_...` (or the env var named in your
`github_token_env` config) and retry. Without a token, offline discovery still works.

**Port already taken.**
`instance create` auto-picks the first free port in 8069–8099 — but a *stopped* stack
does not reserve its port, so two instances can end up registered on the same one. Start
them one at a time, pin a port with `--http-port`, or widen the range via
`config set port_range_end ...`.

**Adopted stack says "restart with your own tooling".**
After `module add --yes` on an adopted stack, the CLI updates the files but never
restarts containers — restart the stack yourself (e.g. `./restart.sh`) to apply the new
mount.

**A module installed but Odoo reports it uninstalled.**
`module install` verifies `ir_module_module` states and exits 1 listing the offenders —
check the last lines of the captured output (shown dimmed) and the module's
dependencies.

**The database manager asks for a master password — where is it?**
Nothing fills that field for you: the official `odoo` image provides the master
password through **no environment variable** (its entrypoint only wires the DB
connection vars, and the shipped default config has `admin_passwd` commented out), and
Odoo never pre-fills the form server-side. What looks like a pre-filled field is your
browser's saved-password autofill. `instance create` generates a random master password
and stores it in `<stack>/.env` (`ADMIN_PASSWD=...`) and in
`<stack>/config/odoo.conf` (`admin_passwd = ...`). Read it with the CLI:
`odoo-installer instance secret <name>` (or `--key POSTGRES_PASSWORD` for the DB
password). To set your own, edit `admin_passwd` in `config/odoo.conf` (and `.env` for
consistency) and run `odoo-installer instance restart <name>`.

**Two instances want the same port (8069).**
Port auto-allocation picks the first port that is free *right now* — a stopped stack
does not reserve its port. If two registered instances share a port, start them one at
a time, or recreate one on another port (e.g. `instance create <name> --http-port 8070`).

**Where are the test logs?**
Created instances: `<stack>/logs/test-<module>-<ts>.log`. Adopted instances:
`~/.local/state/odoo-installer/logs/<name>/` (XDG state dir — the CLI never writes into
adopted stacks).
