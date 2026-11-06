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
) -> tuple[FakeDocker, list[str]]:
    from types import SimpleNamespace

    from odoo_installer.core import apply as apply_mod

    docker = FakeDocker()
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
    monkeypatch.setattr(apply_mod, "_db_initialized", lambda *a, **k: False)
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


def _kinds(docker: FakeDocker) -> list[str]:
    out = []
    for args, _ in docker.compose_calls:
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
    calls = [c[0] for c in docker.compose_calls]
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
    assert "--load-language=tr_TR" in docker.compose_calls[0][0]


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
