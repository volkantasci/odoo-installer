"""Run odoo CLI commands inside the web container (alternate port convention).

Install/upgrade runs use --stop-after-init on RUNNER_HTTP_PORT (8071) so they never
clash with the serving process — same convention as the manual workflow.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from odoo_installer.adapters.docker import ComposeLike
from odoo_installer.constants import CONTAINER_HTTP_PORT, RUNNER_HTTP_PORT


def install_modules(
    docker: ComposeLike,
    stack_dir: Path,
    web_service: str,
    db: str,
    modules: list[str],
    *,
    upgrade: bool = False,
    load_language: str | None = None,
    timeout_s: int = 1800,
) -> str:
    """`odoo -i/-u` on RUNNER_HTTP_PORT (8071) so the serving process never clashes.

    NOTE: Odoo's own `-r`/`-w` flags are the DATABASE connection user/password,
    not the app's admin login — never pass credentials here. First-time admin
    credentials are set through the ORM via `set_admin_credentials` below.
    """
    flag = "-u" if upgrade else "-i"
    args = [
        "exec",
        "-T",
        web_service,
        "odoo",
        "-d",
        db,
        flag,
        ",".join(modules),
        "--stop-after-init",
        f"--http-port={RUNNER_HTTP_PORT}",
    ]
    if load_language is not None:
        # Odoo's base installer uses this to activate the language and set it
        # as the default for new partners. Only meaningful on first init.
        args.append(f"--load-language={load_language}")
    return docker.compose(args, stack_dir, timeout_s=timeout_s)


def set_admin_credentials(
    docker: ComposeLike,
    stack_dir: Path,
    web_service: str,
    db: str,
    login: str,
    password: str,
    *,
    lang: str | None = None,
    country: str | None = None,
    timezone: str | None = None,
    currency: str | None = None,
    base_url: str | None = None,
    timeout_s: int = 300,
) -> str:
    """Set the database's admin credentials and first-init defaults via the ORM.

    A raw SQL UPDATE would bypass password hashing and brick the login; the
    shell writes through res.users, so passlib hashing and related caches stay
    correct. Only ever run this right after a database's first initialization —
    later runs would silently reset a password the user may have changed.

    ``lang``/``country``/``timezone``/``currency`` are optional first-init
    defaults: they make a fresh database usable in the customer's locale
    without a manual Settings tour. Odoo's ORM validates every value; an
    unknown timezone/currency/country is skipped rather than failing the job.
    """
    values: dict[str, str] = {
        "login": login,
        "password": password,
    }
    if lang is not None:
        values["lang"] = lang
    if timezone is not None:
        values["tz"] = timezone

    lines = [
        "user = env.ref('base.user_admin')",
        "company = env.company",
        "admin_partner = user.partner_id",
        "company_partner = company.partner_id",
        "zones = set(env['res.users']._fields['tz'].get_values(env))",
        f"admin_values = dict({values!r})",
        "if admin_values.get('tz') and admin_values['tz'] not in zones:",
        "    admin_values.pop('tz')",
        "user.write(admin_values)",
    ]
    if lang is not None:
        lines.extend(
            [
                f"lang = {lang!r}",
                "lang_record = env['res.lang']._activate_lang(lang)",
                "if not lang_record and hasattr(env['res.lang'], '_create_lang'):",
                "    lang_record = env['res.lang']._create_lang(lang)",
                "env['ir.default'].set('res.partner', 'lang', lang)",
                "admin_partner.write({'lang': lang})",
                "company_partner.write({'lang': lang})",
            ]
        )
    if country is not None:
        lines.extend(
            [
                f"country = env['res.country'].search([('code', '=', {country!r})], limit=1)",
                "if country:",
                "    admin_partner.write({'country_id': country.id})",
                "    company_partner.write({'country_id': country.id})",
                "    env['ir.default'].set('res.partner', 'country_id', country.id)",
            ]
        )
    if currency is not None:
        lines.extend(
            [
                "currency = env['res.currency'].with_context(active_test=False)"
                f".search([('name', '=', {currency!r})], limit=1)",
                "if currency:",
                "    if not currency.active:",
                "        currency.active = True",
                "    company.write({'currency_id': currency.id})",
            ]
        )
    if base_url is not None:
        # Freeze the public URL: otherwise Odoo rewrites web.base.url on the
        # first admin login. Reports render through the container's own port.
        lines.extend(
            [
                "params = env['ir.config_parameter'].sudo()",
                f"params.set_param('web.base.url', {base_url!r})",
                "params.set_param('web.base.url.freeze', 'True')",
                f"params.set_param('report.url', 'http://127.0.0.1:{CONTAINER_HTTP_PORT}')",
            ]
        )
    lines.extend(
        [
            "env.cr.commit()",
            f"print('admin credentials and defaults set for {login}')",
        ]
    )
    script = "\n".join(lines) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False) as fh:
        fh.write(script)
        script_path = Path(fh.name)
    try:
        docker.compose_transfer(
            ["exec", "-T", web_service, "odoo", "shell", "-d", db, "--no-http"],
            stack_dir,
            stdin_path=script_path,
            timeout_s=timeout_s,
        )
    finally:
        script_path.unlink(missing_ok=True)
    return f"admin login {login!r} password set (ORM-hashed)"
