# odoo-installer — Guide

[🇹🇷 Türkçe](../tr/README.md) · **🇬🇧 English**

> **Written for `odoo-installer` 0.8.x** (current release: 0.8.1).
> The source of truth for architecture and decisions is
> [`DEVELOPMENT.md`](../../DEVELOPMENT.md).

`odoo-installer` (`oii` for short) is a single command-line tool for the whole life
of an Odoo 19.0 deployment:

> create container stacks, add OCA repositories at the correct branch, prove modules
> with real test runs, install them safely, back up and restore data, and converge
> everything from a declarative spec — with every change shown **before** it happens.

---

## How to read this guide

The chapters build on each other, but every page stands on its own.

If you are new, read **1 → 3 → 4** first and come back for the rest when needed.

| # | Chapter | What you will learn |
|---|---------|---------------------|
| 1 | [Overview](01-overview.md) | What the tool does, its features and design principles |
| 2 | [Installation](02-installation.md) | Installing, upgrading and enabling completions |
| 3 | [Core concepts](03-concepts.md) | Instances, plans, the whitelist, dependency resolution, ingress |
| 4 | [Commands — host & instance](04-commands-host-and-instance.md) | `doctor`, `install`, `config`, `instance` |
| 5 | [Commands — data, modules & tests](05-commands-data-modules-tests.md) | `db`, `module`, `test` |
| 6 | [Commands — backups & apply](06-commands-backups-and-apply.md) | `backup`, `apply` and the desired-state spec |
| 7 | [Configuration](07-configuration.md) | Every config key, file and environment variable |
| 8 | [Workflows & recipes](08-workflows.md) | End-to-end scenarios you can copy |
| 9 | [Safety & troubleshooting](09-safety-and-troubleshooting.md) | Guard rails, exit codes, common errors, FAQ |

---

## Conventions used in every page

- All examples use the short alias **`oii`**. The same CLI also answers to
  `odoo-installer` and `python -m odoo_installer`.
- `$` at the start of a block means *a shell command*; blocks without `$` show
  **output**.
- Mutating commands are **dry runs by default**; the examples add `--apply`
  (and `--yes` for destructive actions) when they intend to execute.
- `grep`-friendly keywords such as `--apply`, `--yes`, `--resolve-deps` are always
  written exactly as you type them.
- A `✔` means the step succeeded; `already satisfied` means the tool found nothing
  left to do.
- Placeholder values are written like `<name>`, `<db>` or `X.Y.Z`.

---

## Not what you are looking for?

- A quick overview lives in the [project README](../../README.md).
- A single-page usage guide: [USAGE.md](../../USAGE.md) ·
  [Türkçe](../../USAGE.tr.md).
- Contributor/architecture material: [DEVELOPMENT.md](../../DEVELOPMENT.md).
- Release history: [CHANGELOG.md](../../CHANGELOG.md).

---

[Next: Overview ➡️](01-overview.md)
