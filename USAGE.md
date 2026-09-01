# odoo-installer — Usage Guide

> **Works with 0.6.0+** · Read this in [Türkçe](USAGE.tr.md)
>
> Architecture, decisions and milestones live in [DEVELOPMENT.md](DEVELOPMENT.md).

`odoo-installer` is one CLI for your Odoo 19.0 fleet — it creates and manages Docker
stacks, installs OCA modules at the correct branch, proves modules work before they
ship, and shares those approvals across every machine you use. Everything it changes,
it shows you first.

---

## Contents

1. [At a glance](#1-at-a-glance)
2. [Installation](#2-installation)
3. [How it thinks](#3-how-it-thinks)
4. [Command reference](#4-command-reference)
5. [Files and configuration](#5-files-and-configuration)
6. [Recipes](#6-recipes)
7. [Safety and exit codes](#7-safety-and-exit-codes)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. At a glance

| Command family | What it gives you |
|----------------|-------------------|
| `doctor` | Instant host diagnosis — docker, compose, git, disk, ports, GitHub reachability |
| `install` | Host prerequisites via pacman/apt — Odoo itself is **never** installed on the host |
| `config` | Validated, atomic global configuration |
| `instance` | Full stack lifecycle: create, adopt existing stacks, start/stop, secret lookup, remove |
| `db` | Database list/create/drop/reset through the stack's own postgres container |
| `module` | OCA repos and modules: add with dependency visibility, list, search, install, upgrade, remove, test, approve |
| `test` | Batch test suites with reports + central whitelist sync |

Three ideas make it safe to use on a machine that also runs production:

- **Plan-first** — every mutation prints its exact plan and runs only with `--apply`
  (plus `--yes` when destructive). Applied plans stream live `[i/n]` step progress.
- **Tested-only installs** — `module install` refuses any module that has not passed
  a real test run or been explicitly approved.
- **Explicit database names** — the CLI never picks a database for you.

---

## 2. Installation

```bash
pip install odoo-installer            # from PyPI
# or from a checkout:
pip install .
# or, for development:
pip install -e ".[dev]"
```

For an isolated daily-use install (recommended over mixing with a dev venv):

```bash
pipx install odoo-installer           # or: uv tool install odoo-installer
```

Enable shell completion (bash/zsh/fish): `odoo-installer --install-completion`.

The CLI answers to three names: `odoo-installer`, `oii` and `python -m odoo_installer`.

> 💡 **Upgrading:** `pip install -U odoo-installer` (or `pipx upgrade
> odoo-installer`). If pip claims "already satisfied" right after a release, pin the
> version for one run — `pip install "odoo-installer==X.Y.Z"` — the index cache can
> lag a few minutes behind PyPI.

---

## 3. How it thinks

### 3.1 Instances

An **instance** is one Odoo stack in its own directory (default root
`~/odoo-instances/`):

```text
~/odoo-instances/<name>/
├── docker-compose.yml       # rendered from templates
├── .env                     # image, pg tag, http port, generated secrets
├── config/odoo.conf         # addons_path, rewritten by `module add`
├── addons/local/            # your own modules → /mnt/extra-addons
├── repos/<oca-repo>/        # OCA clones → /mnt/oca/<repo>
├── logs/                    # captured test logs (test-<module>-<ts>.log)
└── .odoo-installer.json     # instance manifest
```

The `db` service is never published on the host — all database access goes through
the stack (psql inside the `db` container).

### 3.2 Plan-first, with live progress

Mutating commands (`install`, `instance create/remove`, `module add/remove`,
`db drop/reset`) print a numbered plan of the exact commands and file writes and exit
0 **without doing anything** until you add `--apply` (plus `--yes` for destructive
confirmations). The printed plan *is* the executed code path. When a plan runs, every
step is announced as it happens:

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

`instance adopt <dir>` registers an **existing** compose stack (detected purely from
container labels) without rewriting its files. Adopted stacks are **read-mostly**:

- lifecycle (`start/stop/restart`), `exec`, `psql` and log access work normally;
- `start` uses `docker compose start` — the stack is never recreated;
- file edits (e.g. `module add` appending a mount) need an explicit `--yes`, and the
  CLI never recreates the containers — it tells you to do it yourself;
- the one mutating exception is `instance remove --apply --yes`, which tears the
  stack down (with `--remove-data`, its named volumes too) and deletes the directory.

### 3.4 The whitelist — tested means installable

`module test` and `test suite` install each module on a throwaway **scratch database**
(`oitest_<module>`, dropped afterwards unless `--keep-db`), run its tests inside the
container, and record every PASS in the whitelist
(`~/.config/odoo-installer/tested.toml`). `module install` / `module upgrade` refuse
anything that is not whitelisted unless you pass `--allow-untested`. That is the
contract: **only proven modules are installed.**

The whitelist is also **portable** — see [§4.7](#47-test--batch-testing-and-central-sync):
a small git repo can carry approvals to every machine, and `module approve` records
modules that are already proven on a running stack.

---

## 4. Command reference

Global: `--version` / `-V`, `--help` everywhere, plus a `version` command.

### 4.1 `doctor` — host diagnostics

```bash
odoo-installer doctor [--json]
```

Checks docker engine, compose plugin, docker group membership, git, disk space at the
instances root, port availability in the configured range and github.com
reachability. Exits **4** when a critical check fails.

### 4.2 `install` — host prerequisites

```bash
odoo-installer install [--apply]
```

Installs docker engine, the compose plugin and git via pacman (Arch) or apt
(Debian/Ubuntu). Never installs Odoo itself. Idempotent — a satisfied host is a no-op.

### 4.3 `config` — global configuration

```bash
odoo-installer config show [--json]
odoo-installer config set <key> <value>
odoo-installer config edit          # $VISUAL/$EDITOR, validated before saving
odoo-installer config path
```

| Key | Default | Meaning |
|-----|---------|---------|
| `instances_root` | `~/odoo-instances` | where new stacks live |
| `repo_root` | `~/odoo-repos` | where OCA clones go for adopted stacks |
| `default_pg_tag` | `17` | postgres image tag |
| `port_range_start` / `port_range_end` | `8069` / `8099` | auto-allocation range (≥ 1024) |
| `github_token_env` | `GITHUB_TOKEN` | env var holding a GitHub token |
| `tested_repo_url` | *(empty)* | central whitelist repo (see §4.7) |

Unknown keys are rejected; `set` validates values; `edit` validates the result and
saves nothing when invalid.

### 4.4 `instance` — stack lifecycle

#### Create

```bash
odoo-installer instance create <name> [--dir PATH] [--http-port N] [--image TAG]
                            [--pg-tag N] [--apply]
```

Renders the stack, starts it, waits for `/web/health`, registers the instance.

- **Port:** first free port in the configured range — a *stopped* stack does not
  reserve its port, so two instances can share one; pin with `--http-port`.
- **Secrets:** postgres and admin passwords are generated once and persisted. The
  master password is baked into `config/odoo.conf` (`admin_passwd`) and recorded in
  `.env` (`ADMIN_PASSWD`) — the official odoo image provides it through no
  environment variable, and the database manager never pre-fills the field.

#### List / show / secret / lifecycle

```bash
odoo-installer instance list
odoo-installer instance show <name>
odoo-installer instance secret <name> [--key KEY]
odoo-installer instance start|stop|restart <name>
```

`secret` prints one value from the instance's `.env` on its own line (default:
`ADMIN_PASSWD` — the master password; e.g. `--key POSTGRES_PASSWORD`). Unknown keys
are a hard error listing the available keys.

#### Remove

```bash
odoo-installer instance remove <name> [--remove-data] [--yes] [--apply]
```

Dry-run by default; executes only with `--apply --yes`. Volumes are **kept** unless
`--remove-data` (which destroys the named volumes declared in the compose file).
Works for **adopted stacks too** — removal is the one explicitly confirmed mutation
allowed on them.

#### Adopt an existing stack

```bash
odoo-installer instance adopt <dir> [--name NAME] [--db-user odoo] [--apply]
```

### 4.5 `db` — databases

```bash
odoo-installer db list [--instance NAME]
odoo-installer db create <db> [--instance NAME]           # idempotent
odoo-installer db drop <db> [--instance NAME] [--yes] [--apply]
odoo-installer db reset <db> [--instance NAME] [--yes] [--apply]
```

Executed through psql in the instance's `db` container. Database names are always
explicit; `postgres`/`template0`/`template1` are refused; `drop`/`reset` need
`--apply --yes`.

### 4.6 `module` — OCA repos and modules

#### Add a repo

```bash
odoo-installer module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH]
                         [--fork USER] [--instance NAME] [--yes] [--apply]
```

- The argument is a **repo** (`web`, `OCA/server-tools`) — not a module name. The
  19.0 branch is verified via the GitHub API before cloning; a module name passed by
  mistake gets a hint naming the repo that provides it.
- `--modules m1,m2` records only these modules — and the plan **verifies and shows
  their dependencies**, classified from GitHub raw manifests:

  ```console
  $ odoo-installer module add web --sparse --modules web_responsive
  ...
  3. → verify dependencies of web_responsive
       (core: base, web, mail, web_tour · already available: —)
  ```

  - **core** — verified by listing the running container's core addons dir;
  - **same-repo** — siblings in the same repo; they join the sparse clone
    automatically, so the later install cannot fail with "module not found";
  - **other-repo** — provider repo named in the plan; mounted later by
    `install --resolve-deps`;
  - **already available** — provided by the local addons or another mounted repo.
- `--sparse` performs a **blob-filtered partial clone**
  (`git clone --filter=blob:none --sparse --depth 1`) — only the requested modules
  download.
- `--repo PATH` mounts an existing checkout **as-is** — the CLI never switches its
  branch.
- `--fork USER` clones from your fork (`origin` = fork, `upstream` = OCA).
- The CLI appends the compose volume + `addons_path` (with backups and
  `docker compose config` validation) and **recreates** `web` (`up -d` — a plain
  restart would not mount the new volume). Adopted stacks: `--yes` required, and you
  recreate the stack yourself.
- After success it prints the next steps: `module test` → whitelist → `module install`.

#### List / search

```bash
odoo-installer module list [--instance NAME] [--db DB] [--json]
odoo-installer module search <query> [--limit N]
```

#### Install / upgrade

```bash
odoo-installer module install <name...> --db DB [--instance NAME]
                            [--allow-untested] [--resolve-deps]
odoo-installer module upgrade <name...> --db DB [--instance NAME]
                            [--allow-untested] [--resolve-deps]
```

Runs `odoo -d <db> -i/-u <name> --stop-after-init --http-port=8071` inside the web
container (never disturbing the serving process). Refuses modules that are not
whitelisted unless `--allow-untested`, and verifies `ir_module_module` states
afterwards (exit 1 if any module is not `installed`).

**Dependency resolution** — OCA modules often depend on other OCA modules. The CLI
reads each target's `__manifest__.py`:

- deps provided by **Odoo core** (verified by listing the web container's core
  addons) or by **already-mounted repos** just work;
- a dep whose provider repo is **not mounted** is refused with the provider named —
  add `--resolve-deps` to mount the provider repos automatically (from the whitelist
  catalog) and include the deps in the install;
- unknown providers are reported honestly with a `module search` hint.

#### Remove

```bash
odoo-installer module remove <repo> [--db DB] [--purge-repo] [--instance NAME]
                             [--yes] [--apply]
```

Unmounts, rewrites `addons_path`; `--db` resets the repo's modules to `uninstalled`;
`--purge-repo` deletes the clone (only clones the CLI owns).

#### Test one module

```bash
odoo-installer module test <name> [--instance NAME] [--keep-db]
```

Installs on a scratch DB, runs `--test-enable --test-tags=/<name>`, captures the log,
parses failure kinds, prints PASS/FAIL (exit 3 on failure) and records PASSes in the
whitelist.

#### Approve already-proven modules

```bash
odoo-installer module approve <name...> --db DB [--instance NAME]
```

For modules whose quality is already proven on a running stack: refuses anything not
in `installed` state in `--db`, then records the entries in the whitelist — no test
log required.

### 4.7 `test` — batch testing and central sync

```bash
odoo-installer test suite [--instance NAME] [--only REPO] [--modules m1,m2]
                          [--output report.md] [--output report.json] [--keep-db]
odoo-installer test pull [--apply]
```

`suite` tests every module on the addons_path sequentially (fresh `oitest_<module>`
scratch DB each), feeds PASSes into the whitelist, writes repeatable `.md`/`.json`
reports and exits **3** when anything fails. `--only` filters by source repo.

`pull` syncs the whitelist from the central repo configured in `tested_repo_url`:
it refreshes a local cache clone and **merges** the repo's `tested.toml` into the
active whitelist — union by module name, newer `tested_at` wins. Approvals made
anywhere spread to every machine that pulls; the CLI itself never needs updating for
new approvals.

---

## 5. Files and configuration

All files live in platformdirs locations; every write is atomic.

| File | Purpose |
|------|---------|
| `~/.config/odoo-installer/config.toml` | global config (§4.3) |
| `~/.config/odoo-installer/registry.toml` | instance registry |
| `~/.config/odoo-installer/tested.toml` | installable-addons whitelist |
| `<stack>/.odoo-installer.json` | per-instance manifest |
| `<stack>/repos/<repo>/` | OCA clones — git state is the truth |
| `<stack>/logs/` · `~/.local/state/odoo-installer/logs/<name>/` | test logs (created / adopted stacks) |

Precedence: **CLI flags > instance manifest > global config.toml > constants.**

GitHub tokens: read from the env var named by `github_token_env` (default
`GITHUB_TOKEN`); without one, discovery degrades gracefully.

---

## 6. Recipes

### 6.1 Bootstrap a machine

```bash
odoo-installer doctor && odoo-installer install --apply && odoo-installer doctor
```

### 6.2 Fresh dev instance with an OCA module

```bash
odoo-installer instance create dev --apply
odoo-installer db create odoo --instance dev
odoo-installer module add web --sparse --modules web_responsive --apply
odoo-installer module test web_responsive
odoo-installer module install web_responsive --db odoo
```

### 6.3 Work from your fork

```bash
odoo-installer module add server-tools --fork myuser --apply
```

### 6.4 Mount your own checkout (never mutated)

```bash
odoo-installer module add web --repo ~/dev/web-deploy --apply
```

### 6.5 Full installability report

```bash
odoo-installer test suite --output report.md --output report.json
```

### 6.6 Adopt production, inspect safely

```bash
odoo-installer instance adopt ~/Projects/my-odoo --apply
odoo-installer db list --instance my-odoo
odoo-installer module approve attribute_set pim --db odoo   # proven modules → whitelist
```

### 6.7 Share approvals across machines

```bash
# 1) on the proven stack: record approvals
oii module approve attribute_set pim product_attribute_set --db odoo
# 2) push the whitelist to the central repo (tested.toml at its root)
# 3) everywhere else:
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

### 6.8 Upgrade with confidence

```bash
oii module test my_module --keep-db          # prove it on a scratch DB
oii module upgrade my_module --db odoo       # only whitelisted modules get through
```

---

## 7. Safety and exit codes

- Plan-first on every mutation; live `[i/n]` progress while applying.
- Idempotent re-runs report `already satisfied` instead of redoing work.
- Explicit database names, always.
- Adopted stacks: never rewritten without `--yes`, never recreated by the CLI.
- Scratch DBs (`oitest_*`) are dropped unless `--keep-db`.

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | runtime error |
| 2 | usage error (Typer) |
| 3 | test failures (`module test`, `test suite`) |
| 4 | `doctor` critical check failed |

---

## 8. Troubleshooting

**`doctor` exits 4.** Read the FAIL row — it names the check and a fix hint. Common
causes: missing compose plugin, user not in the `docker` group, port range occupied.

**"modules not visible to this instance; run 'module add' first".** The module is not
on the addons_path — `module add` its repo (or `--repo` your checkout).

**"not tested yet: ...".** The whitelist has no entry — run `module test <name>`, or
pass `--allow-untested` deliberately.

**"branch '19.0' does not exist on OCA/<name>"** — with a hint. If you passed a module
name instead of a repo, the hint names the providing repo and the exact command.
Otherwise check the spelling or `module search <name>`.

**"missing OCA dependencies need mounting: ...".** The dependency resolver found
provider repos that are not mounted. Re-run with `--resolve-deps` to mount them
automatically (they must be whitelisted — `test pull` first if the approvals live in
the central repo).

**GitHub rate limiting / empty search results.** Set a token (`GITHUB_TOKEN` or the
env var named by `github_token_env`).

**Port already taken.** A stopped stack does not reserve its port — two instances can
share one. Start them one at a time, pin `--http-port`, or widen the range.

**"recreate it with your own tooling".** After `module add --yes` on an adopted stack,
recreate the web service yourself (`docker compose up -d web`) — a plain restart would
not mount the new volume.

**A module installed but Odoo reports it uninstalled.** `module install` verifies
`ir_module_module` states and exits 1 listing the offenders — check the dimmed output
tail and the module's dependencies.

**The database manager asks for a master password.** Nothing pre-fills that field:
the official `odoo` image passes no master password via env, and the shipped default
config has `admin_passwd` commented out. Read yours with
`odoo-installer instance secret <name>`; set your own by editing `admin_passwd` in
`config/odoo.conf` (and `.env`) then `instance restart`.

**Two instances want the same port.** See "Port already taken" — and remember a
stopped stack does not reserve its port.

**Where are the test logs?** Created instances: `<stack>/logs/`. Adopted instances:
`~/.local/state/odoo-installer/logs/<name>/`.
