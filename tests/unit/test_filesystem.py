"""Tests for the FileSystemAdapter — the only adapter that is pure local I/O.

The other adapters (docker/git/github/system) are thin subprocess/network
wrappers, omitted from coverage; they are exercised against the live stack.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from odoo_installer.adapters.filesystem import FileSystemAdapter
from odoo_installer.exceptions import StackError


@pytest.fixture
def fs() -> FileSystemAdapter:
    return FileSystemAdapter()


def test_disk_free_gib_resolves_nearest_ancestor(fs: FileSystemAdapter, tmp_path: Path) -> None:
    free, probe = fs.disk_free_gib(tmp_path / "not" / "there")
    assert free > 0
    assert probe == tmp_path


def test_exists(fs: FileSystemAdapter, tmp_path: Path) -> None:
    assert fs.exists(tmp_path)
    assert not fs.exists(tmp_path / "nope")


def test_ensure_dir_creates_nested(fs: FileSystemAdapter, tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    fs.ensure_dir(target)
    assert target.is_dir()


def test_ensure_dir_fails_when_parent_is_a_file(fs: FileSystemAdapter, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(StackError, match="cannot create directory"):
        fs.ensure_dir(blocker / "sub")


def test_read_text_missing_returns_none(fs: FileSystemAdapter, tmp_path: Path) -> None:
    assert fs.read_text(tmp_path / "missing") is None


def test_read_text_roundtrip(fs: FileSystemAdapter, tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    assert fs.read_text(path) == "hello"


def test_read_text_directory_raises(fs: FileSystemAdapter, tmp_path: Path) -> None:
    with pytest.raises(StackError, match="cannot read"):
        fs.read_text(tmp_path)


def test_write_text_new_file_gets_0644(fs: FileSystemAdapter, tmp_path: Path) -> None:
    path = tmp_path / "new.env"
    fs.write_text(path, "SECRET=1")
    assert path.read_text(encoding="utf-8") == "SECRET=1"
    assert path.stat().st_mode & 0o777 == 0o644


def test_write_text_explicit_mode_wins(fs: FileSystemAdapter, tmp_path: Path) -> None:
    path = tmp_path / "new.env"
    fs.write_text(path, "SECRET=1", mode=0o600)
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_text_preserves_existing_mode(fs: FileSystemAdapter, tmp_path: Path) -> None:
    path = tmp_path / "odoo.conf"
    path.write_text("a = 1\n", encoding="utf-8")
    path.chmod(0o640)
    fs.write_text(path, "a = 2\n")  # no explicit mode: keep 0640
    assert path.read_text(encoding="utf-8") == "a = 2\n"
    assert path.stat().st_mode & 0o777 == 0o640


def test_write_text_fails_when_parent_is_a_file(fs: FileSystemAdapter, tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(StackError, match="cannot write"):
        fs.write_text(blocker / "f", "content")


def test_remove_tree_missing_is_noop(fs: FileSystemAdapter, tmp_path: Path) -> None:
    fs.remove_tree(tmp_path / "missing")  # must not raise


def test_remove_tree_removes_directory(fs: FileSystemAdapter, tmp_path: Path) -> None:
    target = tmp_path / "gone"
    target.mkdir()
    (target / "f").write_text("x", encoding="utf-8")
    fs.remove_tree(target)
    assert not target.exists()


def test_remove_tree_refuses_filesystem_root(fs: FileSystemAdapter) -> None:
    with pytest.raises(StackError, match="refusing"):
        fs.remove_tree(Path("/"))


def test_subdirectories_sorted_hidden_skipped(fs: FileSystemAdapter, tmp_path: Path) -> None:
    (tmp_path / "b-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    dirs = fs.subdirectories(tmp_path)
    assert dirs == [tmp_path / "a-dir", tmp_path / "b-dir"]


def test_subdirectories_missing_raises(fs: FileSystemAdapter, tmp_path: Path) -> None:
    with pytest.raises(StackError, match="cannot list"):
        fs.subdirectories(tmp_path / "missing")
