# 7. Configuration

[🇹🇷 Türkçe](../tr/07-yapilandirma.md) · [🇬🇧 English](README.md)

---

Everything the CLI stores lives in predictable places, and every write is atomic.

**On this page**

1. [Files](#1-files)
2. [Global config keys](#2-global-config-keys)
3. [Managing the config](#3-managing-the-config)
4. [Environment variables](#4-environment-variables)
5. [Instance `.env`](#5-instance-env)
6. [Rendered `odoo.conf`](#6-rendered-odooconf)
7. [Central whitelist repo](#7-central-whitelist-repo)
8. [Precedence](#8-precedence)

---

## 1. Files

| Path | Purpose |
|------|---------|
| `~/.config/odoo-installer/config.toml` | global configuration (`oii config`) |
| `~/.config/odoo-installer/registry.toml` | the instance registry |
| `~/.config/odoo-installer/tested.toml` | the installable-addons whitelist |
| `<stack>/.odoo-installer.json` | per-instance manifest (secret-free CLI state) |
| `<stack>/.env` | per-instance secrets (mode `0600`) |
| `<stack>/config/odoo.conf` | rendered Odoo config (mode `0644`) |
| `<stack>/repos/` | OCA clones for created instances |
| `<stack>/backups/<ts>/` | backups with checksummed `manifest.json` |
| `<stack>/logs/` | test logs for created instances |
| `~/.local/state/odoo-installer/logs/<name>/` | test logs for adopted instances |
| `~/.cache/odoo-installer/tested-repo/` | cached clone of the central whitelist repo |
| `~/odoo-repos/` | OCA clones for adopted stacks (`repo_root`) |

> 💡 All XDG paths are resolved by `platformdirs`, so standard overrides
> (`XDG_CONFIG_HOME`, …) are honored.

---

## 2. Global config keys

Complete list — `oii config show` prints the resolved values:

| Key | Default | Meaning |
|-----|---------|---------|
| `instances_root` | `~/odoo-instances` | where new stack directories are created |
| `repo_root` | `~/odoo-repos` | where OCA clones go for **adopted** stacks |
| `default_pg_tag` | `17` | default PostgreSQL image tag for new instances |
| `port_range_start` | `8069` | port auto-allocation range start (≥ 1024) |
| `port_range_end` | `8099` | port auto-allocation range end |
| `github_token_env` | `GITHUB_TOKEN` | name of the env var holding a GitHub token |
| `tested_repo_url` | *(empty)* | central whitelist git repo (used by `test pull`) |
| `backup_hook` | *(empty)* | shell command run after every successful backup, with `OII_BACKUP_DIR` set |
| `container_runtime` | `auto` | `auto`, `podman` or `docker` |

Validation rules:

- unknown keys are **rejected** — typos fail loudly instead of silently doing nothing;
- `port_range_start <= port_range_end` and both `>= 1024`;
- `container_runtime` must be one of the three literals;
- values set through `oii config set` are validated before being written.

---

## 3. Managing the config

```bash
oii config show            # resolved values, key = value
oii config show --json     # machine-readable
oii config set <key> <value>
oii config edit            # $VISUAL/$EDITOR, validated before saving
oii config path            # file location
```

Notes:

- `edit` opens the file in `$VISUAL`, then `$EDITOR`, else `vi`.
  If the edited text is invalid, **nothing is saved** and the error is shown.
- `set` writes atomically (temp file + rename) — an interrupted write can never
  corrupt the config.
- Lists are comma-separated only where a single string is expected (for example
  `github_token_env` is a plain name, not a list).

Common tweaks:

```bash
oii config set instances_root ~/stacks          # move where stacks live
oii config set container_runtime docker         # force Docker
oii config set port_range_start 9000            # wider/other port range
oii config set port_range_end 9100
oii config set default_pg_tag 16
```

> 💡 Changing `instances_root` does **not** move existing instances — the registry
> remembers each stack's absolute directory.

---

## 4. Environment variables

| Variable | Used for |
|----------|----------|
| `GITHUB_TOKEN` (or the var named by `github_token_env`) | GitHub API calls: branch verification, module probing, `module search` |
| `VISUAL` / `EDITOR` | editor for `oii config edit` |
| `CONTAINER_HOST` | remote Podman socket — passed through to compose unchanged |
| `DOCKER_HOST` | remote Docker socket — passed through unchanged |
| `OII_BACKUP_DIR` | set by the CLI for the `backup_hook` — the fresh backup directory |
| `NO_COLOR` / `TERM` | standard Rich behavior for the output |

About the GitHub token:

- without one, the tool still works — branch checks and search are rate-limited
  and may temporarily fail;
- with one, limits are much higher; a classic token with public read access is
  enough (no scopes needed for public repos);
- the token is read from the environment only — never written to disk by the CLI.

---

## 5. Instance `.env`

Generated once per instance (mode `0600`), reused by every re-run:

| Key | Purpose |
|-----|---------|
| `COMPOSE_PROJECT_NAME` | compose project = instance name |
| `ODOO_IMAGE` | Odoo image tag |
| `PG_TAG` | PostgreSQL image tag |
| `HTTP_PORT` | host HTTP port (`0` in ingress mode) |
| `POSTGRES_PASSWORD` | database role password |
| `ADMIN_PASSWD` | Odoo **master password** (`admin_passwd`) |
| `ODOO_ADMIN_LOGIN` | application admin login |
| `ODOO_ADMIN_PASSWORD` | application admin password (applied on first DB initialization by `apply`) |

Read values with `oii instance secret <name> --key <KEY>` instead of opening the
file — the command prints exactly one value and lists available keys on a typo.

---

## 6. Rendered `odoo.conf`

`instance create` / `apply` render `config/odoo.conf` from the instance's knobs:

| Option | Source |
|--------|--------|
| `admin_passwd` | generated secret (master password) |
| `db_host`, `db_port`, `db_user`, `db_password` | fixed stack wiring + secret |
| `addons_path` | `/mnt/extra-addons` plus one entry per mounted repo (`/mnt/oca/<repo>`) — maintained by `module add`/`remove` |
| `data_dir` | `/var/lib/odoo` |
| `list_db` | `[settings].list_db` (default `True`) |
| `proxy_mode` | implied `True` in ingress mode, otherwise `False` |
| `workers` | emitted only when set (default: threaded mode) |

> ⚠️ The file header says *do not edit while the CLI manages this instance* — the
> CLI rewrites `addons_path` in place and keeps `.oii-bak` backups of its edits.
> Use `--workers`, `--proxy-mode`, `[settings]` etc. to change values through the
> tool.

---

## 7. Central whitelist repo

To share install approvals across machines, host a tiny git repo containing a
`tested.toml` at its root — `module test` and `module approve` produce entries in
exactly that format.

Setup once per machine:

```bash
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

Workflow:

```bash
# on a machine that proved a module:
oii module test my_module

# publish the whitelist (any git workflow — commit/push tested.toml):

# everywhere else:
oii test pull --apply
```

Merge semantics: union by module name, newer `tested_at` wins. Local approvals and
central ones coexist.

The cached clone lives in `~/.cache/odoo-installer/tested-repo/` and is refreshed
(freshly cloned) on every pull.

---

## 8. Precedence

```text
CLI flags  >  instance manifest  >  global config.toml  >  built-in constants
```

Practical consequences:

| Value | Flag | Manifest | Config | Constant |
|-------|------|----------|--------|----------|
| HTTP port | `--http-port` | pinned port | allocation range | `8069` start |
| Odoo image | `--image` | recorded image | — | `odoo:19.0` |
| Postgres tag | `--pg-tag` | recorded tag | `default_pg_tag` | `17` |
| Runtime | — | — | `container_runtime` | `auto` |
| Instance dir | `--dir` | absolute `dir` | `instances_root` | `~/odoo-instances` |

---

## Related reading

- Concepts: [3. Core concepts](03-concepts.md)
- Configuration commands: [4. Commands — host & instance](04-commands-host-and-instance.md)
- Whitelist workflows: [5. Commands — data, modules & tests](05-commands-data-modules-tests.md)

---

[⬅️ Previous: Backups & apply](06-commands-backups-and-apply.md) · [Index](README.md) · [Next: Workflows ➡️](08-workflows.md)
