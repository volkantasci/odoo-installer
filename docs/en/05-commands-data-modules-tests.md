# 5. Commands — data, modules & tests

[🇹🇷 Türkçe](../tr/05-komutlar-veri-modul-test.md) · [🇬🇧 English](README.md)

---

This page covers:

| Command | Purpose |
|---------|---------|
| [`db`](#db--databases) | list, create, drop, reset databases |
| [`module`](#module--oca-repos-and-modules) | manage OCA repos, modules, tests and approvals |
| [`test`](#test--batch-testing-and-central-sync) | batch suites and whitelist sync |

---

## `db` — databases

```bash
oii db list   [--instance NAME] [--json]
oii db create <db> [--instance NAME]
oii db drop   <db> [--instance NAME] [--yes] [--apply]
oii db reset  <db> [--instance NAME] [--yes] [--apply]
```

All commands run `psql` **inside the instance's `db` container** — PostgreSQL is
never exposed on the host.

### Rules

- The database name is **always an explicit argument** — the CLI never picks one.
- Names must match `[a-z][a-z0-9_]{0,62}`.
- `postgres`, `template0` and `template1` are protected: dropping them is refused.
- `create` is idempotent and additive — it reports `already exists`.
- `drop` / `reset` are plan-first and execute only with `--apply --yes`.
- `reset` = drop + recreate (empty).

### Examples

```bash
oii db list --instance dev
oii db create odoo --instance dev

# dry runs — show the exact SQL steps:
oii db drop staging --instance dev
oii db reset staging --instance dev

# execute (destructive):
oii db reset staging --instance dev --apply --yes
```

```console
$ oii db create odoo --instance dev
✔ database 'odoo': created
```

> 💡 Which instance? When exactly **one** instance is registered, `--instance` may
> be omitted. With several registered, the CLI asks you to specify it — it never
> guesses.

---

## `module` — OCA repos and modules

```bash
oii module add | list | search | install | upgrade | upgrade-repos
          | remove | test | approve
```

---

### `module add` — add an OCA repo

```bash
oii module add <oca-repo> [--modules m1,m2] [--sparse] [--repo PATH]
                    [--fork USER] [--instance NAME] [--yes] [--apply]
                    [--resolve-deps / --no-resolve-deps]
```

The argument is a **repository**, not a module:

| Accepted form | Example |
|---------------|---------|
| short name (owner defaults to `OCA`) | `web`, `server-tools` |
| explicit owner | `OCA/server-tools` |

| Option | Meaning |
|--------|---------|
| `--modules m1,m2` | record only these modules (they join the sparse set) |
| `--sparse` | blob-filtered partial clone of only the requested modules |
| `--repo PATH` | mount an existing local checkout **as-is** (never mutated; must already be on `19.0` if attached to a branch) |
| `--fork USER` | clone from your fork (`origin` = fork, branch verified there) |
| `--instance NAME` | target instance |
| `--yes` | required for file edits on adopted stacks |
| `--resolve-deps` / `--no-resolve-deps` | toggle automatic cross-repo provisioning (default: on) |
| `--apply` | execute the plan |

#### What happens at plan time

1. **Branch verification** — `origin/19.0` is checked via the GitHub API. A module
   name passed by mistake produces a hint naming its repo.
2. **Dependency report** — with `--modules`, each module's `__manifest__.py` is read
   from GitHub and every dependency is classified
   (`core` / `same-repo` / `other-repo` / `already available`).
3. **Provider plans** — repos that provide cross-repo dependencies get their own
   sparse plans, shown as separate `Dependency plan:` sections.

#### What happens at apply time

1. dependency provider plans are applied **first**;
2. the repo is cloned/mounted (sparse when requested);
3. modules are discovered and the requested ones are verified present;
4. compose volume + `addons_path` are edited — backup-protected, with
   `docker compose config` validation and automatic restore on failure;
5. the repo is recorded in the manifest;
6. the `web` service is **recreated once** (`up -d`) so all new mounts go live.

On **adopted stacks**, files are edited only with `--yes`, the web service is never
recreated by the CLI, and it tells you to recreate it yourself
(`docker compose up -d web`).

At the end it prints the next steps:

```console
✔ web added
next: `module test <module>` to whitelist it, then `module install <module> --db <db>`
```

#### Examples

```bash
# one module, sparse, with dependency verification:
oii module add web --sparse --modules web_responsive

# whole repo (all modules discovered after the clone):
oii module add server-tools

# your fork:
oii module add server-tools --fork myuser --apply

# an existing checkout, mounted as-is:
oii module add web --repo ~/dev/web-deploy --apply
```

#### Dependency notes

- With the container **offline**, probing still runs; only unexplainable names are
  tolerated with a warning (Odoo re-checks them at install time).
- Whole-repo adds resolve providers **after** the clone, from the real manifests.
- `--no-resolve-deps` skips provisioning; the later install will stop with guidance
  if a dependency is missing.

---

### `module list` / `module search`

```bash
oii module list [--instance NAME] [--db DB] [--json]
oii module search <query> [--limit N]
```

`list` shows all modules visible on the instance's addons path (local addons +
mounted repos), together with source repo, commit and whitelist status. With
`--db`, it also shows each module's `ir_module_module` state from that database.

`search` queries the OCA GitHub org:

```console
$ oii module search "responsive"
OCA repos matching 'responsive'
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Repository ┃ Default branch ┃ Description          ┃
...
```

> 💡 Without a GitHub token, discovery degrades gracefully but is rate-limited.
> Set `GITHUB_TOKEN` (or the env var named by `github_token_env`) to raise limits.

---

### `module install` / `module upgrade`

```bash
oii module install <name...> --db DB [--instance NAME]
                              [--allow-untested] [--resolve-deps]
oii module upgrade <name...> --db DB [--instance NAME]
                              [--allow-untested] [--resolve-deps]
```

Both run inside the web container:

```text
odoo -d <db> -i/-u <name> --stop-after-init --http-port=8071
```

The alternate port `8071` guarantees they never disturb the serving process on
`8069`.

| Option | Meaning |
|--------|---------|
| `--db DB` | **required** — the target database, always explicit |
| `--allow-untested` | skip the whitelist gate deliberately |
| `--resolve-deps` | mount missing OCA provider repos automatically and include the dependencies in the install |
| `--instance NAME` | target instance |

#### Gates applied before running

1. **Visibility** — the module must be on the instance's addons path, or be an
   Odoo **core** module (verified by listing the running container's core addons).
   Not visible? The error tells you to run `module add` first.
2. **Whitelist** — OCA modules must be tested/approved, else the command refuses:
   `not tested yet: <name> — run 'module test <name>' first, or pass --allow-untested`.
   Core modules are never gated.
3. **Dependencies** — see below.

#### Dependency resolution

- Core and already-mounted deps just work.
- A dep whose provider repo is **not mounted** → refused with the provider named:
  `missing OCA dependencies need mounting: … — re-run with --resolve-deps`.
  With `--resolve-deps`, the provider repo is mounted
  (whitelist catalog first, then OCA-wide manifest probing) and the dependency is
  included in the run.
- A mounted **sparse** clone that lacks the dep extends its sparse set
  automatically.
- Truly unknown providers are reported with a `module search` hint.

#### After running

The CLI verifies `ir_module_module` states and exits `1` if anything is not
`installed`, listing the offenders. Success looks like:

```console
$ oii module install web_responsive --db odoo --instance dev
✔ installed: web_responsive
```

Both argument styles work: `module install a b c` and `module install a,b,c`.

#### Core modules

Odoo core modules (`sale`, `account`, `stock`, …) are accepted, verified against
the running container, and never gated. If the container is down the verification
is impossible and the command says so.

---

### `module remove`

```bash
oii module remove <repo> [--db DB] [--purge-repo] [--instance NAME]
                         [--yes] [--apply]
```

Reverses `module add`:

| Flag | Effect |
|------|--------|
| *(none)* | remove the mount, rewrite `addons_path`, forget the repo |
| `--db DB` | additionally reset the repo's modules to `uninstalled` in that database |
| `--purge-repo` | also delete the clone — only clones the CLI owns (under `repos/` or `repo_root/`) |
| `--yes` | required for file edits on adopted stacks |
| `--apply` | execute the plan |

> ⚠️ Resetting module states is **not** a real uninstall: data tables remain. A
> true uninstall happens inside Odoo; `module remove` cleans the deployment state.

---

### `module test` — prove one module

```bash
oii module test <name> [--instance NAME] [--keep-db] [--with m1,m2]
```

Sequence:

1. drops any previous `oitest_<name>` scratch database;
2. installs the module on that fresh scratch DB inside the web container;
3. runs its tests (`--test-enable --test-tags=/<name>`);
4. captures the full log and classifies failures;
5. prints PASS/FAIL;
6. on PASS, records the module in the whitelist;
7. drops the scratch DB (unless `--keep-db`).

| Option | Meaning |
|--------|---------|
| `--keep-db` | keep the scratch database for debugging |
| `--with m1,m2` | install extra modules in a **separate setup stage first** |

#### `--with`: two-stage testing

Some modules need data that only exists after other modules install — most notably
accounting modules that need a chart of accounts and journals. Odoo 19 applies
chart templates **after** the module install loop, so a single combined `-i` run
would test before the journals exist (false FAILs).

`--with` installs the extras in a separate plain `--stop-after-init` stage first,
then installs and tests the target module:

```bash
oii module test partner_statement --with sale
```

The executed tests are still scoped to `/<name>`. A broken setup stage is reported
as a FAIL with its log.

#### Reading the outcome

```console
$ oii module test web_responsive
✔ PASS web_responsive on scratch db 'oitest_web_responsive' (84s, exit 0)
log: /home/you/odoo-instances/dev/logs/test-web_responsive-20261007-141530.log
✔ web_responsive recorded as tested/installable (whitelist: ~/.config/odoo-installer/tested.toml)
```

Failure kinds classified from the log: `test_failure`, `import_error`,
`not_installable`, `addons_path`, `manifest`, `traceback`, `exit_code`.

Exit code **3** on failure.

Logs:

- created instances → `<stack>/logs/`
- adopted instances → `~/.local/state/odoo-installer/logs/<name>/`

---

### `module approve` — trust already-proven modules

```bash
oii module approve <name...> --db DB [--instance NAME]
```

For modules whose quality is already proven on a live stack (for example, approved
in production):

1. refuses anything not in `installed` state in the given `--db`;
2. records the whitelist entries — no test log required.

```bash
oii module approve attribute_set pim --db odoo --instance prod
```

---

### `module upgrade-repos` — refresh mounted repos

```bash
oii module upgrade-repos [--instance NAME] [--apply]
```

For every mounted repo:

1. `fetch` + checkout `origin/<branch>` (the tip of `19.0`);
2. records the new commit in the manifest;
3. reports which mounted modules changed between old and new commits;
4. recreates the web service when something moved.

The upgrade **inside Odoo** stays explicit — run the printed command yourself:

```bash
oii module upgrade <changed modules> --db odoo
```

---

## `test` — batch testing and central sync

```bash
oii test suite [--instance NAME] [--only REPO] [--modules m1,m2]
               [--output report.md] [--output report.json] [--keep-db]
oii test pull [--apply]
```

### `test suite`

Tests every module on the instance's addons path, **sequentially** (one scratch DB
at a time).

| Option | Meaning |
|--------|---------|
| `--only REPO` | restrict to one source repo — `web` or `OCA/web` both match |
| `--modules m1,m2` | explicit module list instead of everything |
| `--output PATH` | write a report; repeatable; `.md` and `.json` supported |
| `--keep-db` | keep each module's scratch database |

- each module gets a fresh `oitest_<module>` database, dropped afterwards;
- every PASS feeds the whitelist;
- a summary table is printed at the end;
- exit code **3** when anything failed.

```console
$ oii test suite --only web --output report.md --output report.json
[1/3] web_environment_ribbon (OCA/web)
✔ PASS web_environment_ribbon on scratch db 'oitest_web_environment_ribbon' (61s, exit 0)
...
3 modules: 3 passed, 0 failed
✔ report written: report.md
✔ report written: report.json
```

The Markdown report contains the summary table and a `## Failures` section with
logs; the JSON report carries machine-readable results
(`instance`, `generated_at`, `total`, `passed`, `failed`, `results[]`).

### `test pull` — central whitelist sync

```bash
oii test pull             # dry run
oii test pull --apply     # execute
```

Requires `tested_repo_url` to be configured. What it does:

1. refreshes a local cache clone of the whitelist repo
   (`~/.cache/odoo-installer/tested-repo/`);
2. reads its `tested.toml` and **merges** it into the active whitelist —
   union by module name, newer `tested_at` wins.

```console
$ oii test pull --apply
✔ whitelist synced from https://github.com/org/odoo-installer-tested.git: +42 added, 3 updated (97 approved modules)
```

### The whitelist repo format

A tiny git repo with a `tested.toml` at its root:

```toml
[modules.web_responsive]
name = "web_responsive"
repo = "OCA/web"
branch = "19.0"
commit = "abcdef1234567890"
tested_at = "2026-09-12T14:31:05Z"
db = "oitest_web_responsive"
log_path = ""
deps = ["web"]
```

`module test`/`module approve` write entries like this locally; push the file to
the central repo to distribute approvals.

---

## Related reading

- Concepts behind the whitelist and the resolver:
  [3. Core concepts §4–5](03-concepts.md)
- End-to-end recipes: [8. Workflows](08-workflows.md)
- Errors and fixes: [9. Safety & troubleshooting](09-safety-and-troubleshooting.md)

---

[⬅️ Previous: Host & instance commands](04-commands-host-and-instance.md) · [Index](README.md) · [Next: Backups & apply ➡️](06-commands-backups-and-apply.md)
