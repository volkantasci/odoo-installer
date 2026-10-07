# 8. Workflows & recipes

[🇹🇷 Türkçe](../tr/08-is-akislari.md) · [🇬🇧 English](README.md)

---

Copy-paste scenarios, from a blank machine to a grown fleet.

**On this page**

1. [Bootstrap a new machine](#1-bootstrap-a-new-machine)
2. [Fresh dev instance with an OCA module](#2-fresh-dev-instance-with-an-oca-module)
3. [Install a module with cross-repo dependencies](#3-install-a-module-with-cross-repo-dependencies)
4. [Test a module that needs a chart of accounts](#4-test-a-module-that-needs-a-chart-of-accounts)
5. [Work from your fork](#5-work-from-your-fork)
6. [Mount your own checkout (never mutated)](#6-mount-your-own-checkout-never-mutated)
7. [Full installability report](#7-full-installability-report)
8. [Adopt production, inspect safely](#8-adopt-production-inspect-safely)
9. [Share approvals across machines](#9-share-approvals-across-machines)
10. [Upgrade with confidence](#10-upgrade-with-confidence)
11. [Ingress behind a reverse proxy](#11-ingress-behind-a-reverse-proxy)
12. [Declarative instance from a spec](#12-declarative-instance-from-a-spec)
13. [Scheduled backups with an offsite hook](#13-scheduled-backups-with-an-offsite-hook)

---

## 1. Bootstrap a new machine

```bash
# install the CLI (isolated):
pipx install odoo-installer

# make the host able to run stacks:
oii doctor
oii install --apply
oii doctor        # all green? you're ready
```

Optional but recommended:

```bash
oii --install-completion
export GITHUB_TOKEN=ghp_...   # higher GitHub API limits
```

---

## 2. Fresh dev instance with an OCA module

The classic end-to-end flow — every mutation is a dry run until `--apply`:

```bash
# 1. create the stack (renders compose/.env/odoo.conf, starts, waits for health)
oii instance create dev --apply

# 2. create a database
oii db create odoo --instance dev

# 3. find the OCA repo that provides the module
oii module search "responsive"

# 4. clone a sparse repo with only the module you need
oii module add web --sparse --modules web_responsive --apply

# 5. prove it on a scratch database
oii module test web_responsive

# 6. install it into your database
oii module install web_responsive --db odoo --instance dev

# 7. log in and enjoy:
#    http://localhost:8069
#    - app admin: the plain `admin` user (change the password in Settings)
#    - master password (database manager): `oii instance secret dev`
```

> 💡 Steps 3–4 are optional when you already know the repo. Step 5 is required
> unless you pass `--allow-untested` deliberately.
>
> 💡 Databases initialized through `oii apply` additionally get the generated
> `ODOO_ADMIN_PASSWORD` applied on first initialization — see
> [recipe 12](#12-declarative-instance-from-a-spec).

---

## 3. Install a module with cross-repo dependencies

`module add` resolves and provisions cross-repo providers automatically:

```console
$ oii module add account-financial-report --modules account_financial_report --apply
...
resolving dependency OCA/server-ux (provides date_range)
...
resolving dependency OCA/reporting-engine (provides report_xlsx)
...
✔ account-financial-report added
```

If you install directly and a dependency's provider repo is missing, the error
tells you exactly what to do:

```console
$ oii module install account_financial_report --db odoo
Error: missing OCA dependencies need mounting: date_range <- OCA/server-ux (provides date_range) — re-run with --resolve-deps to mount them automatically
```

```bash
# let the installer mount the providers and include the deps:
oii module install account_financial_report --db odoo --resolve-deps
```

---

## 4. Test a module that needs a chart of accounts

Accounting modules often fail tests when installed alone because journals do not
exist yet. Use a **two-stage** test:

```bash
oii module test partner_statement --with sale
```

`--with` installs the extra modules in a separate setup stage **before** the test
run; the tests themselves stay scoped to `partner_statement`.

Debug a failure interactively by keeping the scratch database:

```bash
oii module test partner_statement --with sale --keep-db
oii db list --instance dev          # oitest_partner_statement is still there
```

---

## 5. Work from your fork

```bash
oii module add server-tools --fork myuser --apply
```

- `origin` points at your fork, `upstream` at OCA;
- the branch is verified on the fork before cloning;
- push changes to your fork; `module upgrade-repos` refreshes to its tip.

---

## 6. Mount your own checkout (never mutated)

Perfect for active development: mount a local working tree as-is.

```bash
cd ~/dev/web-deploy
git checkout 19.0

oii module add web --repo ~/dev/web-deploy --apply
```

Rules:

- the checkout must be on `19.0` (if attached to a branch) — the CLI refuses
  otherwise, telling you to switch it yourself;
- the CLI never fetches, checks out or edits it;
- `module remove` unmounts it but `--purge-repo` will **not** delete it
  (only clones the CLI owns are purgeable).

After editing code, recreate the service so the container sees it:

```bash
oii instance restart dev        # or: docker compose up -d web
```

---

## 7. Full installability report

Test everything on an instance's addons path, sequentially, with reports:

```bash
oii test suite --instance dev --output report.md --output report.json
```

- one fresh scratch DB per module;
- PASSes feed the whitelist;
- exit code `3` if anything fails — usable in CI.

```bash
# filter by repo or explicit list:
oii test suite --only web
oii test suite --modules web_responsive,web_environment_ribbon
```

---

## 8. Adopt production, inspect safely

```bash
# register the existing stack (no files are rewritten):
oii instance adopt ~/Projects/my-odoo --apply

# inspect without touching anything:
oii instance show my-odoo
oii db list --instance my-odoo
oii module list --instance my-odoo --db odoo
oii instance logs my-odoo --tail 100

# record already-proven modules into the whitelist:
oii module approve attribute_set pim product_attribute_set --db odoo --instance my-odoo
```

Adopted stacks keep running exactly as before — the CLI never recreates their
containers. See [3. Core concepts §6](03-concepts.md#6-adopted-stacks).

---

## 9. Share approvals across machines

```bash
# one-time setup on every machine:
oii config set tested_repo_url https://github.com/<org>/odoo-installer-tested.git

# on the machine that proved the modules:
oii module test my_module
# (or, for modules already proven on a live stack:)
oii module approve my_module --db odoo

# copy ~/.config/odoo-installer/tested.toml into the central repo and push it.
# then, everywhere else:
oii test pull --apply
```

New approvals now spread without updating the CLI.

---

## 10. Upgrade with confidence

```bash
# 1. refresh repo clones to the tip of their branches (reports changed modules):
oii module upgrade-repos --instance dev --apply

# 2. prove the module on a scratch DB first:
oii module test my_module --keep-db

# 3. upgrade in Odoo — only whitelisted modules get through:
oii module upgrade my_module --db odoo --instance dev
```

The tool deliberately keeps the two phases separate: **refresh the code**, then
**upgrade inside Odoo** with the list it printed.

---

## 11. Ingress behind a reverse proxy

```bash
oii instance create acme \
    --ingress-network violetear-ingress \
    --ingress-alias acme \
    --memory 2g --cpus 1.5 --workers 4 \
    --apply
```

- create the external network first if it does not exist
  (`docker network create violetear-ingress` / `podman network create …`);
- the web service joins it under alias `acme`; no host port is published;
- point your proxy at `acme:8069` inside the network;
- health checks keep working through the container healthcheck.

Declaratively:

```toml
name = "acme"

[ingress]
network = "violetear-ingress"
alias = "acme"

[resources]
memory = "2g"
cpus = 2.0

[settings]
workers = 4
```

```bash
oii apply acme.toml --apply
```

---

## 12. Declarative instance from a spec

Write the desired state once, converge as often as you like:

```toml
# acme.toml
name = "acme"
pg_tag = 17
http_port = 8070
admin_login = "admin"

[[repos]]
url = "OCA/web"
modules = ["web_environment_ribbon"]

[[repos]]
url = "OCA/server-tools"
modules = ["base_technical_features"]

[databases.acme]
install = ["base", "sale", "web_environment_ribbon", "base_technical_features"]
allow_untested = false
```

```bash
# see exactly what would change:
oii apply acme.toml

# converge:
oii apply acme.toml --apply

# converge again — everything reports "already satisfied":
oii apply acme.toml --apply
```

> ⚠️ The tested-only gate still applies: modules must be tested/approved (or the
> database's `allow_untested = true`). Run `module test` or `test pull` first when
> the spec mentions new modules.

---

## 13. Scheduled backups with an offsite hook

```bash
# ship every fresh backup offsite (runs after each create):
oii config set backup_hook 'rclone copy "$OII_BACKUP_DIR" remote:odoo-backups/$(basename "$OII_BACKUP_DIR")'

# manual snapshot:
oii backup create --instance prod

# keep the 14 newest:
oii backup prune --instance prod --keep 14 --apply
```

A cron entry for a nightly snapshot:

```cron
# m h  dom mon dow   command
  30 3  *   *   *     oii backup create --instance prod >> ~/.local/state/odoo-backups.log 2>&1
  30 3  *   *   *     oii backup prune --instance prod --keep 14 --apply >> ~/.local/state/odoo-backups.log 2>&1
```

Notes:

- `backup create` is safe while Odoo serves (MVCC-consistent dump);
- a failing hook fails the command, but the local backup stays on disk;
- verify now and then: `oii backup verify --instance prod`.

---

## Related reading

- Concepts behind the commands: [3. Core concepts](03-concepts.md)
- Full option lists: [4](04-commands-host-and-instance.md) ·
  [5](05-commands-data-modules-tests.md) · [6](06-commands-backups-and-apply.md)

---

[⬅️ Previous: Configuration](07-configuration.md) · [Index](README.md) · [Next: Safety & troubleshooting ➡️](09-safety-and-troubleshooting.md)
