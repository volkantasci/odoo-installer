"""Spec loading/validation and `oii apply` plan assembly (fakes only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub, FakeSystem
from typer.testing import CliRunner

from odoo_installer.cli.deps import Container
from odoo_installer.cli.main import app
from odoo_installer.core.spec import DatabaseDefaults, load_spec, repo_arg_from_url
from odoo_installer.exceptions import ConfigError, StackError
from odoo_installer.schemas import GlobalConfig

runner = CliRunner()


# ---------------------------------------------------------------- spec loading


def write_spec(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "odoo-stack.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_spec_full_shape(tmp_path: Path) -> None:
    path = write_spec(
        tmp_path,
        """
name = "acme"
http_port = 8069

[ingress]
network = "violetear-ingress"
""",
    )
    with pytest.raises(ConfigError, match="mutually exclusive"):
        load_spec(path)


def test_load_spec_minimal(tmp_path: Path) -> None:
    spec = load_spec(write_spec(tmp_path, 'name = "acme"\n'))
    assert spec.name == "acme"
    assert spec.repos == []
    assert spec.databases == {}


def test_load_spec_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid stack spec"):
        load_spec(write_spec(tmp_path, 'name = "x"\nunknown_key = 1\n'))


def test_load_spec_rejects_bad_db_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid database name"):
        load_spec(write_spec(tmp_path, 'name = "x"\n[databases."9bad"]\ninstall = []\n'))


def test_load_spec_database_defaults(tmp_path: Path) -> None:
    spec = load_spec(
        write_spec(
            tmp_path,
            """
name = "locale"

[databases.locale_db]
install = ["base"]

[databases.locale_db.defaults]
lang = "tr_TR"
country = "TR"
timezone = "Europe/Istanbul"
currency = "TRY"
""",
        )
    )
    defaults = spec.databases["locale_db"].defaults
    assert defaults is not None
    assert (defaults.lang, defaults.country, defaults.timezone, defaults.currency) == (
        "tr_TR",
        "TR",
        "Europe/Istanbul",
        "TRY",
    )


def test_load_spec_rejects_invalid_database_defaults(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="invalid stack spec"):
        load_spec(
            write_spec(
                tmp_path,
                """
name = "locale"

[databases.locale_db.defaults]
lang = "TURKISH"
""",
            )
        )


def test_load_spec_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read stack spec"):
        load_spec(tmp_path / "nope.toml")


def test_repo_arg_from_url_variants() -> None:
    assert repo_arg_from_url("OCA/web") == "OCA/web"
    assert repo_arg_from_url("web") == "OCA/web"
    assert repo_arg_from_url("https://github.com/OCA/web.git") == "OCA/web"
    assert repo_arg_from_url("https://github.com/OCA/web") == "OCA/web"
    assert repo_arg_from_url("git@github.com:OCA/web.git") == "OCA/web"
    with pytest.raises(StackError, match="only GitHub"):
        repo_arg_from_url("https://gitlab.com/OCA/web.git")
    with pytest.raises(StackError, match="invalid repository"):
        repo_arg_from_url("https://github.com/a/b/c")


# ------------------------------------------------------------- apply planning


def make_container(tmp_path: Path, **overrides: object) -> Container:
    return Container(
        config=GlobalConfig(instances_root=tmp_path / "instances"),
        config_path=tmp_path / "config.toml",
        registry_path=tmp_path / "registry.toml",
        tested_path=tmp_path / "tested.toml",
        git=overrides.get("git", FakeGit(remote="https://github.com/OCA/web.git")),
        docker=overrides.get("docker", FakeDocker()),
        system=overrides.get("system", FakeSystem()),
        github=overrides.get(
            "github",
            FakeGitHub(
                module_manifests={
                    "web_environment_ribbon": "{'name': 'web_environment_ribbon', 'depends': []}"
                }
            ),
        ),
        fs=overrides.get("fs", FakeFs()),
    )


@pytest.fixture
def patch_deps(monkeypatch: pytest.MonkeyPatch):
    def _install(container: Container) -> None:
        monkeypatch.setattr("odoo_installer.cli.deps.build", lambda config_path=None: container)

    return _install


def test_apply_dry_run_fresh_instance(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "fresh"
http_port = 18069

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.freshdb]
install = ["base"]
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["instance"] == "fresh"
    assert payload["created"] is True
    descriptions = [s["description"] for s in payload["steps"]]
    assert any("converge repos, databases" in d for d in descriptions)
    assert not (tmp_path / "instances" / "fresh").exists()  # dry run writes nothing


def test_apply_existing_instance_details_repo_and_db_steps(
    patch_deps, tmp_path: Path, monkeypatch
) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    # create the instance first (fakes: no containers, just files + registry)
    created = runner.invoke(app, ["instance", "create", "app1", "--apply"])
    assert created.exit_code == 0, created.output

    spec = write_spec(
        tmp_path,
        """
name = "app1"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.app1db]
install = ["base", "web_environment_ribbon"]
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["created"] is False
    descriptions = [s["description"] for s in payload["steps"]]
    assert any("web_environment_ribbon" in d for d in descriptions)
    assert any("ensure database 'app1db' exists" in d for d in descriptions)
    assert any("install modules base, web_environment_ribbon" in d for d in descriptions)


def test_apply_executes_and_converges_idempotently(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    # every runtime probe in the install step (core listing, psql, odoo -i) is
    # served from this queue; the core listing must contain the core modules
    container.docker = FakeDocker(compose_results=["base\nweb\nmail\nbus\n"] * 24)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "conv"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]

[databases.convdb]
install = ["base"]
""",
    )
    first = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert first.exit_code == 0, first.output
    assert (tmp_path / "instances" / "conv" / ".odoo-installer.json").exists()

    # second apply: create steps satisfied; repo steps re-run their idempotent
    # plans; install step reports already-installed via module_states stub
    second = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert second.exit_code == 0, second.output
    assert "already satisfied" in second.output


def test_apply_removes_repos_dropped_from_spec(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    (tmp_path / "a").mkdir()
    with_repos = write_spec(
        tmp_path / "a",
        """
name = "diff"
""",
    )
    base = write_spec(
        tmp_path,
        """
name = "diff"

[[repos]]
url = "https://github.com/OCA/web.git"
modules = ["web_environment_ribbon"]
""",
    )
    # create with the repo, then apply the repo-less spec
    created = runner.invoke(app, ["apply", str(base), "--apply"])
    assert created.exit_code == 0, created.output
    manifest = json.loads((tmp_path / "instances" / "diff" / ".odoo-installer.json").read_text())
    assert any(r["repo"] == "OCA/web" for r in manifest["repos"])
    removed = runner.invoke(app, ["apply", str(with_repos), "--apply"])
    assert removed.exit_code == 0, removed.output
    assert "remove /mnt/oca/web mount from the compose file" in removed.output
    assert "forget OCA/web in .odoo-installer.json" in removed.output


def test_apply_ingress_spec_publishes_no_port(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    spec = write_spec(
        tmp_path,
        """
name = "ing"

[ingress]
network = "violetear-ingress"
alias = "tenant-42"

[resources]
memory = "2g"

[settings]
proxy_mode = true
list_db = false
""",
    )
    result = runner.invoke(app, ["apply", str(spec), "--apply"])
    assert result.exit_code == 0, result.output
    compose = (tmp_path / "instances" / "ing" / "docker-compose.yml").read_text()
    assert "ports:" not in compose
    assert "tenant-42" in compose
    assert "mem_limit: 2g" in compose
    conf = (tmp_path / "instances" / "ing" / "config" / "odoo.conf").read_text()
    assert "proxy_mode = True" in conf
    assert "list_db = False" in conf


def test_apply_renders_knobs_and_keeps_them_on_reapply(patch_deps, tmp_path: Path) -> None:
    container = make_container(tmp_path)
    patch_deps(container)
    first = write_spec(
        tmp_path,
        """
name = "knobs"
[ingress]
network = "violetear-ingress"
[resources]
memory = "1536m"
cpus = 1.0
[settings]
workers = 1
max_cron_threads = 1
limit_memory_soft = "1536m"
""",
    )
    assert runner.invoke(app, ["apply", str(first), "--apply"]).exit_code == 0
    stack = tmp_path / "instances" / "knobs"
    assert "max_cron_threads = 1" in (stack / "config" / "odoo.conf").read_text().splitlines()
    assert "mem_limit: 1536m" in (stack / "docker-compose.yml").read_text()
    second = write_spec(
        tmp_path,
        """
name = "knobs"
[ingress]
network = "violetear-ingress"
[resources]
memory = "4g"
""",
    )
    assert runner.invoke(app, ["apply", str(second), "--apply"]).exit_code == 0
    conf = (stack / "config" / "odoo.conf").read_text().splitlines()
    assert "max_cron_threads = 1" in conf  # manifest precedence: unspecified keeps value
    assert "limit_memory_soft = 1610612736" in conf
    assert "mem_limit: 4g" in (stack / "docker-compose.yml").read_text()  # explicit value wins


def test_load_spec_rejects_decimal_memory_knob(tmp_path: Path) -> None:
    path = write_spec(tmp_path, 'name = "x"\n[settings]\nlimit_memory_soft = "1.5g"\n')
    with pytest.raises(ConfigError):
        load_spec(path)


def test_load_spec_rejects_decimal_hard_limit(tmp_path: Path) -> None:
    path = write_spec(tmp_path, 'name = "x"\n[settings]\nlimit_memory_hard = "2.5g"\n')
    with pytest.raises(ConfigError):
        load_spec(path)


@pytest.mark.parametrize("knob", ["limit_memory_soft", "limit_memory_hard"])
@pytest.mark.parametrize("value", ["0", "255m", "1k", "1048576"])
def test_load_spec_rejects_memory_limits_below_the_floor(
    tmp_path: Path, knob: str, value: str
) -> None:
    """limit_memory_hard is RLIMIT_AS: a tiny value means no worker can start."""
    path = write_spec(tmp_path, f'name = "x"\n[settings]\n{knob} = "{value}"\n')
    with pytest.raises(ConfigError, match="256m"):
        load_spec(path)


def test_load_spec_accepts_limits_from_the_floor_up(tmp_path: Path) -> None:
    spec = load_spec(
        write_spec(
            tmp_path,
            'name = "x"\n[settings]\nlimit_memory_soft = "262144k"\nlimit_memory_hard = "256m"\n',
        )
    )
    assert spec.settings is not None
    assert (spec.settings.limit_memory_soft, spec.settings.limit_memory_hard) == (
        "262144k",
        "256m",
    )


def test_load_spec_rejects_soft_limit_above_hard_limit(tmp_path: Path) -> None:
    path = write_spec(
        tmp_path, 'name = "x"\n[settings]\nlimit_memory_soft = "3g"\nlimit_memory_hard = "2560m"\n'
    )
    with pytest.raises(ConfigError, match="limit_memory_soft"):
        load_spec(path)
    equal = 'name = "x"\n[settings]\nlimit_memory_soft = "2g"\nlimit_memory_hard = "2048m"\n'
    assert load_spec(write_spec(tmp_path, equal)).settings is not None


def test_apply_keeps_limit_memory_hard_on_reapply(patch_deps, tmp_path: Path) -> None:
    """Like every knob: an unspecified hard limit keeps the manifest's value,
    an explicit one wins (violetear relies on always naming it)."""
    container = make_container(tmp_path)
    patch_deps(container)
    stack = tmp_path / "instances" / "hard"
    first = write_spec(
        tmp_path,
        """
name = "hard"
[ingress]
network = "violetear-ingress"
[settings]
limit_memory_soft = "1536m"
limit_memory_hard = "2g"
""",
    )
    assert runner.invoke(app, ["apply", str(first), "--apply"]).exit_code == 0
    assert (
        "limit_memory_hard = 2147483648"
        in (stack / "config" / "odoo.conf").read_text().splitlines()
    )
    unspecified = write_spec(tmp_path, 'name = "hard"\n[ingress]\nnetwork = "violetear-ingress"\n')
    assert runner.invoke(app, ["apply", str(unspecified), "--apply"]).exit_code == 0
    conf = (stack / "config" / "odoo.conf").read_text().splitlines()
    assert "limit_memory_hard = 2147483648" in conf  # kept from the manifest
    explicit = write_spec(
        tmp_path,
        """
name = "hard"
[ingress]
network = "violetear-ingress"
[settings]
limit_memory_soft = "2048m"
limit_memory_hard = "2560m"
""",
    )
    assert runner.invoke(app, ["apply", str(explicit), "--apply"]).exit_code == 0
    conf = (stack / "config" / "odoo.conf").read_text().splitlines()
    assert "limit_memory_hard = 2684354560" in conf  # the explicit value wins
    assert "limit_memory_soft = 2147483648" in conf


# --- staged first init -------------------------------------------------------


def _run_install_step(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    modules: list[str],
    defaults: DatabaseDefaults | None,
    *,
    password: str | None = "pw",
    docker: FakeDocker | None = None,
    initialized: bool = False,
) -> tuple[FakeDocker, list[str]]:
    from types import SimpleNamespace

    from odoo_installer.core import apply as apply_mod

    docker = docker or FakeDocker()
    scripts: list[str] = []
    orig_transfer = docker.compose_transfer

    def capture(args, project_dir, *, stdin_path=None, stdout_path=None, timeout_s=1800):  # type: ignore[no-untyped-def]
        if stdin_path is not None:
            scripts.append(Path(stdin_path).read_text(encoding="utf-8"))
        orig_transfer(
            args,
            project_dir,
            stdin_path=stdin_path,
            stdout_path=stdout_path,
            timeout_s=timeout_s,
        )

    docker.compose_transfer = capture  # type: ignore[method-assign]
    manifest = SimpleNamespace(dir=tmp_path, web_service="web", db_service="db", db_user="odoo")
    monkeypatch.setattr(apply_mod, "load_manifest", lambda fs, d: manifest)
    monkeypatch.setattr(apply_mod, "available_modules", lambda fs, m: dict.fromkeys(modules, "x"))
    monkeypatch.setattr(apply_mod, "_states_safe", lambda *a, **k: None)
    monkeypatch.setattr(apply_mod, "_db_initialized", lambda *a, **k: initialized)
    monkeypatch.setattr(
        apply_mod, "_secret_or", lambda fs, d, key: password if key.endswith("PASSWORD") else None
    )
    step = apply_mod._install_step(
        docker=docker,
        fs=FakeFs(),
        stack_dir=tmp_path,
        db="shop",
        modules=modules,
        allow_untested=True,
        defaults=defaults,
        tested_path=tmp_path / "tested.json",
    )
    step.run()
    return docker, scripts


def _odoo_calls(docker: FakeDocker) -> list[tuple[str, ...]]:
    return [args for args, _ in docker.compose_calls if "psql" not in args]


def _kinds(docker: FakeDocker) -> list[str]:
    out = []
    for args in _odoo_calls(docker):
        out.append("shell" if "shell" in args else "install " + args[args.index("-i") + 1])
    return out


def test_first_init_with_country_installs_base_then_defaults_then_apps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker, scripts = _run_install_step(
        monkeypatch,
        tmp_path,
        ["base", "account", "sale"],
        DatabaseDefaults(lang="tr_TR", country="TR"),
    )
    calls = _odoo_calls(docker)
    assert calls[0] == (
        "exec", "-T", "web", "odoo", "-d", "shop", "-i", "base",
        "--stop-after-init", "--http-port=8071", "--load-language=tr_TR",
    )  # fmt: skip
    assert "shell" in calls[1]
    assert "search([('code', '=', 'TR')]" in scripts[0]
    assert calls[2] == (
        "exec", "-T", "web", "odoo", "-d", "shop", "-i", "account,sale",
        "--stop-after-init", "--http-port=8071",
    )  # fmt: skip
    assert len(calls) == 3


def test_first_init_with_only_base_runs_no_empty_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker, _ = _run_install_step(
        monkeypatch, tmp_path, ["base"], DatabaseDefaults(lang="tr_TR", country="TR")
    )
    assert _kinds(docker) == ["install base", "shell"]


def test_first_init_without_country_keeps_single_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker, _ = _run_install_step(
        monkeypatch, tmp_path, ["base", "account", "sale"], DatabaseDefaults(lang="tr_TR")
    )
    assert _kinds(docker) == ["install base,account,sale", "shell"]
    assert "--load-language=tr_TR" in _odoo_calls(docker)[0]


def test_first_init_without_password_keeps_single_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker, _ = _run_install_step(
        monkeypatch,
        tmp_path,
        ["base", "account"],
        DatabaseDefaults(lang="tr_TR", country="TR"),
        password=None,
    )
    assert _kinds(docker) == ["install base,account"]


def test_staged_first_init_without_lang_has_no_load_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker, _ = _run_install_step(
        monkeypatch, tmp_path, ["base", "account"], DatabaseDefaults(country="TR")
    )
    assert _kinds(docker) == ["install base", "shell", "install account"]
    assert not any(a.startswith("--load-language") for a in _odoo_calls(docker)[0])


def test_base_url_default_reaches_the_orm_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, scripts = _run_install_step(
        monkeypatch,
        tmp_path,
        ["base", "account"],
        DatabaseDefaults(country="TR", base_url="https://acme.example.com"),
    )
    assert "web.base.url" in scripts[0]
    assert "https://acme.example.com" in scripts[0]


class _FailingDocker(FakeDocker):
    """Raises StackError for compose calls whose args contain `fail_on`."""

    def __init__(
        self, fail_on: str, *, drop_fails: bool = False, exc: Exception | None = None
    ) -> None:
        super().__init__()
        self.exc = exc
        self.fail_on = fail_on
        self.drop_fails = drop_fails

    def compose(self, args, project_dir, timeout_s=300):  # type: ignore[no-untyped-def]
        out = super().compose(args, project_dir, timeout_s)
        if self.drop_fails and "DROP DATABASE" in args[-1]:
            raise StackError("postgres is down")
        if any(self.fail_on in a for a in args):
            raise self.exc or StackError(f"boom in {self.fail_on}")
        return out

    def compose_transfer(self, args, project_dir, **kwargs):  # type: ignore[no-untyped-def]
        super().compose_transfer(args, project_dir, **kwargs)
        if any(self.fail_on in a for a in args):
            raise self.exc or StackError(f"boom in {self.fail_on}")


def _drops(docker: FakeDocker) -> list[str]:
    return [a[-1] for a, _ in docker.compose_calls if "DROP DATABASE" in a[-1]]


def test_failed_defaults_script_drops_the_half_initialised_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("shell")
    with pytest.raises(StackError, match="boom in shell") as exc:
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
        )
    assert _drops(docker) == ['DROP DATABASE IF EXISTS "shop" WITH (FORCE)']
    assert "removed" in str(exc.value) and "shop" in str(exc.value)


def test_failed_apps_install_in_staged_flow_drops_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("account")
    with pytest.raises(StackError, match="boom in account"):
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
        )
    assert len(_drops(docker)) == 1


def test_failed_install_on_initialised_database_does_not_drop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("account")
    with pytest.raises(StackError, match="boom in account"):
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
            initialized=True,
        )
    assert _drops(docker) == []


def test_drop_failure_keeps_the_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("shell", drop_fails=True)
    with pytest.raises(StackError, match="boom in shell") as exc:
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
        )
    assert "could not be removed" in str(exc.value)
    assert "postgres is down" in str(exc.value)


def test_non_compose_error_in_first_init_also_drops_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("shell", exc=OSError("disk full"))
    with pytest.raises(StackError, match="OSError: disk full") as exc:
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
        )
    assert len(_drops(docker)) == 1
    assert "removed" in str(exc.value)
    assert isinstance(exc.value.__cause__, OSError)


# --- fail-safe detection, interrupted-init marker, drop gates ------------------


class ScriptDocker(FakeDocker):
    """Feeds scripted psql output (matched on a SQL substring) through compose().

    A rule value that is an Exception is raised, like a failing psql would.
    """

    def __init__(self, rules: dict[str, str | Exception] | None = None) -> None:
        super().__init__()
        self.rules = rules or {}

    def compose(self, args, project_dir, timeout_s=300):  # type: ignore[no-untyped-def]
        super().compose(args, project_dir, timeout_s)
        if "psql" in args:
            for needle, out in self.rules.items():
                if needle in args[-1]:
                    if isinstance(out, Exception):
                        raise out
                    return out
        return ""


NO_RELATION = StackError('relation "ir_module_module" does not exist')
REGISTRY_SQL = "table_name = 'ir_module_module'"
TABLE_COUNT_SQL = "SELECT count(*)"
STATES_SQL = "FROM ir_module_module WHERE name IN"
COMMENT_SQL = "shobj_description"
PENDING = "oii:first-init-pending"
LOGIN_COUNT_SQL = "FROM res_users_log"


def _run_real_detection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    docker: FakeDocker,
    modules: list[str],
    defaults: DatabaseDefaults | None,
    *,
    password: str | None = "pw",
) -> str:
    """Runs _install_step with the REAL detection functions (only manifest/secrets faked)."""
    from types import SimpleNamespace

    from odoo_installer.core import apply as apply_mod

    manifest = SimpleNamespace(dir=tmp_path, web_service="web", db_service="db", db_user="odoo")
    monkeypatch.setattr(apply_mod, "load_manifest", lambda fs, d: manifest)
    monkeypatch.setattr(apply_mod, "available_modules", lambda fs, m: dict.fromkeys(modules, "x"))
    monkeypatch.setattr(
        apply_mod, "_secret_or", lambda fs, d, key: password if key.endswith("PASSWORD") else None
    )
    step = apply_mod._install_step(
        docker=docker,
        fs=FakeFs(),
        stack_dir=tmp_path,
        db="shop",
        modules=modules,
        allow_untested=True,
        defaults=defaults,
        tested_path=tmp_path / "tested.json",
    )
    return step.run()


def _trace(docker: FakeDocker) -> list[str]:
    """One label per compose call, in order: psql SQL as 'db: sql', odoo calls by kind."""
    out = []
    for args, _ in docker.compose_calls:
        if "psql" in args:
            out.append(f"{args[args.index('-d') + 1]}: {args[-1]}")
        elif "shell" in args:
            out.append("odoo shell")
        elif "-i" in args:
            out.append("odoo -i " + args[args.index("-i") + 1])
    return out


def _fresh_rules(**extra: str | Exception) -> dict[str, str | Exception]:
    rules: dict[str, str | Exception] = {
        STATES_SQL: NO_RELATION,
        REGISTRY_SQL: "",
        TABLE_COUNT_SQL: "0",
    }
    rules.update(extra)
    return rules


def test_marker_wraps_a_staged_first_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    docker = ScriptDocker(_fresh_rules())
    _run_real_detection(
        monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults(country="TR")
    )
    trace = [t for t in _trace(docker) if t.startswith(("odoo", "postgres: COMMENT"))]
    assert trace == [
        f"postgres: COMMENT ON DATABASE \"shop\" IS '{PENDING}'",
        "odoo -i base",
        "odoo shell",
        'postgres: COMMENT ON DATABASE "shop" IS NULL',
        "odoo -i account",
    ]


def test_marker_wraps_a_single_install_first_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker(_fresh_rules())
    _run_real_detection(monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults())
    trace = [t for t in _trace(docker) if t.startswith(("odoo", "postgres: COMMENT"))]
    assert trace == [
        f"postgres: COMMENT ON DATABASE \"shop\" IS '{PENDING}'",
        "odoo -i base,account",
        "odoo shell",
        'postgres: COMMENT ON DATABASE "shop" IS NULL',
    ]


def test_no_password_means_no_marker_sql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    docker = ScriptDocker(_fresh_rules())
    _run_real_detection(
        monkeypatch, tmp_path, docker, ["base"], DatabaseDefaults(country="TR"), password=None
    )
    assert not any("COMMENT ON" in t for t in _trace(docker))


def test_pending_marker_at_start_drops_recreates_and_redoes_first_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker(
        {
            STATES_SQL: "",  # query ran: tables exist (module absent)
            COMMENT_SQL: PENDING,
            LOGIN_COUNT_SQL: "0",
        }
    )
    note = _run_real_detection(
        monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults(country="TR")
    )
    trace = [t for t in _trace(docker) if "shobj" not in t and "ir_module_module" not in t]
    assert trace[0] == "shop: SELECT count(*) FROM res_users_log"  # login guard first
    trace = trace[1:]
    assert trace[0] == 'postgres: DROP DATABASE IF EXISTS "shop" WITH (FORCE)'
    assert trace[1].startswith("postgres: SELECT 1 FROM pg_database")  # create_database probe
    assert trace[2] == 'postgres: CREATE DATABASE "shop"'
    assert f"postgres: COMMENT ON DATABASE \"shop\" IS '{PENDING}'" in trace
    assert trace.index("odoo -i base") < trace.index("odoo shell") < trace.index("odoo -i account")
    assert "interrupted first init" in note


def test_initialised_database_without_marker_is_a_normal_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker({STATES_SQL: "base|installed\naccount|uninstalled", COMMENT_SQL: ""})
    _run_real_detection(
        monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults(country="TR")
    )
    trace = _trace(docker)
    assert not any("DROP" in t or "COMMENT ON" in t or "information_schema" in t for t in trace)
    assert [t for t in trace if t.startswith("odoo")] == ["odoo -i base,account"]


def test_registry_present_via_psql_one_is_initialised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker({STATES_SQL: NO_RELATION, REGISTRY_SQL: "1\n", COMMENT_SQL: ""})
    _run_real_detection(monkeypatch, tmp_path, docker, ["base"], None)
    assert not any("DROP" in t or "COMMENT ON" in t for t in _trace(docker))


def test_garbage_psql_output_refuses_to_guess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker({STATES_SQL: NO_RELATION, REGISTRY_SQL: "1\nTime: 3.2 ms"})
    with pytest.raises(StackError, match="unexpected psql output"):
        _run_real_detection(monkeypatch, tmp_path, docker, ["base"], DatabaseDefaults())
    assert not [t for t in _trace(docker) if t.startswith("odoo")]
    assert not any("DROP" in t for t in _trace(docker))


def test_foreign_tables_without_registry_are_never_initialised_or_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker({STATES_SQL: NO_RELATION, REGISTRY_SQL: "", TABLE_COUNT_SQL: "3"})
    with pytest.raises(StackError, match="has tables but no Odoo registry"):
        _run_real_detection(monkeypatch, tmp_path, docker, ["base"], DatabaseDefaults())
    trace = _trace(docker)
    assert not any("DROP" in t or "COMMENT ON" in t or t.startswith("odoo") for t in trace)


def test_state_query_success_proves_initialisation_without_registry_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker({STATES_SQL: "base|installed", COMMENT_SQL: ""})
    _run_real_detection(monkeypatch, tmp_path, docker, ["base", "sale"], None)
    assert not any("information_schema" in t for t in _trace(docker))


def test_drop_after_single_install_first_init_failure_targets_postgres(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("base,account")
    with pytest.raises(StackError, match="removed"):
        _run_install_step(
            monkeypatch, tmp_path, ["base", "account"], DatabaseDefaults(), docker=docker
        )
    drop = [a for a, _ in docker.compose_calls if "DROP DATABASE" in a[-1]]
    assert len(drop) == 1 and drop[0][drop[0].index("-d") + 1] == "postgres"


def test_drop_after_staged_base_install_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = _FailingDocker("base")
    with pytest.raises(StackError, match="removed"):
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=docker,
        )
    drop = [a for a, _ in docker.compose_calls if "DROP DATABASE" in a[-1]]
    assert len(drop) == 1 and drop[0][drop[0].index("-d") + 1] == "postgres"


def test_drop_failure_of_any_exception_type_keeps_the_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Docker(_FailingDocker):
        def compose(self, args, project_dir, timeout_s=300):  # type: ignore[no-untyped-def]
            if "DROP DATABASE" in args[-1]:
                raise OSError("socket gone")
            return super().compose(args, project_dir, timeout_s)

    with pytest.raises(StackError, match="boom in shell") as exc:
        _run_install_step(
            monkeypatch,
            tmp_path,
            ["base", "account"],
            DatabaseDefaults(country="TR"),
            docker=Docker("shell"),
        )
    assert "socket gone" in str(exc.value) and "could not be removed" in str(exc.value)


@pytest.mark.parametrize("name", ["postgres", "template0", "template1"])
def test_force_drop_refuses_protected_databases(name: str) -> None:
    from odoo_installer.core.dbms import force_drop_database

    docker = FakeDocker()
    with pytest.raises(StackError, match="protected"):
        force_drop_database(docker, Path("/x"), "db", "odoo", name)
    assert docker.compose_calls == []


def _pending_rules(
    logins: str | Exception = "0", states: str = "base|installed\naccount|installed"
):
    return {STATES_SQL: states, COMMENT_SQL: PENDING, LOGIN_COUNT_SQL: logins}


def _redo_trace(docker: FakeDocker) -> list[str]:
    return [t for t in _trace(docker) if t.startswith("odoo") or "DROP" in t or "CREATE DATA" in t]


def test_pending_marker_with_everything_installed_still_redoes_single_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker(_pending_rules())
    note = _run_real_detection(
        monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults(lang="tr_TR")
    )
    assert _redo_trace(docker) == [
        'postgres: DROP DATABASE IF EXISTS "shop" WITH (FORCE)',
        'postgres: CREATE DATABASE "shop"',
        "odoo -i base,account",
        "odoo shell",
    ]
    assert "interrupted first init" in note


def test_pending_marker_with_base_only_still_redoes_staged_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker(_pending_rules(states="base|installed"))
    _run_real_detection(monkeypatch, tmp_path, docker, ["base"], DatabaseDefaults(country="TR"))
    assert _redo_trace(docker) == [
        'postgres: DROP DATABASE IF EXISTS "shop" WITH (FORCE)',
        'postgres: CREATE DATABASE "shop"',
        "odoo -i base",
        "odoo shell",
    ]


@pytest.mark.parametrize(
    "logins", ["3", "1\nTime: 2 ms", "", StackError('relation "res_users_log" does not exist')]
)
def test_pending_marker_never_drops_a_database_with_logins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, logins: str | Exception
) -> None:
    docker = ScriptDocker(_pending_rules(logins=logins))
    with pytest.raises(StackError, match="will not drop it") as exc:
        _run_real_detection(
            monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults(country="TR")
        )
    assert 'COMMENT ON DATABASE "shop" IS NULL' in str(exc.value)
    assert "psql" in str(exc.value) and "default" in str(exc.value)
    assert _redo_trace(docker) == []


def test_failed_redo_says_it_was_an_interrupted_init_that_was_dropped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Docker(ScriptDocker):
        def compose_transfer(self, args, project_dir, **kw):  # type: ignore[no-untyped-def]
            super().compose_transfer(args, project_dir, **kw)
            raise StackError("boom in shell")

    docker = Docker(_pending_rules())
    with pytest.raises(StackError, match="boom in shell") as exc:
        _run_real_detection(monkeypatch, tmp_path, docker, ["base", "account"], DatabaseDefaults())
    assert "interrupted first init" in str(exc.value)
    assert "dropped and re-created" in str(exc.value)


def test_failed_drop_after_marker_points_at_the_marker_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Docker(ScriptDocker):
        def compose_transfer(self, args, project_dir, **kw):  # type: ignore[no-untyped-def]
            super().compose_transfer(args, project_dir, **kw)
            raise StackError("boom in shell")

        def compose(self, args, project_dir, timeout_s=300):  # type: ignore[no-untyped-def]
            if "DROP DATABASE" in args[-1]:
                raise StackError("pg down")
            return super().compose(args, project_dir, timeout_s)

    with pytest.raises(StackError, match="boom in shell") as exc:
        _run_real_detection(
            monkeypatch, tmp_path, Docker(_fresh_rules()), ["base"], DatabaseDefaults()
        )
    assert "could not be removed" in str(exc.value) and "pg down" in str(exc.value)
    assert "manually" not in str(exc.value)
    assert "next apply" in str(exc.value)


def test_garbled_table_count_is_unexpected_output_not_foreign_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker = ScriptDocker(
        {STATES_SQL: NO_RELATION, REGISTRY_SQL: "", TABLE_COUNT_SQL: "3\nTime: 1ms"}
    )
    with pytest.raises(StackError, match="unexpected psql output"):
        _run_real_detection(monkeypatch, tmp_path, docker, ["base"], DatabaseDefaults())


def test_apply_lock_is_exclusive_per_instance(tmp_path: Path) -> None:
    from odoo_installer.core.apply import apply_lock

    registry = tmp_path / "state" / "registry.toml"  # directory does not exist yet
    with apply_lock(registry, "acme"):
        with (
            pytest.raises(StackError, match="another apply is running for acme"),
            apply_lock(registry, "acme"),
        ):
            pass
        with apply_lock(registry, "other"):  # other instances are independent
            pass
    with apply_lock(registry, "acme"):  # released afterwards
        pass
