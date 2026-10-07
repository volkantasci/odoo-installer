# 9. Safety & troubleshooting

[🇹🇷 Türkçe](../tr/09-guvenlik-ve-sorun-giderme.md) · [🇬🇧 English](README.md)

---

**On this page**

1. [Safety rules at a glance](#1-safety-rules-at-a-glance)
2. [Exit codes](#2-exit-codes)
3. [Troubleshooting](#3-troubleshooting)
4. [FAQ](#4-faq)
5. [Getting help](#5-getting-help)

---

## 1. Safety rules at a glance

| Rule | How it manifests |
|------|------------------|
| Plan-first | every mutation prints a numbered plan and does nothing until `--apply` |
| Destructive actions double-gated | `db drop/reset`, `instance remove --remove-data`, `backup restore` require `--apply --yes` |
| Idempotent re-runs | satisfied steps report `already satisfied`; secrets/ports persist |
| Explicit database names | the CLI never picks a database for you |
| Explicit instance names | ambiguous registries force `--instance`, never a random pick |
| Adopted stacks are read-mostly | no file rewrites without `--yes`; the CLI never recreates their containers |
| File edits are backup-protected | `.oii-bak` copies; compose edits validated with `docker compose config` and restored on failure |
| Scratch databases are disposable | `oitest_*` DBs are dropped after tests unless `--keep-db` |
| Corrupted backups are refused | `backup restore` verifies checksums before planning |
| Token handling | GitHub tokens are read from the environment and never written to disk |

Protected database names: `postgres`, `template0`, `template1`.

The `remove` command refuses directories that do not carry the CLI's manifest — it
never deletes something it did not create (adopted stacks are the deliberate
exception, still behind `--apply --yes`).

---

## 2. Exit codes

| Code | Meaning | Typical commands |
|------|---------|------------------|
| `0` | success (including dry runs) | everything |
| `1` | runtime error | any command failing on an OdooInstallerError (missing instance, unhealthy stack, refused action) |
| `2` | usage error | Typer — unknown option/command |
| `3` | test failures | `module test`, `test suite` |
| `4` | critical host check failed | `doctor` |

Scripting example:

```bash
oii doctor || exit 4
oii test suite --only web --output report.md
case $? in
    0) echo "all good" ;;
    3) echo "tests failed — see report.md" ;;
    *) echo "unexpected error" ;;
esac
```

Most read commands also support `--json` for stable machine output:
`doctor`, `instance list/show/health`, `db list`, `module list`, `backup list`,
`test suite --output report.json`, `config show`, `apply --json`.

---

## 3. Troubleshooting

### `doctor` exits `4`

Read the FAIL row — it names the check. Common causes and fixes:

| FAIL | Fix |
|------|-----|
| container runtime | install/start it: `oii install --apply` |
| compose | install the provider (`docker-compose` / `docker-compose-plugin`) |
| compose (podman) | `systemctl --user enable --now podman.socket` |
| runtime permissions | `sudo usermod -aG docker $USER`, then re-login |
| git | install `git` |
| disk space | free space; a stack needs roughly 7 GB |

WARN rows do not block, but explain degraded behavior (linger, ports busy, GitHub
unreachable).

### "branch '19.0' does not exist on OCA/&lt;name&gt;"

The branch check failed before any clone.

- You may have passed a **module** name to `module add` — the error names the
  providing repo and the exact command when the whitelist knows it.
- Otherwise check spelling, or find the repo with `oii module search <name>`.

### "not tested yet: …"

`module install`/`upgrade` refused an untested module.

```bash
oii module test <name>          # prove it → whitelist
oii module install <name> --db odoo

# or, deliberately:
oii module install <name> --db odoo --allow-untested
```

If your approvals live in the central repo: `oii test pull --apply` first.

### "missing OCA dependencies need mounting: …"

The resolver found provider repos that are not mounted:

```bash
oii module install <name> --db odoo --resolve-deps
```

Providers must exist and be resolvable; if the dependency lives in a repo the
catalog cannot explain, `module search` will find it.

### "modules not visible to this instance"

The module is not on the addons path:

```bash
oii module add <repo> --apply          # the OCA repo that provides it
oii module add <repo> --repo ~/my/checkout --apply   # or your own checkout
```

If the error adds *"cannot verify Odoo core either — is the stack running?"*, the
container is down, so neither core nor OCA visibility can be verified: start the
stack (`oii instance start <name>`).

### GitHub rate limiting / empty search results

Set a token:

```bash
export GITHUB_TOKEN=ghp_...
# or point the CLI at another variable:
oii config set github_token_env MY_GH_TOKEN
```

### Port already taken

- a **stopped** stack holds no socket — two instances may show the same port;
  start them one at a time, or pin distinct `--http-port` values;
- a port used by an unrelated process is reported explicitly;
- widen the range if it is exhausted:

```bash
oii config set port_range_start 9000
oii config set port_range_end 9100
```

### A fresh create left containers/volumes behind

Fresh creates sweep same-name leftovers automatically (`compose down -v`) because
PostgreSQL never re-initializes an existing data dir. Re-runs on an existing
manifest never sweep — that would destroy data.

If a create died halfway and the manifest exists, remove and recreate:

```bash
oii instance remove <name> --apply --yes --remove-data   # destroys its data
oii instance create <name> --apply
```

### "recreate it with your own tooling" (adopted stacks)

After `module add --yes` on an adopted stack, the CLI has edited the stack's files
but deliberately did not touch the running containers:

```bash
cd <stack-dir>
docker compose up -d web     # or: podman compose up -d web
```

### A module installed but Odoo reports it uninstalled

`module install` verifies `ir_module_module` states afterwards and exits `1` with
the list. Inspect the output tail and the module's dependencies:

```bash
oii module list --instance dev --db odoo
oii instance logs dev --tail 200
```

### The database manager asks for the master password

Nothing pre-fills that field by design. Read the generated master password:

```bash
oii instance secret dev
```

To set your own: edit `admin_passwd` in `config/odoo.conf` **and** `.env`
(`ADMIN_PASSWD`), then `oii instance restart dev`.

### Where are the test logs?

| Instance type | Location |
|---------------|----------|
| created | `<stack>/logs/test-<module>-<timestamp>.log` |
| adopted | `~/.local/state/odoo-installer/logs/<name>/` |

`module test` also prints the log path when a log was written.

### "cannot identify the web/db services" / adopt fails

Adoption works from container labels only. Requirements:

- the stack must have run at least once (`compose ps` sees its containers);
- one service must have a **postgres** image (the db);
- one service must have an **odoo** image or publish host port `8069` (the web);
- the web service must publish container port `8069` on the host.

For ingress-mode stacks with no published port, adoption is not possible — the CLI
cannot reach them over HTTP.

### Backup hook failed

The hook command runs after the backup is written, with `OII_BACKUP_DIR` set. A
non-zero exit fails the command and prints stderr — the backup stays on disk.
Test hooks manually:

```bash
OII_BACKUP_DIR=/path/to/backup bash -c "$(oii config show | grep backup_hook ...)"
```

### Restore refuses my backup

`backup restore` verifies SHA-256 checksums first. Run
`oii backup verify --instance <name> --backup <TS>` to see which file is
missing/corrupted. Restore targets must be complete backups; an incomplete
directory is never used.

### `apply` on a fresh stack shows one big step

That is expected: repo/database/module plans are built from the instance manifest,
which exists only after the stack is created. The dry run shows an honest single
convergence step; execution plans it in full detail with live `[i/n]` output.

---

## 4. FAQ

**Docker or Podman — what should I pick?**
Either works. `auto` prefers rootless Podman when available. Pick explicitly with
`oii config set container_runtime podman|docker`.

**Does the CLI install Odoo on the host?**
Never. `oii install` prepares the host runtime only; Odoo always runs in the stack.

**Can I manage several instances?**
Yes — they coexist, each in its own directory with its own port and secrets. With
multiple registered, pass `--instance`.

**Will re-running commands break my data?**
No. Re-runs are idempotent. Data is destroyed only by explicit destructive
commands (`db drop/reset`, `instance remove --remove-data`, `backup restore`)
behind `--apply --yes`.

**Can I use Odoo versions other than 19.0?**
The branch logic is fixed to `19.0` for OCA validation. `--image` can point at
another tag, but OCA branch checks stay at `19.0`.

**Where is my filestore?**
In a named compose volume inside the stack, backed up by `oii backup create` as
`filestore.tar`. The database volume (`pgdata`) is managed by the db container.

**Do I need a GitHub token?**
Only for heavier discovery/probing. Without one everything still works, with lower
rate limits.

**Can I run this in CI?**
Yes — `doctor --json`, `apply --json`, reports and exit codes are designed for
scripting. Tests themselves need a running stack with the container runtime
available.

**How do I update OCA code?**
`oii module upgrade-repos --apply` refreshes clones; then run the printed
`module upgrade <changed> --db <db>` inside Odoo.

**How do I uninstall the CLI?**
`pip uninstall odoo-installer` (or `pipx uninstall odoo-installer`). Your stacks,
config and whitelist stay; see [2. Installation §Uninstall](02-installation.md).

---

## 5. Getting help

- `oii <command> --help` is always the most current reference.
- [`USAGE.md`](../../USAGE.md) — single-page guide (English).
- [`USAGE.tr.md`](../../USAGE.tr.md) — tek sayfalık kılavuz (Türkçe).
- [`DEVELOPMENT.md`](../../DEVELOPMENT.md) — architecture and decisions.
- Issues and feature requests:
  <https://github.com/volkantasci/odoo-installer/issues>

When reporting an issue, include:

```bash
oii version
oii doctor --json
oii config show --json
```

…plus the exact command you ran and its full output.

---

[⬅️ Previous: Workflows](08-workflows.md) · [Index](README.md) · [🇹🇷 Türkçe](../tr/09-guvenlik-ve-sorun-giderme.md)
