# 3. Core concepts

[🇹🇷 Türkçe](../tr/03-kavramlar.md) · [🇬🇧 English](README.md)

---

This chapter explains the mental model behind every command. Read it once — after
that, the command reference will feel obvious.

**On this page**

1. [Instances](#1-instances)
2. [Plan-first execution](#2-plan-first-execution)
3. [Secrets and ports](#3-secrets-and-ports)
4. [The whitelist](#4-the-whitelist)
5. [OCA repos and the dependency resolver](#5-oca-repos-and-the-dependency-resolver)
6. [Adopted stacks](#6-adopted-stacks)
7. [Ingress mode](#7-ingress-mode)
8. [The container runtime](#8-the-container-runtime)
9. [Where state lives](#9-where-state-lives)
10. [Precedence](#10-precedence)

---

## 1. Instances

An **instance** is one Odoo stack living in its own directory.

Created instances default to `~/odoo-instances/<name>/`:

```text
~/odoo-instances/dev/
├── docker-compose.yml       # rendered from templates
├── .env                     # image, pg tag, port, generated secrets (mode 0600)
├── config/
│   └── odoo.conf            # addons_path etc. — rewritten by `module add` (mode 0644)
├── addons/
│   └── local/               # your own modules → mounted at /mnt/extra-addons
├── repos/
│   └── oca-web/             # OCA clones → mounted at /mnt/oca/web
├── logs/                    # captured test logs (test-<module>-<timestamp>.log)
├── backups/                 # created by `oii backup create`
│   └── <timestamp>/
│       ├── db.dump
│       ├── filestore.tar
│       └── manifest.json
└── .odoo-installer.json     # the instance manifest (CLI state — secret-free)
```

Two services make up the stack:

| Service | Image | Published on the host? |
|---------|-------|------------------------|
| `web` | `odoo:19.0` (configurable) | yes — the allocated HTTP port (unless ingress mode) |
| `db` | `postgres:<tag>` (default `17`) | **never** — all DB access goes through the stack |

Every database operation (`db …`, test scratch DBs, module state checks) is executed
with `psql` **inside** the `db` container. PostgreSQL is never exposed.

---

## 2. Plan-first execution

Mutating commands follow one rule: **show the exact plan, then do nothing until
asked.**

```console
$ oii instance create dev
Instance create plan: dev (http port 8069)
   1. → create directory structure under /home/you/odoo-instances/dev
   2. → render docker-compose.yml
   3. → render .env (contains secrets, mode 0600)
   4. → render config/odoo.conf (readable by the container, mode 0644)
   5. → register instance 'dev' in the registry
   6. → write .odoo-installer.json
   7. → clear containers/volumes from any earlier 'dev' stack (compose down -v; …)
   8. → start the stack (docker compose up -d, project 'dev')
   9. → wait for web container dev-web-1 to become healthy
dry run — re-run with --apply to execute
```

The printed plan **is the executed code path** — it cannot drift from what runs.

### The two switches

| Switch | Meaning |
|--------|---------|
| `--apply` | execute the plan |
| `--yes` | additionally confirm a **destructive** or adopted-stack action |

Rules of thumb:

- Read-only commands (`list`, `show`, `search`, `health`, `logs`, `secret`,
  `doctor`, `backup list/verify`) run directly — no switches.
- Additive commands (`db create`, `backup create`) also run directly; they cannot
  destroy existing data.
- Everything else is a dry run until `--apply`.
- Destructive commands (`db drop/reset`, `instance remove`, `backup restore`) need
  `--apply --yes`.

### Live progress and idempotency

During an applied plan, each step is announced as it happens:

```console
$ oii instance create dev --apply
[1/9] create directory structure under /home/you/odoo-instances/dev
  ✔ directories ready
[2/9] render docker-compose.yml
  ✔ written (623 bytes)
...
[9/9] wait for web container dev-web-1 to become healthy
  ✔ healthy
✔ instance 'dev' ready at http://localhost:8069
```

Re-runs are safe:

- unchanged files are reported as `already satisfied`;
- the port is pinned by the existing manifest;
- secrets are reused from `.env`;
- a running stack is left alone.

---

## 3. Secrets and ports

### Generated secrets

On the first create, the following credentials are generated and **persisted**
(they are never rotated by re-runs):

| `.env` key | Purpose |
|------------|---------|
| `POSTGRES_PASSWORD` | password of the PostgreSQL `odoo` role |
| `ADMIN_PASSWD` | Odoo **master password** (`admin_passwd` in `config/odoo.conf`) |
| `ODOO_ADMIN_LOGIN` / `ODOO_ADMIN_PASSWORD` | application admin credentials applied on a database's first initialization by `oii apply` |

Read them back any time:

```bash
oii instance secret dev                                  # master password
oii instance secret dev --key POSTGRES_PASSWORD
oii instance secret dev --key ODOO_ADMIN_PASSWORD
```

`secret` never guesses: a missing key is a hard error that lists the available keys.

### Ports

- The first free port in `port_range_start`–`port_range_end` (default
  **8069–8099**) is allocated on create.
- A **stopped stack does not hold a socket** — the registry is the record of its
  claim, and auto-allocation skips ports reserved by any registered instance.
- Pin a port with `--http-port`; it must be free on the wire and not reserved by
  another instance.
- Re-running `create` on an instance keeps its pinned port, even while the stack is
  running.
- Ingress-mode instances publish **no** host port (`http_port = 0` internally).

---

## 4. The whitelist

The central safety contract: **a module is installable only after it has proven
itself.**

### How a module becomes trusted

```text
oii module test <name>
        │
        ├─ creates a fresh scratch database   →  oitest_<name>
        ├─ installs the module inside the web container
        ├─ runs its tests                     →  --test-enable --test-tags=/<name>
        ├─ parses the log, prints PASS/FAIL
        └─ on PASS, records an entry in ~/.config/odoo-installer/tested.toml
```

```text
oii module install <name> --db <db>
        │
        ├─ OCA module not in the whitelist?  →  refused
        │      (unless --allow-untested)
        └─ Odoo core modules                 →  always allowed
```

The whitelist file (`tested.toml`) stores, per module: name, repo, branch, commit,
test timestamp, database, log path and dependencies.

### `module approve` — trusting already-proven modules

For modules that are demonstrably healthy on a live stack:

```bash
oii module approve my_module --db odoo
```

It refuses anything that is not in `installed` state in the given database, then
records the whitelist entry — no test log required.

### Portable approvals

Pretty soon you want the same approvals on every machine. Point the CLI at a small
git repo that holds a `tested.toml` at its root:

```bash
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git
oii test pull --apply
```

`test pull` merges the repo's `tested.toml` into the local whitelist — **union by
module name, newer `tested_at` wins**. The CLI itself never needs an update for new
approvals.

### Scratch databases

Test runs use throwaway databases named `oitest_<module>`:

- dropped after the run, unless `--keep-db`;
- never touch your real databases;
- always visible in `db list` while they live.

---

## 5. OCA repos and the dependency resolver

### Repos, not module names

`module add` expects a **repository** name:

```bash
oii module add web                    # OCA/web
oii module add OCA/server-tools       # explicit owner
```

Pass a module name by mistake and the error tells you which repo provides it.

Before any clone, the `19.0` branch is verified through the GitHub API. If it does
not exist, nothing is cloned and the failure names the exact command to try.

### Sparse clones

```bash
oii module add web --sparse --modules web_responsive
```

`--sparse` performs a blob-filtered partial clone:
`git clone --filter=blob:none --sparse --depth 1`.

Only the requested modules' files are downloaded. Re-adding another module
**extends** the sparse set instead of replacing it.

### The dependency report

When you pass `--modules`, the plan verifies and *shows* each module's dependencies,
read from `__manifest__.py` files on GitHub:

```console
3. → verify dependencies of web_responsive
     (core: base, web, mail, web_tour · already available: —)
```

Every dependency is classified:

| Bucket | Meaning | What the CLI does |
|--------|---------|-------------------|
| **core** | provided by Odoo itself | verified against the running web container |
| **same-repo** | lives in the same GitHub repo | joins the sparse clone automatically |
| **other-repo** | lives in another OCA repo | provider repo is mounted automatically (see below) |
| **already available** | provided by local addons or another mount | nothing to do |
| **unknown** | provider cannot be determined | reported honestly; container-offline runs tolerate it |

### Automatic cross-repo provisioning

`module add` resolves cross-repo dependencies by default:

1. the whitelist catalog is asked first;
2. anything unexplained is probed across the OCA org (raw manifests, transitive);
3. each provider repo is sparse-cloned at `19.0`, mounted and recorded **before**
   the main repo;
4. the web service is recreated **once**, at the end.

```console
$ oii module add account-financial-report --modules account_financial_report
Module add plan: OCA/account-financial-report
   ...
Dependency plan: OCA/server-ux (provides date_range)
   ...
Dependency plan: OCA/reporting-engine (provides report_xlsx)
   ...
```

`--no-resolve-deps` disables provisioning — the repo is added as-is and an unmet
dependency will stop the later install with guidance.

Whole-repo adds (`--modules` omitted) cannot know their module set before cloning;
providers are resolved in a late phase right after the clone is placed.

### How mounts go live

Adding or removing a repo edits two files:

- `docker-compose.yml` — the volume line, validated with `docker compose config`
  and restored if the edit breaks the file (a `.oii-bak` backup is left behind);
- `config/odoo.conf` — the `addons_path` entry.

Then the `web` service is **recreated** with `compose up -d` — a plain `restart`
would not mount the new volume.

---

## 6. Adopted stacks

`instance adopt` registers an **existing** compose stack — for example a production
deployment you already run — without rewriting a single file.

Detection uses **container labels only**; the compose file is never parsed. The CLI
identifies the `web` service (Odoo image or a published `8069` port), the `db`
service (postgres image), the project name and the host port.

Adopted stacks are then managed **read-mostly**:

| Operation | Behavior on adopted stacks |
|-----------|----------------------------|
| `start` | `compose start` — existing containers only, never recreated |
| `stop` / `restart` | normal compose actions |
| `show` / `logs` / `health` / `db …` / `module list` | work normally |
| `module add` / `module remove` | file edits require `--yes`; the CLI then tells you to recreate the stack yourself |
| `instance remove` | works — the one explicitly confirmed destructive mutation |

Test logs for adopted stacks are written to
`~/.local/state/odoo-installer/logs/<name>/` (the CLI never writes into an adopted
stack directory).

> ⚠️ Adoption requires the web service to publish container port `8069` on the host
> — a stack the CLI cannot reach over HTTP cannot be adopted.

---

## 7. Ingress mode

For fleets behind a reverse proxy (Caddy, nginx, Traefik…), create instances
**without published host ports**:

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --ingress-alias acme
```

What changes:

- the `web` service joins the **external** network `violetear-ingress` under the
  alias (`acme`);
- no `ports:` entry exists — the proxy routes to `acme:8069` inside the network;
- `proxy_mode` becomes `true` automatically;
- the `db` service never joins the ingress network.

Combine with resource limits and `odoo.conf` knobs:

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --memory 2g --cpus 1.5 --workers 4
```

Health checks adapt: published stacks are probed over HTTP (`/web/health`), while
ingress instances are probed through the container healthcheck.

The same is expressible declaratively — see
[6. Backups & apply](06-commands-backups-and-apply.md).

---

## 8. The container runtime

| Config value | Behavior |
|--------------|----------|
| `auto` (default) | prefer `podman` if installed **and** answering, else `docker` |
| `podman` | require the podman binary on PATH |
| `docker` | require the docker binary on PATH |

- Both engines speak the **compose specification**; every command works on either.
- Under rootless Podman the compose provider talks through `podman.socket`
  (a user service) — `oii doctor` fails the compose check with the exact fix when
  the socket is not listening.
- `CONTAINER_HOST` / `DOCKER_HOST` environment variables pass through unchanged for
  remote sockets.

---

## 9. Where state lives

| Path | Contents |
|------|----------|
| `~/.config/odoo-installer/config.toml` | global configuration |
| `~/.config/odoo-installer/registry.toml` | the instance registry |
| `~/.config/odoo-installer/tested.toml` | the installable-addons whitelist |
| `<stack>/.odoo-installer.json` | per-instance manifest (secret-free) |
| `<stack>/.env` | per-instance secrets (mode 0600) |
| `<stack>/repos/<repo>/` | OCA clones — **git state is the truth** |
| `<stack>/backups/<ts>/` | backups with checksummed `manifest.json` |
| `<stack>/logs/` | test logs (created instances) |
| `~/.local/state/odoo-installer/logs/<name>/` | test logs (adopted instances) |
| `~/.cache/odoo-installer/tested-repo/` | cached clone of the central whitelist repo |

The manifest records the instance's services, repos, ports and rendering knobs; it
is deliberately **secret-free**. Secrets only live in `.env` and `config/odoo.conf`.

---

## 10. Precedence

When values collide, this order wins:

```text
CLI flags  >  instance manifest  >  global config.toml  >  built-in constants
```

That is why:

- `--http-port` beats the manifest's pinned port (but the manifest's own port is
  accepted even while busy);
- explicit create options (`--image`, `--workers`, `--memory`…) override what the
  instance currently runs — omitting them never changes recorded values;
- `config set` values fill in whatever the flags and manifests do not specify.

---

[⬅️ Previous: Installation](02-installation.md) · [Index](README.md) · [Next: Host & instance commands ➡️](04-commands-host-and-instance.md)
