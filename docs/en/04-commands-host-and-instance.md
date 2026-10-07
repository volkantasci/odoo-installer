# 4. Commands — host & instance

[🇹🇷 Türkçe](../tr/04-komutlar-host-ve-instance.md) · [🇬🇧 English](README.md)

---

This page covers:

| Command | Purpose |
|---------|---------|
| [`version`](#version) | print the installed version |
| [`doctor`](#doctor--host-diagnostics) | host diagnostics |
| [`install`](#install--host-prerequisites) | host prerequisites (plan-first) |
| [`config`](#config--global-configuration) | global configuration |
| [`instance`](#instance--stack-lifecycle) | create, inspect and manage stacks |

Every command also accepts `--help`.

---

## `version`

```bash
oii version
```

Prints the bare version — handy in scripts:

```console
$ oii version
0.8.1
```

The global flag `oii --version` / `oii -V` prints the same information with the
tool's name.

---

## `doctor` — host diagnostics

```bash
oii doctor [--json]
```

Runs seven checks (nine under Podman) and prints a table:

| Check | Notes |
|-------|-------|
| container runtime | engine version and usability for the current user |
| compose | provider version; under Podman also probes the rootless socket |
| runtime permissions | docker group membership (Docker) or rootless usability (Podman) |
| git | presence on PATH |
| disk space | free GiB at the instances root — FAIL under 2 GiB, WARN under 5 GiB |
| ports | occupancy of the configured range — WARN when some are busy |
| github api | reachability — WARN only (discovery degrades gracefully) |
| linger (Podman only) | boot survival — WARN when disabled |
| podman boot restart (Podman only) | `podman-restart.service` — WARN when disabled |

Each row carries a `fix_hint` naming the exact command to run.

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | no FAIL rows |
| 4 | at least one critical check failed |

Examples:

```bash
oii doctor                # human-readable table
oii doctor --json         # machine-readable, for CI/monitoring
oii doctor || echo "needs attention"
```

```console
$ oii doctor
odoo-installer doctor
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Check              ┃ Status ┃ Detail                     ┃ Fix hint    ┃
...
7 checks: 7 ok, 0 warn, 0 fail
```

---

## `install` — host prerequisites

```bash
oii install [--apply]
```

Installs the missing host pieces via **pacman** (Arch) or **apt**
(Debian/Ubuntu):

- the container runtime (per `container_runtime`);
- the compose provider;
- git;
- under Podman: `podman.socket`, linger, `podman-restart.service`.

It **never installs Odoo itself** — Odoo runs in the stacks.

```bash
oii install               # dry run: show the steps
oii install --apply       # execute
```

A satisfied host is a no-op:

```console
$ oii install
✔ all host prerequisites already satisfied
```

---

## `config` — global configuration

```bash
oii config show [--json]
oii config set <key> <value>
oii config edit
oii config path
```

| Subcommand | Behavior |
|------------|----------|
| `show` | prints the **resolved** configuration (defaults included) |
| `set` | validates one value and writes atomically; unknown keys and bad values are rejected |
| `edit` | opens the file in `$VISUAL`/`$EDITOR` (else `vi`); result is validated **before** saving |
| `path` | prints the config file path |

Examples:

```bash
oii config show
oii config show --json
oii config set instances_root ~/stacks
oii config set container_runtime podman
oii config set tested_repo_url https://github.com/org/odoo-installer-tested.git
oii config path
```

```console
$ oii config set default_pg_tag 16
✔ default_pg_tag = 16
```

All keys and their defaults are documented in
[7. Configuration](07-configuration.md).

---

## `instance` — stack lifecycle

```bash
oii instance create | adopt | list | show | health | logs | secret
                 | start | stop | restart | remove
```

At any time, `oii instance --help` lists them all.

---

### `instance create`

```bash
oii instance create <name> [options] [--apply]
```

Creates a complete stack: renders `docker-compose.yml`, `.env`,
`config/odoo.conf`, starts the stack, waits for `/web/health`, and registers the
instance.

| Option | Meaning |
|--------|---------|
| `--dir PATH` | stack directory (default: `<instances_root>/<name>`) |
| `--http-port N` | host HTTP port (default: first free in the configured range) |
| `--image TAG` | Odoo image (default `odoo:19.0`) |
| `--pg-tag N` | PostgreSQL image tag (default from config, `17`) |
| `--ingress-network NAME` | attach web to this external network, publish **no** host port |
| `--ingress-alias SLUG` | network alias (default: the instance name) |
| `--memory 2g` | compose `mem_limit` on the web service |
| `--cpus 1.5` | compose `cpus` on the web service |
| `--proxy-mode / --no-proxy-mode` | `odoo.conf` `proxy_mode` (default on with ingress) |
| `--workers N` | `odoo.conf` `workers` (default: threaded) |
| `--apply` | execute the plan |

Instance names must match `[a-z0-9][a-z0-9-]{0,31}` — lowercase letters, digits and
dashes.

What the plan does, in order:

1. create the directory structure (`config/`, `addons/local/`, `logs/`);
2. render `docker-compose.yml`;
3. render `.env` with generated secrets (mode `0600`);
4. render `config/odoo.conf` (mode `0644`);
5. register the instance;
6. write the manifest;
7. **first create only:** sweep any leftover containers/volumes of a same-name
   stack (`compose down -v`) — PostgreSQL never re-initializes an old data dir, so
   stale volumes would poison the new stack;
8. `compose up -d`;
9. wait for the web container to become healthy.

Re-runs are idempotent: unchanged files report `already satisfied`, secrets and
ports persist, and the sweep never happens when a manifest exists
(that would destroy data).

```console
$ oii instance create dev --apply
...
✔ instance 'dev' ready at http://localhost:8069
```

With ingress, the final line reports the network and alias instead.
A `create` on a directory that holds an **adopted** instance is refused.

---

### `instance list` / `show`

```bash
oii instance list [--json]
oii instance show <name> [--json]
```

`list` prints the registry (name, HTTP port, directory, adopted flag).

`show` prints the manifest plus live container states:

```console
$ oii instance show dev
dev — Odoo 19.0 (odoo:19.0), postgres 17
  directory: /home/you/odoo-instances/dev
  http port: 8069
  adopted:   no
  web: running (odoo:19.0)
  db: running (postgres:17)
```

---

### `instance health` / `logs`

```bash
oii instance health <name> [--wait N] [--json]
oii instance logs <name> [--tail N]
```

`health`:

- published stacks → HTTP `GET /web/health`;
- ingress stacks → the container healthcheck;
- exits `1` when unhealthy; `--wait N` polls for up to N seconds.

`logs` prints the combined compose logs (default `--tail 80`).

```bash
oii instance health dev --wait 60
oii instance logs dev --tail 200
```

---

### `instance secret`

```bash
oii instance secret <name> [--key KEY]
```

Prints exactly one value from the instance's `.env`, on its own line
(default `--key ADMIN_PASSWD` — the Odoo master password).

```bash
oii instance secret dev
oii instance secret dev --key POSTGRES_PASSWORD
oii instance secret dev --key ODOO_ADMIN_PASSWORD
```

Unknown keys are a hard error listing the available keys — the command never
guesses and never falls back to another file.

---

### `instance start` / `stop` / `restart`

```bash
oii instance start <name>
oii instance stop <name>
oii instance restart <name>
```

Direct, reversible lifecycle actions (no plan needed).

| Action | Created instances | Adopted stacks |
|--------|-------------------|----------------|
| `start` | `compose up -d` | `compose start` — existing containers only, never recreated |
| `stop` | `compose stop` | same |
| `restart` | `compose restart` | same |

---

### `instance remove`

```bash
oii instance remove <name> [--remove-data] [--yes] [--apply]
```

Dry-run by default; executes only with `--apply --yes`.

| Flag | Effect |
|------|--------|
| *(none)* | stop and remove containers, delete the stack directory, unregister |
| `--remove-data` | additionally destroy the stack's **named volumes** (`compose down -v`) — the database and filestore |
| `--yes` | required confirmation |
| `--apply` | execute the plan |

Works for **adopted stacks too** — removal is the one confirmed mutation allowed
there.

> 🔥 `--remove-data` is irreversible. Back up first
> (`oii backup create`) if the data matters.

```console
$ oii instance remove dev --apply --yes
[1/3] stop and remove the instance's containers (volumes kept)
  ✔ removed
[2/3] delete the instance directory /home/you/odoo-instances/dev
  ✔ deleted
[3/3] remove instance 'dev' from the registry
  ✔ removed
✔ instance 'dev' removed
```

`remove` refuses directories that lack the CLI's manifest — it will not delete
something it did not create.

---

### `instance adopt`

```bash
oii instance adopt <dir> [--name NAME] [--db-user odoo] [--apply]
```

Registers an existing compose stack without rewriting its files. The CLI prints
what it detected (project, services, images, port) before planning.

```console
$ oii instance adopt ~/Projects/my-odoo
detected: project my-odoo, web service web (odoo:19.0) on port 8069, db service db (postgres:17)
Instance adopt plan: my-odoo
   1. → write .odoo-installer.json into /home/you/Projects/my-odoo (adopted, read-mostly)
   2. → register instance 'my-odoo' in the registry (adopted)
dry run — re-run with --apply to execute
```

| Requirement | Detail |
|-------------|--------|
| Detection | purely from **container labels** — the compose file is not parsed |
| Web service | Odoo image, or a published host port mapping container `8069` |
| DB service | a postgres image |
| Unique name | `--name` if the compose project name is taken/invalid |
| `--db-user` | the postgres role inside the db container (default `odoo`) |

Behavioral rules for adopted stacks are described in
[3. Core concepts §6](03-concepts.md#6-adopted-stacks).

---

## Related reading

- All configuration keys: [7. Configuration](07-configuration.md)
- Domains: [5. Data, modules & tests](05-commands-data-modules-tests.md)
  · [6. Backups & apply](06-commands-backups-and-apply.md)

---

[⬅️ Previous: Core concepts](03-concepts.md) · [Index](README.md) · [Next: Data, modules & tests ➡️](05-commands-data-modules-tests.md)
