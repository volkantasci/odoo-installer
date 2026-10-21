"""Odoo CLI runner: module install flags and first-init ORM defaults."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker

from odoo_installer.core.runner import install_modules, set_admin_credentials


class CapturingDocker(FakeDocker):
    def __init__(self) -> None:
        super().__init__()
        self.script: str | None = None

    def compose_transfer(
        self,
        args: list[str],
        project_dir: Path,
        *,
        stdin_path: Path | None = None,
        stdout_path: Path | None = None,
        timeout_s: int = 1800,
    ) -> None:
        if stdin_path is not None:
            self.script = Path(stdin_path).read_text(encoding="utf-8")
        super().compose_transfer(
            args,
            project_dir,
            stdin_path=stdin_path,
            stdout_path=stdout_path,
            timeout_s=timeout_s,
        )


def test_install_modules_adds_load_language(tmp_path: Path) -> None:
    docker = FakeDocker()
    install_modules(docker, tmp_path, "web", "shop", ["base"], load_language="tr_TR")
    args = docker.compose_calls[-1][0]
    assert "--load-language=tr_TR" in args


def test_install_modules_omits_load_language_when_unset(tmp_path: Path) -> None:
    docker = FakeDocker()
    install_modules(docker, tmp_path, "web", "shop", ["base"])
    args = docker.compose_calls[-1][0]
    assert not any(arg.startswith("--load-language") for arg in args)


def test_set_admin_credentials_writes_locale_defaults(tmp_path: Path) -> None:
    docker = CapturingDocker()
    set_admin_credentials(
        docker,
        tmp_path,
        "web",
        "shop",
        "boss",
        "s3cret",
        lang="tr_TR",
        country="TR",
        timezone="Europe/Istanbul",
        currency="TRY",
    )
    assert docker.script is not None
    script = docker.script
    assert "'login': 'boss'" in script
    assert "'password': 's3cret'" in script
    assert "'lang': 'tr_TR'" in script
    assert "'tz': 'Europe/Istanbul'" in script
    assert "env['ir.default'].set('res.partner', 'lang', lang)" in script
    assert "env['res.country'].search([('code', '=', 'TR')]" in script
    assert "env['ir.default'].set('res.partner', 'country_id', country.id)" in script
    assert "env['res.currency'].with_context(active_test=False)" in script
    assert ".search([('name', '=', 'TRY')]" in script
    assert "currency.active = True" in script
    assert "company.write({'currency_id': currency.id})" in script
    assert "admin credentials and defaults set for boss" in script


def test_set_admin_credentials_without_defaults_keeps_script_minimal(tmp_path: Path) -> None:
    docker = CapturingDocker()
    set_admin_credentials(docker, tmp_path, "web", "shop", "boss", "s3cret")
    assert docker.script is not None
    assert "res.country" not in docker.script
    assert "res.currency" not in docker.script
    assert "res.lang" not in docker.script
