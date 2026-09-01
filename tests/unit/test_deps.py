"""Tests for the OCA dependency resolver and --resolve-deps install flow."""

from __future__ import annotations

from pathlib import Path

from fakes import FakeDocker, FakeFs

from odoo_installer.core.modules import (
    module_manifest_deps,
    read_manifest_deps,
    resolve_dependencies,
)
from odoo_installer.schemas import InstanceManifest, RepoRecord, TestedModule

CORE_ADDONS = "base\nweb\nmail\nproduct\nsale\nstock\nweb_tour\n"


def _manifest(tmp_path: Path) -> InstanceManifest:
    return InstanceManifest(
        name="dev",
        dir=tmp_path / "inst",
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=8070,
    )


def _write_manifest(fs: FakeFs, module_dir: Path, deps: list[str], name: str | None = None) -> None:
    fs.ensure_dir(module_dir)
    deps_repr = ", ".join(f'"{d}"' for d in deps)
    fs.write_text(
        module_dir / "__manifest__.py",
        '{"name": "' + (name or module_dir.name) + '", '
        f'"depends": [{deps_repr}], "version": "19.0.1.0.0"}}',
    )


def test_read_manifest_deps_parses_literal() -> None:
    fs = FakeFs()
    module_dir = Path("/tmp/m/mod_a")
    _write_manifest(fs, module_dir, ["base", "web", "mod_b"])
    assert read_manifest_deps(fs, module_dir) == ["base", "web", "mod_b"]


def test_read_manifest_deps_survives_exotic_manifest() -> None:
    fs = FakeFs()
    module_dir = Path("/tmp/m/mod_weird")
    fs.write_text(
        module_dir / "__manifest__.py",
        'NAME = "x"\n{"name": NAME, "depends": ["base"], "summary": ")]} trick"}',
    )
    assert read_manifest_deps(fs, module_dir) == ["base"]


def test_read_manifest_deps_missing_file() -> None:
    assert read_manifest_deps(FakeFs(), Path("/tmp/m/nothing")) == []


def test_module_manifest_deps_local(tmp_path: Path) -> None:
    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(
        fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product", "attribute_set"]
    )
    assert module_manifest_deps(fs, manifest, "pim") == ["product", "attribute_set"]
    assert module_manifest_deps(fs, manifest, "ghost") == []


def test_resolve_dependencies_core_passthrough(tmp_path: Path) -> None:
    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product", "mail"])
    docker = FakeDocker(compose_results=[CORE_ADDONS])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=docker, targets=["pim"], catalog={}
    )
    assert resolution.to_install == ["pim"]
    assert resolution.to_mount == []
    assert resolution.unresolved == []


def test_resolve_dependencies_mounts_catalog_provider(tmp_path: Path) -> None:
    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(
        fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product", "web_dark_mode"]
    )
    catalog = {
        "web_dark_mode": TestedModule(name="web_dark_mode", repo="OCA/web", branch="19.0", deps=[]),
    }
    docker = FakeDocker(compose_results=[CORE_ADDONS])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=docker, targets=["pim"], catalog=catalog
    )
    assert resolution.to_mount == [("OCA/web", "19.0", ["web_dark_mode"])]
    assert resolution.to_install == ["pim", "web_dark_mode"]
    assert resolution.unresolved == []


def test_resolve_dependencies_satisfied_by_mounted_repo(tmp_path: Path) -> None:
    fs = FakeFs()
    stack = tmp_path / "inst"
    _write_manifest(fs, stack / "repos" / "oca-web" / "web_dark_mode", ["web"])
    manifest = InstanceManifest(
        name="dev",
        dir=stack,
        odoo_version="19.0",
        image="odoo:19.0",
        pg_tag=17,
        http_port=8070,
        repos=[
            RepoRecord(
                repo="OCA/web",
                url="https://github.com/OCA/web.git",
                branch="19.0",
                commit="d4bfccf5",
                host_path=stack / "repos" / "oca-web",
                container_path="/mnt/oca/web",
                modules=["web_dark_mode"],
            )
        ],
    )
    _write_manifest(fs, stack / "addons" / "local" / "pim", ["product", "web_dark_mode"])
    catalog = {
        "web_dark_mode": TestedModule(name="web_dark_mode", repo="OCA/web", branch="19.0", deps=[]),
    }
    docker = FakeDocker(compose_results=[CORE_ADDONS])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=docker, targets=["pim"], catalog=catalog
    )
    assert resolution.to_mount == []
    assert resolution.to_install == ["pim"]
    assert resolution.unresolved == []


def test_resolve_dependencies_walks_catalog_deps(tmp_path: Path) -> None:
    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(
        fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product", "web_dark_mode"]
    )
    catalog = {
        "web_dark_mode": TestedModule(
            name="web_dark_mode",
            repo="OCA/web",
            branch="19.0",
            deps=["web_tour"],
        ),
    }
    docker = FakeDocker(compose_results=[CORE_ADDONS])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=docker, targets=["pim"], catalog=catalog
    )
    assert resolution.unresolved == []  # web_tour is core in CORE_ADDONS


def test_resolve_dependencies_unresolved_unknown(tmp_path: Path) -> None:
    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product", "not_anywhere"])
    docker = FakeDocker(compose_results=[CORE_ADDONS])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=docker, targets=["pim"], catalog={}
    )
    assert resolution.unresolved == ["not_anywhere"]


def test_resolve_dependencies_docker_failure_degrades(tmp_path: Path) -> None:
    class ExplodingDocker(FakeDocker):
        def compose(self, args: list[str], project_dir: Path, timeout_s: int = 300) -> str:
            if args[:2] == ["exec", "-T"]:
                raise RuntimeError("container gone")
            return ""

    fs = FakeFs()
    manifest = _manifest(tmp_path)
    _write_manifest(fs, tmp_path / "inst" / "addons" / "local" / "pim", ["product"])
    resolution = resolve_dependencies(
        fs=fs, manifest=manifest, docker=ExplodingDocker(), targets=["pim"], catalog={}
    )
    # conservative degradation: without the container listing, core cannot be
    # verified, so even Odoo-core-looking deps are reported unresolved, not guessed
    assert resolution.unresolved == ["product"]
    assert resolution.to_mount == []
