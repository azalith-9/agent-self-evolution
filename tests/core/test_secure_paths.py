"""Pinned roots reject lexical aliases, special files, and root replacement."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


def api() -> object:
    return importlib.import_module("evolution.core.secure_paths")


@pytest.mark.parametrize(
    "target", ["", ".", "./x", "a//x", "a/./x", "a/../x", "../x", "/x", "x/", "x\0suffix"]
)
def test_noncanonical_relative_paths_are_rejected(tmp_path: Path, target: str) -> None:
    module = api()
    with module.ProtectedRoot.open(tmp_path) as root:
        with pytest.raises(ValueError):
            root.read_regular(target, max_bytes=32)


@pytest.mark.parametrize(
    "kind", ["leaf_symlink", "parent_symlink", "fifo", "directory", "setuid", "setgid", "sticky"]
)
def test_nonregular_and_special_mode_inputs_are_refused_without_reading(
    tmp_path: Path,
    kind: str,
) -> None:
    module = api()
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o700)
    (tmp_path / "outside").write_bytes(b"private")
    target = trusted / "file"
    relative = "file"
    if kind == "leaf_symlink":
        target.symlink_to(tmp_path / "outside")
    elif kind == "parent_symlink":
        target.symlink_to(tmp_path, target_is_directory=True)
        relative = "file/outside"
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "directory":
        target.mkdir()
    else:
        target.write_bytes(b"payload")
        target.chmod({"setuid": 0o4600, "setgid": 0o2600, "sticky": 0o1600}[kind])
    with module.ProtectedRoot.open(trusted) as root:
        with pytest.raises(ValueError):
            root.read_regular(relative, max_bytes=32)


def test_open_root_remains_pinned_when_path_is_replaced(tmp_path: Path) -> None:
    module = api()
    original = tmp_path / "root"
    original.mkdir(mode=0o700)
    (original / "x").write_bytes(b"original")
    with module.ProtectedRoot.open(original) as root:
        original.rename(tmp_path / "retained")
        original.mkdir(mode=0o700)
        (original / "x").write_bytes(b"substituted")
        assert root.read_regular("x", max_bytes=32) == b"original"


def test_read_is_bounded_and_root_symlink_is_refused(tmp_path: Path) -> None:
    module = api()
    (tmp_path / "large").write_bytes(b"x" * 33)
    with module.ProtectedRoot.open(tmp_path) as root:
        with pytest.raises(ValueError):
            root.read_regular("large", max_bytes=32)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        module.ProtectedRoot.open(alias)
