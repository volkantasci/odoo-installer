"""Tests for OCA module management core (DEVELOPMENT.md §6 rules)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeDocker, FakeFs, FakeGit, FakeGitHub

from odoo_installer.core.modules import (
    compose_volume_edit,
    compose_volume_remove,
    conf_addons_edit,
    conf_addons_remove,
    discover_modules,
    find_odoo_conf_host_path,
    module_add_plan,
    module_remove_plan,
    split_repo,
)
from odoo_installer.core.plan import apply_steps
from odoo_installer.exceptions import StackError
from odoo_installer.schemas import GlobalConfig, InstanceManifest, RepoRecord, TestedModule

COMPOSE = """services:
  web:
    image: odoo:19.0
    volumes:
      - ./config:/etc/odoo
      - ./addons/local:/mnt/extra-addons
  db:
    image: postgres:17
"""

CONF = """[options]
admin_passwd = x
addons_path = /mnt/extra-addons
db_host = db
"""


def make_manifest(tmp_path: Path, *, adopted: bool = False) -> InstanceManifest:
    stack = tmp_path / "instances" / "dev"
    (stack / "config").mkdir(parents=True, exist_ok=True)
    (stack / "docker-compose.yml").write_text(COMPOSE, encoding="utf-8")
    (stack / "config" / "odoo.conf").write_text(CONF, encoding="utf-8")
    return InstanceManifest(
        name="dev",
        dir=stack,
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=8070,
        adopted=adopted,
    )


def make_config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(instances_root=tmp_path / "instances", repo_root=tmp_path / "repos")


# --- pure editing functions --------------------------------------------------


def test_split_repo() -> None:
    assert split_repo("OCA/server-utils") == ("OCA", "server-utils")
    assert split_repo("server-utils") == ("OCA", "server-utils")
    with pytest.raises(StackError, match="invalid repository"):
        split_repo("bad repo")


def test_compose_volume_edit_appends_with_matching_indent() -> None:
    new, changed = compose_volume_edit(
        COMPOSE, Path("/srv/repos/oca-server-utils"), "/mnt/oca/server-utils", "web"
    )
    assert changed
    assert "- /srv/repos/oca-server-utils:/mnt/oca/server-utils" in new
    # the new line sits inside the web volumes block (6-space indent)
    line = next(ln for ln in new.splitlines() if "oca-server-utils" in ln)
    assert line.startswith("      - ")


def test_compose_volume_edit_is_idempotent() -> None:
    once, changed1 = compose_volume_edit(COMPOSE, Path("/srv/x"), "/mnt/oca/x", "web")
    again, changed2 = compose_volume_edit(once, Path("/srv/x"), "/mnt/oca/x", "web")
    assert changed1 and not changed2
    assert once == again


def test_compose_volume_edit_dedupes_relative_variant(tmp_path: Path) -> None:
    # a hand-written relative mount line must not get a duplicate absolute twin
    host = tmp_path / "repos" / "oca-web"
    relative = COMPOSE.replace(
        "      - ./addons/local:/mnt/extra-addons",
        "      - ./addons/local:/mnt/extra-addons\n      - ./repos/oca-web:/mnt/oca/web",
    )
    again, changed = compose_volume_edit(relative, host, "/mnt/oca/web", "web", base_dir=tmp_path)
    assert not changed
    assert again.count("/mnt/oca/web") == 1


def test_compose_volume_remove_matches_relative_variant(tmp_path: Path) -> None:
    host = tmp_path / "repos" / "oca-web"
    relative = COMPOSE.replace(
        "      - ./addons/local:/mnt/extra-addons",
        "      - ./addons/local:/mnt/extra-addons\n      - ./repos/oca-web:/mnt/oca/web",
    )
    restored, changed = compose_volume_remove(relative, host, "/mnt/oca/web", base_dir=tmp_path)
    assert changed
    assert "/mnt/oca/web" not in restored


def test_compose_volume_edit_requires_volumes_key() -> None:
    minimal = "services:\n  web:\n    image: odoo:19.0\n"
    with pytest.raises(StackError, match="volumes"):
        compose_volume_edit(minimal, Path("/srv/x"), "/mnt/oca/x", "web")


def test_compose_volume_remove() -> None:
    edited, _ = compose_volume_edit(COMPOSE, Path("/srv/x"), "/mnt/oca/x", "web")
    restored, changed = compose_volume_remove(edited, Path("/srv/x"), "/mnt/oca/x")
    assert changed
    assert "/mnt/oca/x" not in restored


def test_conf_addons_edit_and_remove() -> None:
    edited, changed = conf_addons_edit(CONF, "/mnt/oca/server-utils")
    assert changed
    assert "addons_path = /mnt/extra-addons, /mnt/oca/server-utils" in edited
    again, changed2 = conf_addons_edit(edited, "/mnt/oca/server-utils")
    assert not changed2 and again == edited
    restored, removed = conf_addons_remove(edited, "/mnt/oca/server-utils")
    assert removed and "addons_path = /mnt/extra-addons" in restored


def test_conf_addons_remove_refuses_last_entry() -> None:
    with pytest.raises(StackError, match="last addons_path"):
        conf_addons_remove(CONF, "/mnt/extra-addons")


def test_find_odoo_conf_host_path_dir_and_file_mounts(tmp_path: Path) -> None:
    dir_compose = "services:\n  web:\n    volumes:\n      - ./config:/etc/odoo\n"
    assert find_odoo_conf_host_path(dir_compose, tmp_path) == tmp_path / "config" / "odoo.conf"
    file_compose = "services:\n  web:\n    volumes:\n      - ./odoo.conf:/etc/odoo/odoo.conf\n"
    assert find_odoo_conf_host_path(file_compose, tmp_path) == tmp_path / "odoo.conf"


def test_discover_modules(tmp_path: Path) -> None:
    fs = FakeFs()
    (tmp_path / "server-utils").mkdir(parents=True)
    (tmp_path / "server-utils" / "__manifest__.py").write_text("{}", encoding="utf-8")
    (tmp_path / "setup").mkdir()
    (tmp_path / ".hidden").mkdir()
    assert discover_modules(fs, tmp_path) == ["server-utils"]


# --- add plan ----------------------------------------------------------------


def test_module_add_plan_happy_created_instance(tmp_path: Path) -> None:
    fs, git = FakeFs(), FakeGit(sample_modules=("server_util_foo",))
    manifest = make_manifest(tmp_path)
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        modules_opt=None,
        sparse=False,
        fork=None,
        existing_repo=None,
        github=FakeGitHub(),
        git=git,
        fs=fs,
        docker=FakeDocker(),
    )
    apply_steps(plan.steps)
    assert git.cloned[0][0] == "https://github.com/OCA/server-utils.git"
    assert (plan.host_path, "origin/19.0") in git.checkouts
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert f"{plan.host_path}:/mnt/oca/server-utils" in compose
    conf = (manifest.dir / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "/mnt/extra-addons, /mnt/oca/server-utils" in conf
    loaded = InstanceManifest.model_validate_json(
        (manifest.dir / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    assert loaded.repos[0].repo == "OCA/server-utils"
    assert loaded.repos[0].branch == "19.0"


def test_module_add_plan_recreates_created_instance(tmp_path: Path) -> None:
    fs, git, docker = FakeFs(), FakeGit(sample_modules=("server_util_foo",)), FakeDocker()
    manifest = make_manifest(tmp_path)
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        modules_opt=None,
        sparse=False,
        fork=None,
        existing_repo=None,
        github=FakeGitHub(),
        git=git,
        fs=fs,
        docker=docker,
    )
    apply_steps(plan.steps)
    assert ("up", "-d", manifest.web_service) in [args for args, _ in docker.compose_calls]


def test_module_add_plan_refuses_same_container_path_clash(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    manifest.repos = [
        RepoRecord(
            repo="OCA/web",
            url="https://github.com/OCA/web.git",
            branch="19.0",
            commit="a" * 40,
            host_path=manifest.dir / "repos" / "oca-web",
            container_path="/mnt/oca/web",
            modules=["web_responsive"],
        )
    ]
    with pytest.raises(StackError, match="already mounted at /mnt/oca/web"):
        module_add_plan(
            config=make_config(tmp_path),
            manifest=manifest,
            repo_arg="myfork/web",
            modules_opt=None,
            sparse=False,
            fork=None,
            existing_repo=None,
            github=FakeGitHub(),
            git=FakeGit(sample_modules=("web_responsive",)),
            fs=FakeFs(),
            docker=FakeDocker(),
        )


def test_module_add_plan_skips_restart_when_nothing_changes(tmp_path: Path) -> None:
    fs, git = FakeFs(), FakeGit(sample_modules=("server_util_foo",))
    manifest = make_manifest(tmp_path)
    kwargs: dict[str, object] = {
        "config": make_config(tmp_path),
        "manifest": manifest,
        "repo_arg": "server-utils",
        "modules_opt": None,
        "sparse": False,
        "fork": None,
        "existing_repo": None,
        "github": FakeGitHub(),
        "git": git,
        "fs": fs,
    }
    apply_steps(module_add_plan(docker=FakeDocker(), **kwargs).steps)  # type: ignore[arg-type]
    docker2 = FakeDocker()
    plan2 = module_add_plan(docker=docker2, **kwargs)  # type: ignore[arg-type]
    notes = apply_steps(plan2.steps)
    assert "unchanged" in notes
    assert "skipped (nothing changed)" in notes
    assert docker2.compose_calls == []  # nothing touched the runtime at all


def test_module_add_plan_missing_branch_fails_before_clone(tmp_path: Path) -> None:
    fs, git = FakeFs(), FakeGit()

    class NoBranch(FakeGitHub):
        def branch_exists(self, repo: str, branch: str) -> bool:
            return False

    with pytest.raises(StackError, match="does not exist on OCA/server-utils"):
        module_add_plan(
            config=make_config(tmp_path),
            manifest=make_manifest(tmp_path),
            repo_arg="server-utils",
            modules_opt=None,
            sparse=False,
            fork=None,
            existing_repo=None,
            github=NoBranch(),
            git=git,
            fs=fs,
            docker=FakeDocker(),
        )
    assert git.cloned == []  # clone never attempted


def test_module_add_plan_sparse_requests_modules(tmp_path: Path) -> None:
    git = FakeGit()
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=make_manifest(tmp_path),
        repo_arg="server-utils",
        modules_opt=["server_util_foo"],
        sparse=True,
        fork=None,
        existing_repo=None,
        github=FakeGitHub(),
        git=git,
        fs=FakeFs(),
        docker=FakeDocker(),
    )
    apply_steps(plan.steps)
    assert git.sparse_cloned == [
        (
            "https://github.com/OCA/server-utils.git",
            make_config(tmp_path).instances_root / "dev" / "repos" / "oca-server-utils",
            ["server_util_foo"],
        )
    ]
    assert git.sparse == []  # fresh sparse clone sets the cone at clone time
    # the plan itself is honest about the sparse scope
    assert "sparse-clone" in plan.steps[0].description
    assert "only: server_util_foo" in plan.steps[0].description


def test_module_add_plan_adopted_has_no_restart_step(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path, adopted=True)
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        modules_opt=None,
        sparse=False,
        fork=None,
        existing_repo=None,
        github=FakeGitHub(),
        git=FakeGit(sample_modules=("server_util_foo",)),
        fs=FakeFs(),
        docker=FakeDocker(),
    )
    assert not any(("restart" in d or "recreate" in d) for d in (s.description for s in plan.steps))


def test_module_add_plan_adopted_clones_into_repo_root(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path, adopted=True)
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        modules_opt=None,
        sparse=False,
        fork=None,
        existing_repo=None,
        github=FakeGitHub(),
        git=FakeGit(sample_modules=("server_util_foo",)),
        fs=FakeFs(),
        docker=FakeDocker(),
    )
    assert plan.host_path == tmp_path / "repos" / "oca-server-utils"


def test_module_add_plan_existing_repo_never_mutated(tmp_path: Path) -> None:
    fs, git = FakeFs(), FakeGit(existing={tmp_path / "checkout"})
    checkout = tmp_path / "checkout" / "server_util_foo"
    checkout.mkdir(parents=True)
    (checkout / "__manifest__.py").write_text("{}", encoding="utf-8")
    manifest = make_manifest(tmp_path)
    plan = module_add_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        modules_opt=None,
        sparse=False,
        fork=None,
        existing_repo=tmp_path / "checkout",
        github=FakeGitHub(),
        git=git,
        fs=fs,
        docker=FakeDocker(),
    )
    apply_steps(plan.steps)
    assert git.fetched == [] and git.checkouts == [] and git.cloned == []


def test_module_add_plan_existing_repo_wrong_branch_fails(tmp_path: Path) -> None:
    fs, git = FakeFs(), FakeGit(existing={tmp_path / "checkout"}, branch="18.0")
    with pytest.raises(StackError, match="never mutates"):
        module_add_plan(
            config=make_config(tmp_path),
            manifest=make_manifest(tmp_path),
            repo_arg="server-utils",
            modules_opt=None,
            sparse=False,
            fork=None,
            existing_repo=tmp_path / "checkout",
            github=FakeGitHub(),
            git=git,
            fs=fs,
            docker=FakeDocker(),
        )


# --- remove plan -------------------------------------------------------------


def prepared_repos_manifest(tmp_path: Path) -> InstanceManifest:
    manifest = make_manifest(tmp_path)
    mount = f"      - {manifest.dir / 'repos' / 'oca-server-utils'}:/mnt/oca/server-utils"
    compose_with_mount = COMPOSE.replace(
        "      - ./addons/local:/mnt/extra-addons",
        "      - ./addons/local:/mnt/extra-addons\n" + mount,
    )
    (manifest.dir / "docker-compose.yml").write_text(compose_with_mount, encoding="utf-8")
    manifest.repos = [
        RepoRecord(
            repo="OCA/server-utils",
            url="https://github.com/OCA/server-utils.git",
            branch="19.0",
            commit="abc1234",
            host_path=tmp_path / "instances" / "dev" / "repos" / "oca-server-utils",
            container_path="/mnt/oca/server-utils",
            modules=["server_util_foo"],
        )
    ]
    return manifest


def test_module_remove_plan_unmounts_and_purges(tmp_path: Path) -> None:
    fs, docker = FakeFs(), FakeDocker()
    manifest = prepared_repos_manifest(tmp_path)
    (manifest.dir / "repos" / "oca-server-utils").mkdir(parents=True)
    git = FakeGit(existing={manifest.dir / "repos" / "oca-server-utils"})
    plan = module_remove_plan(
        config=make_config(tmp_path),
        manifest=manifest,
        repo_arg="server-utils",
        purge_repo=True,
        db_opt=None,
        dbms_execute_sql=lambda *a, **k: "",
        git=git,
        fs=fs,
        docker=docker,
    )
    apply_steps(plan.steps)
    compose = (manifest.dir / "docker-compose.yml").read_text(encoding="utf-8")
    assert "oca-server-utils" not in compose
    conf = (manifest.dir / "config" / "odoo.conf").read_text(encoding="utf-8")
    assert "oca-server-utils" not in conf
    loaded = InstanceManifest.model_validate_json(
        (manifest.dir / ".odoo-installer.json").read_text(encoding="utf-8")
    )
    assert loaded.repos == []
    assert not (manifest.dir / "repos" / "oca-server-utils").exists()
    assert ("up", "-d", "web") in [args for args, _ in docker.compose_calls]


def test_module_remove_plan_unknown_repo_fails(tmp_path: Path) -> None:
    with pytest.raises(StackError, match="not mounted"):
        module_remove_plan(
            config=make_config(tmp_path),
            manifest=make_manifest(tmp_path),
            repo_arg="ghost",
            purge_repo=False,
            db_opt=None,
            dbms_execute_sql=lambda *a, **k: "",
            git=FakeGit(),
            fs=FakeFs(),
            docker=FakeDocker(),
        )


def test_missing_branch_error_suggests_provider_repo(tmp_path: Path) -> None:
    # user passed a MODULE name (web_responsive); the catalog knows the repo
    manifest = make_manifest(tmp_path)
    with pytest.raises(StackError) as excinfo:
        module_add_plan(
            config=make_config(tmp_path),
            manifest=manifest,
            repo_arg="web_responsive",
            modules_opt=None,
            sparse=False,
            fork=None,
            existing_repo=None,
            github=FakeGitHub(branch_exists=False),
            git=FakeGit(sample_modules=("web_responsive",)),
            fs=FakeFs(),
            docker=FakeDocker(),
            catalog={
                "web_responsive": TestedModule(
                    name="web_responsive", repo="OCA/web", branch="19.0", deps=[]
                )
            },
        )
    message = str(excinfo.value)
    assert "does not exist on OCA/web_responsive" in message
    assert "is a MODULE provided by OCA/web" in message
    assert "oii module add web" in message


def test_missing_branch_error_generic_hint_without_catalog(tmp_path: Path) -> None:
    manifest = make_manifest(tmp_path)
    with pytest.raises(StackError) as excinfo:
        module_add_plan(
            config=make_config(tmp_path),
            manifest=manifest,
            repo_arg="no-such-repo",
            modules_opt=None,
            sparse=False,
            fork=None,
            existing_repo=None,
            github=FakeGitHub(branch_exists=False),
            git=FakeGit(),
            fs=FakeFs(),
            docker=FakeDocker(),
            catalog=None,
        )
    message = str(excinfo.value)
    assert "does not exist on OCA/no-such-repo" in message
    assert "module search no-such-repo" in message
