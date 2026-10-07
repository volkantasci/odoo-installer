# 1. Overview

[🇹🇷 Türkçe](../tr/01-genel-bakis.md) · [🇬🇧 English](README.md)

---

## What is odoo-installer?

`odoo-installer` is a command-line tool that **installs, configures and manages Odoo
19.0 container stacks**.

One CLI handles the full lifecycle:

- create a complete stack (Odoo web + PostgreSQL) on Podman or Docker;
- clone and mount **OCA** repositories at the correct `19.0` branch;
- **test** modules on throwaway databases before trusting them;
- install, upgrade and remove modules through Odoo itself;
- back up and restore databases **and** filestores;
- converge an entire instance from a declarative `odoo-stack.toml` file.

It never installs Odoo on the host. Odoo always runs in containers, and every Odoo
command (`-i`, `-u`, tests) runs **inside** the web container.

---

## Which problems does it solve?

Managing Odoo by hand means remembering a long list of small, sharp rules:

| Manual pain | What `oii` does instead |
|-------------|-------------------------|
| `git clone` a repo, then discover it has no `19.0` branch | Verifies the branch via the GitHub API **before** cloning, never guesses |
| Sparse clones that silently lose previously selected modules | Extends the sparse set (union), never replaces it |
| A module that installs but fails at runtime because a dependency repo is missing | Resolves dependencies from `__manifest__.py` and mounts provider repos automatically |
| Installing an untested community module straight into production | Refuses anything that has not passed a real test run (the whitelist) |
| A forgotten `docker compose up -d` after editing mounts | Recreates the web service for you — a plain restart would not mount new volumes |
| Hand-edited compose files that break | Edits are backup-protected and validated with `docker compose config` |
| Databases dropped by accident | Explicit names only; destructive commands need `--apply --yes` |
| "What will this command change?" | Every mutation prints its exact plan first and only runs with `--apply` |

---

## Feature highlights

### 🦭 Podman-first, Docker-compatible

Every instance is a compose stack on the runtime you choose
(`container_runtime = auto|podman|docker`).

`auto` prefers **rootless Podman** and falls back to Docker. One adapter normalizes
both engines, so every command behaves the same.

### 📄 Declarative desired state

```bash
oii apply odoo-stack.toml
```

One TOML file describes the instance end to end: stack settings, OCA repos,
databases and the modules each database must have installed.

`apply` is **idempotent** — re-running a converged spec reports every step as
`already satisfied`. It is designed to be looped by hosting control planes.

### 💾 Backups built in

```bash
oii backup create | list | verify | prune | restore
```

A backup is a consistent `pg_dump` plus the filestore, with SHA-256 checksums.
`restore` is plan-first and gated, and it refuses corrupted backups outright.

### 🌐 Ingress mode

Attach instances to a shared reverse-proxy network under an alias — **no published
host ports**, per-instance resource limits and `odoo.conf` knobs.

### 📋 Plan-first safety

Every mutating command:

1. prints a numbered plan of the exact commands and file writes;
2. exits `0` **without doing anything**;
3. executes only with `--apply` (plus `--yes` when destructive).

When a plan runs, progress streams live as `[i/n]` step lines.

### 🌿 Correct OCA branches

The `19.0` branch is verified through the GitHub API before any clone. A module
name passed by mistake gets a hint naming the repo that provides it.

### ✅ Tested-only installs

`module install` refuses any module that has not:

- passed a real test run on a scratch database (`module test`, `test suite`), or
- been explicitly approved on a proven stack (`module approve`).

Skip the gate deliberately with `--allow-untested` when you must.

### 🔗 Dependency resolver

Reads each module's `__manifest__.py` and classifies every dependency:

- provided by **Odoo core** (verified against the running container);
- **sibling** modules in the same repo (join the sparse clone automatically);
- **other OCA repos** (provider repos are mounted automatically);
- already **available** locally or via another mount.

### 🗂️ Central approvals

The whitelist can live in a small git repo (`tested_repo_url`).

`test pull` merges it into every machine — so a module approved once is installable
everywhere, without updating the CLI.

### 🔁 Idempotent everywhere

Ports pin, secrets persist, satisfied steps report `already satisfied`, and adopted
stacks are never rewritten behind your back.

---

## Design principles

These rules shape every command:

1. **Show, then do.** A plan is not documentation — it *is* the executed code path.
2. **Explicit beats clever.** Database names are never defaulted to.
3. **Never guess a branch.** OCA support is verified, not assumed.
4. **Only proven modules are installed.** The whitelist is the contract.
5. **Adopted stacks are read-mostly.** The CLI never recreates containers it did
   not create.
6. **Safe to re-run.** Every step is idempotent, by design.

---

## Requirements at a glance

| Requirement | Details |
|-------------|---------|
| Python | 3.11 or newer |
| OS | Linux (Arch/pacman and Debian/Ubuntu/apt are supported for `install`) |
| Runtime | Podman (preferred, rootless) **or** Docker, with a compose provider |
| Git | Required for OCA clones — `oii doctor` checks it |
| Network | GitHub reachable for OCA discovery (optional token raises rate limits) |
| Disk | ~7 GB free per stack is a healthy baseline |

`oii doctor` verifies all of this, and `oii install --apply` fixes what it can.

---

## The command families

| Command family | What it gives you |
|----------------|-------------------|
| `doctor` | Instant host diagnosis — runtime, compose, git, disk, ports, GitHub |
| `install` | Host prerequisites via pacman/apt — Odoo itself is **never** installed on the host |
| `config` | Validated, atomic global configuration |
| `instance` | Full stack lifecycle: create, adopt, inspect, start/stop, secrets, remove |
| `db` | Database list/create/drop/reset through the stack's own PostgreSQL container |
| `module` | OCA repos and modules: add, list, search, install, upgrade, remove, test, approve |
| `test` | Batch test suites with reports + central whitelist sync |
| `backup` | Consistent database + filestore snapshots, verification, pruning, restore |
| `apply` | Declarative convergence from `odoo-stack.toml` |
| `version` | Print the installed version |

A one-line tour:

```bash
oii doctor                                   # can this host run Odoo stacks?
oii install --apply                          # make it able
oii instance create dev --apply              # create the stack
oii db create odoo --instance dev            # create the database
oii module add web --sparse \
    --modules web_responsive --apply         # add an OCA repo
oii module test web_responsive               # prove it on a scratch DB
oii module install web_responsive \
    --db odoo --instance dev                 # install it for real
oii backup create --instance dev             # snapshot it
```

---

## Where to go next

| I want to… | Read |
|------------|------|
| install the tool | [2. Installation](02-installation.md) |
| understand how it thinks | [3. Core concepts](03-concepts.md) |
| look up one command | [4](04-commands-host-and-instance.md) · [5](05-commands-data-modules-tests.md) · [6](06-commands-backups-and-apply.md) |
| configure it | [7. Configuration](07-configuration.md) |
| follow a recipe | [8. Workflows](08-workflows.md) |
| fix an error | [9. Safety & troubleshooting](09-safety-and-troubleshooting.md) |

---

[⬅️ Back to the index](README.md) · [Next: Installation ➡️](02-installation.md)
