# 6. Commands — backups & apply

[🇹🇷 Türkçe](../tr/06-komutlar-yedekleme-ve-apply.md) · [🇬🇧 English](README.md)

---

This page covers:

| Command | Purpose |
|---------|---------|
| [`backup`](#backup--database--filestore-snapshots) | consistent snapshots, verification, pruning, restore |
| [`apply`](#apply--declarative-desired-state) | converge an instance from `odoo-stack.toml` |

---

## `backup` — database + filestore snapshots

```bash
oii backup create  [--instance NAME] [--db DB]
oii backup list    [--instance NAME] [--json]
oii backup verify  [--instance NAME] [--backup TS]
oii backup prune   [--instance NAME] [--keep N] [--apply]
oii backup restore <TS> [--instance NAME] [--apply] [--yes]
```

### What is in a backup

Each backup lives in `<stack>/backups/<timestamp>/`:

| File | Contents |
|------|----------|
| `db.dump` | `pg_dump -Fc` (custom-format dump) |
| `filestore.tar` | the web container's `/var/lib/odoo` (attachments, etc.) |
| `manifest.json` | metadata + **SHA-256 checksums** for both files |

Timestamps carry sub-second precision
(`YYYYMMDDTHHMMSSffffff`), so scheduled and manual backups never collide.

Everything streams between container and host through the runtime's own stdio
(`compose exec -T`) — filestore bytes owned by the container's uid never need
host-side permission fixes on the files.

---

### `backup create`

```bash
oii backup create [--instance NAME] [--db DB]
```

- Runs **directly** — it is additive and safe.
- `pg_dump` is MVCC-consistent: Odoo can keep serving during the backup.
- Database default: the instance's **only** Odoo database. With none, or several,
  you must pass `--db` (or create a database first).

```console
$ oii backup create --instance dev
✔ backup 20261007T141530123456 of 'odoo': db 25165824 bytes + filestore 7340032 bytes (32505856 total) in /home/you/odoo-instances/dev/backups/20261007T141530123456
```

If `backup_hook` is configured, it runs after every successful create with
`OII_BACKUP_DIR` pointing at the fresh backup directory — ideal for `rclone`,
`rsync` or a warehouse script:

```bash
oii config set backup_hook 'rclone copy "$OII_BACKUP_DIR" remote:odoo-backups/$(basename "$OII_BACKUP_DIR")'
```

A failing hook fails the command (the backup itself stays on disk).

---

### `backup list` / `backup verify`

```bash
oii backup list [--instance NAME] [--json]
oii backup verify [--instance NAME] [--backup TS]
```

`list` prints newest-last, one line per backup.

`verify` recomputes the SHA-256 checksums against `manifest.json`:

- no `--backup` → verifies **all** backups;
- exits `1` on any mismatch (missing file or corrupted bytes).

```console
$ oii backup verify --instance dev
✔ 20261007T141530123456: checksums match
```

---

### `backup prune`

```bash
oii backup prune [--instance NAME] [--keep N] [--apply]
```

Deletes all but the newest `--keep` backups (default `3`). Plan-first:

```console
$ oii backup prune --instance dev --keep 2
Backup prune plan: dev (keep 2)
   1. → delete backup 20260901T030000000000 (odoo, 31000000 bytes)
dry run — re-run with --apply to execute
```

`✔ nothing to prune` when nothing is old enough.

---

### `backup restore`

```bash
oii backup restore <TS> [--instance NAME] [--apply] [--yes]
```

Destructive and plan-first; executed only with `--apply --yes`.

Before planning, the backup is **verified** — a corrupted or incomplete backup is
refused outright.

The plan, in order:

1. stop the web service (Odoo must not write during restore);
2. drop and recreate the database;
3. `pg_restore` the dump into it;
4. replace the filestore via a throwaway one-shot container;
5. start the web service;
6. wait for the container to become healthy.

```console
$ oii backup restore 20261007T141530123456 --instance dev
Backup restore plan: dev <- 20261007T141530123456
   1. → stop the web service (Odoo must not write during restore)
   2. → drop and recreate database 'odoo'
   3. → restore database from .../db.dump
   4. → replace the filestore from .../filestore.tar
   5. → start the web service
   6. → wait for the web container to become healthy
This replaces database 'odoo' and the filestore with the state from 20261007T141530123456.
add --yes to confirm the restore
```

> 🔥 **Restore replaces data wholesale.** The pre-restore state is not kept
> automatically — if it matters, `oii backup create` first.

---

## `apply` — declarative desired state

```bash
oii apply <odoo-stack.toml> [--apply] [--json]
```

One TOML file describes **one instance end to end**:

```toml
name = "acme"                    # instance name (also the compose project)
# dir = "~/stacks/acme"          # optional: stack directory
image = "odoo:19.0"              # optional (default)
pg_tag = 17                      # optional (config default)
http_port = 8069                 # OR an [ingress] block — never both
admin_login = "admin"            # Odoo admin login (password generated into .env)

[ingress]                        # reverse-proxy mode: no published host port
network = "violetear-ingress"    # external compose network
alias = "acme"                   # network alias (default: the name)

[resources]
memory = "2g"                    # compose mem_limit
cpus = 2.0                       # compose cpus

[settings]                       # odoo.conf knobs
proxy_mode = true                # implied by [ingress]
list_db = false
workers = 4

[[repos]]                        # OCA repos (branch is always 19.0)
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]   # sparse clone list (omit: whole repo)

[[repos]]
url = "OCA/server-tools"         # owner/repo shorthand works too

[databases.acme]                 # each database gets a table
install = ["base", "sale", "web_environment_ribbon"]
allow_untested = false           # escape hatch for the tested-only gate
```

### What `apply` converges

`apply` assembles the **same idempotent plans** the interactive commands use:

| Area | Behavior |
|------|----------|
| Stack | create if missing — compose, `.env`, `odoo.conf`, registry, manifest |
| Repos | diffed against the manifest: new URLs are added (sparse when `modules` given); dropped repos get unmounted and their clones purged |
| Databases | each `[databases.<name>]` table ensures the database exists |
| Modules | installed with the same gates as `module install` — visibility + tested-only whitelist (`allow_untested` per database) |

### Semantics worth knowing

- **Idempotent.** Re-running on a converged spec reports every step as
  `already satisfied`. Safe to loop — this is the primitive a hosting control
  plane runs on.
- **`http_port` is a request.** It must be free on the wire and not reserved by
  another registered instance; re-runs on the instance's own port are fine.
- **Fresh stacks converge in two phases.** Repo/database/module plans are built
  from the instance manifest, which only exists after the stack does. The dry run
  therefore shows the rest as one honest convergence step; at apply time it is
  planned in full detail and executed with live `[i/n]` progress.
- **First initialization applies admin credentials.** When a database is first
  initialized, the generated `ODOO_ADMIN_PASSWORD` is applied through Odoo's ORM
  (a raw SQL write would bypass password hashing). Later applies never touch the
  password again.
- **`[ingress]` and `http_port` are mutually exclusive** — ingress publishes no
  host port.
- Repos accept `https://github.com/owner/repo[.git]`, `git@github.com:owner/repo`
  or `owner/repo`; a bare `repo` defaults to the `OCA` owner. Branch is always
  `19.0`.

### Dry run and plan inspection

```console
$ oii apply odoo-stack.toml
Apply plan: acme (existing instance)
   1. → render docker-compose.yml
   2. → render .env (contains secrets, mode 0600)
   ...
   7. → ensure database 'acme' exists
   8. → install modules base, sale, web_environment_ribbon into db 'acme' (visibility and whitelist verified at run time)
dry run — re-run with --apply to execute
```

Machine-readable plan for CI/control planes:

```bash
oii apply odoo-stack.toml --json
```

```json
{
  "instance": "acme",
  "stack_dir": "/home/you/odoo-instances/acme",
  "created": false,
  "steps": [
    {
      "index": 1,
      "description": "render docker-compose.yml",
      "already_satisfied": true
    }
  ]
}
```

Combine with execution:

```bash
oii apply odoo-stack.toml --json --apply     # prints the plan, then converges
```

### A control-plane loop

```bash
#!/usr/bin/env bash
set -euo pipefail

# every spec is a filed instance; converge them all, twice is harmless
for spec in /etc/odoo-fleet/*.toml; do
    oii apply "$spec" --json --apply
done
```

---

## Related reading

- End-to-end recipes using both commands: [8. Workflows](08-workflows.md)
- Configuration keys (`backup_hook`, `tested_repo_url`, …):
  [7. Configuration](07-configuration.md)

---

[⬅️ Previous: Data, modules & tests](05-commands-data-modules-tests.md) · [Index](README.md) · [Next: Configuration ➡️](07-configuration.md)
