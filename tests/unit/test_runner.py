"""Odoo CLI runner: module install flags and first-init ORM defaults."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker
from pydantic import ValidationError

from odoo_installer.core.runner import install_modules, set_admin_credentials
from odoo_installer.core.spec import DatabaseDefaults


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


def test_base_url_writes_frozen_url_and_local_report_url(tmp_path: Path) -> None:
    docker = CapturingDocker()
    set_admin_credentials(
        docker, tmp_path, "web", "shop", "boss", "s3cret", base_url="https://acme.voslo.co"
    )
    script = docker.script
    assert script is not None
    url = script.index("set_param('web.base.url', 'https://acme.voslo.co')")
    freeze = script.index("set_param('web.base.url.freeze', 'True')")
    report = script.index("set_param('report.url', 'http://127.0.0.1:8069')")
    assert url < freeze < report
    assert "env['ir.config_parameter'].sudo()" in script


def test_base_url_absent_writes_no_params(tmp_path: Path) -> None:
    docker = CapturingDocker()
    set_admin_credentials(docker, tmp_path, "web", "shop", "boss", "s3cret")
    assert docker.script is not None
    assert "web.base.url" not in docker.script
    assert "report.url" not in docker.script


@pytest.mark.parametrize("ok", ["https://acme.voslo.co", "http://localhost:8069"])
def test_base_url_accepts_origins(ok: str) -> None:
    assert DatabaseDefaults(base_url=ok).base_url == ok


@pytest.mark.parametrize(
    "bad", ["https://acme.voslo.co/", "acme.voslo.co", "https://acme.voslo.co/odoo", "https://a b"]
)
def test_base_url_must_be_an_origin(bad: str) -> None:
    with pytest.raises(ValidationError):
        DatabaseDefaults(base_url=bad)
