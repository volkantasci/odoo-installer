# 2. Installation

[🇹🇷 Türkçe](../tr/02-kurulum.md) · [🇬🇧 English](README.md)

---

## Requirements

| Component | Minimum | Checked by |
|-----------|---------|------------|
| **Python** | 3.11+ | `pip`/`uv` at install time |
| **OS** | Linux; package install supports pacman & apt | `oii doctor` |
| **Container runtime** | Podman **or** Docker, running and reachable | `oii doctor` (FAIL if not) |
| **Compose provider** | `docker-compose` / `docker compose` / `podman compose` | `oii doctor` (FAIL if not) |
| **Git** | any recent version | `oii doctor` (FAIL if not) |
| **Disk space** | ~7 GB per stack recommended; hard-fail under 2 GiB free | `oii doctor` |
| **GitHub access** | only for OCA discovery / branch checks | `oii doctor` (WARN if unreachable) |

> 💡 The runtime is chosen by the `container_runtime` config key
> (`auto` prefers rootless Podman, then Docker). You can change it at any time —
> see [Configuration](07-configuration.md).

---

## Install the CLI

### From PyPI (recommended)

```bash
pip install odoo-installer
```

### Isolated, daily-use install

Keeps the tool out of your development virtualenvs:

```bash
pipx install odoo-installer
# or
uv tool install odoo-installer
```

### From a checkout

```bash
git clone https://github.com/volkantasci/odoo-installer.git
cd odoo-installer
pip install .
```

### For development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pre-commit install
```

See [`DEVELOPMENT.md`](../../DEVELOPMENT.md) for the full contributor workflow.

---

## Verify the installation

The CLI answers to **three names** — every example in this guide uses `oii`:

| Invocation | Notes |
|------------|-------|
| `oii` | short alias |
| `odoo-installer` | full name |
| `python -m odoo_installer` | no console script needed (useful in constrained envs) |

```bash
oii version        # e.g. 0.8.1
oii --version      # same, via the global flag
oii --help         # every command group, rendered by Typer
```

Every group also has its own help:

```bash
oii instance --help
oii module --help
oii module install --help
```

---

## Enable shell completion

Typer ships completion for bash, zsh and fish:

```bash
oii --install-completion     # installs for your current shell
oii --show-completion        # print the script instead of installing it
```

Restart your shell afterwards.

---

## Upgrade

```bash
pip install -U odoo-installer
# or
pipx upgrade odoo-installer
# or
uv tool upgrade odoo-installer
```

> 💡 **"Already satisfied" right after a release?**
>
> The package index cache can lag a few minutes behind PyPI. Pin the version for
> one run:
>
> ```bash
> pip install "odoo-installer==X.Y.Z"
> ```

Your configuration, registry and whitelist are **not** touched by upgrades — they
live under `~/.config/odoo-installer/`.

---

## Prepare the host

Installing the CLI does not yet make the machine able to run stacks. Do it in two
commands:

```bash
oii doctor            # 1. diagnose: what is missing?
oii install --apply   # 2. fix the fixable host prerequisites
oii doctor            # 3. confirm everything is green
```

### What `oii install` actually does

| Missing piece | What gets installed/enabled |
|---------------|-----------------------------|
| Container runtime | `podman` (preferred) or `docker` package via pacman/apt |
| Docker service | `systemctl enable --now docker` |
| Compose provider | `docker-compose` (Arch) / `docker-compose-plugin` (Debian/Ubuntu) |
| Git | `git` package |
| Podman socket | `podman.socket` user service — the compose provider connects through it |
| Boot survival | `loginctl enable-linger` + `podman-restart.service` |

Notes:

- It **never installs Odoo** — Odoo lives in the stacks you create.
- The plan is idempotent: a satisfied host reports
  `✔ all host prerequisites already satisfied`.
- Without `--apply` it is a dry run.
- Auto-detection supports pacman and apt. Other distributions: install the packages
  manually and re-run `oii doctor`.

### Rootful Docker vs rootless Podman

| | Podman (rootless) | Docker |
|---|---|---|
| Permissions | no group needed — runs as your user | user must be in the `docker` group |
| Socket | `podman.socket` user service required for compose | `/var/run/docker.sock` via the service |
| Boot | linger + `podman-restart.service` (doctor WARN if missing) | `docker` system service |
| Remote | `CONTAINER_HOST` passes through | `DOCKER_HOST` passes through |

`oii doctor` is runtime-aware: under Podman it checks the socket, linger and
`podman-restart.service`; under Docker it checks the group membership — each with
an exact fix hint.

---

## Uninstall

```bash
pip uninstall odoo-installer     # or: pipx uninstall odoo-installer
```

Uninstalling the CLI does **not** remove anything else. Left behind (delete
manually if you really want a clean slate):

| Path | Contains |
|------|----------|
| `~/odoo-instances/` | your stacks (containers, databases, filestores, backups) |
| `~/.config/odoo-installer/` | config, registry, whitelist |
| `~/.local/state/odoo-installer/` | test logs of adopted stacks |
| `~/.cache/odoo-installer/` | the cached whitelist repo clone |
| `~/odoo-repos/` | OCA clones for adopted stacks |

> ⚠️ Removing a stack directory by hand does not stop its containers. Use
> `oii instance remove <name> --apply --yes` instead.

---

## Next steps

- [3. Core concepts](03-concepts.md) — how the tool thinks.
- [8. Workflows](08-workflows.md) — first complete scenario.

---

[⬅️ Previous: Overview](01-overview.md) · [Index](README.md) · [Next: Core concepts ➡️](03-concepts.md)
