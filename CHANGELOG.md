# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project scaffold: src-layout package, Typer CLI entry point (`odoo-installer`, alias
  `oii`), `--version` flag and `version` command, static constants for the Odoo 19.0
  stack, and the typed error hierarchy.
- Developer tooling: ruff (format + lint), mypy (strict), pytest with coverage, and
  unit tests for the CLI entry point.
- CI: lint/types and unit test matrix (Python 3.11–3.13) via GitHub Actions.
- `doctor` command: host checks for the docker engine and compose plugin, docker group
  membership (read from `/etc/group`, not stale process groups), git, disk space at the
  instances root, port availability on 8069–8099, and GitHub API reachability. Renders a
  rich table or `--json`; exits with code 4 when a critical check fails.
- `config show|set|path` sub-app backed by validated, atomic TOML persistence
  (`~/.config/odoo-installer/config.toml`); instance registry load/save helpers for M2.
- Host adapters (docker, system, github, filesystem) behind `Protocol` interfaces;
  unit tests run fully offline against fakes.
