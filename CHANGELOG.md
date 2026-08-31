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
