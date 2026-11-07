"""Contained I/O is a parent-process safety boundary, independent of OS sandboxing."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("escape", ["absolute", "parent", "symlink-file", "symlink-dir"])
def test_contained_io_never_accesses_outside_root(tmp_path: Path, operation: str, escape: str) -> None:
    from evolution.core.paths import read_contained, write_contained

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"original")
    (root / "linked-file").symlink_to(sentinel)
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    relative = {"absolute": str(sentinel), "parent": "../outside/sentinel",
                "symlink-file": "linked-file", "symlink-dir": "linked-dir/sentinel"}[escape]
    with pytest.raises(ValueError):
        if operation == "read":
            read_contained(root, relative)
        else:
            write_contained(root, relative, b"changed")
    assert sentinel.read_bytes() == b"original"


def test_contained_io_accepts_nested_unicode_paths(tmp_path: Path) -> None:
    from evolution.core.paths import read_contained, write_contained

    write_contained(tmp_path, "tools/é.py", b"payload")
    assert read_contained(tmp_path, "tools/é.py") == b"payload"


def test_write_failure_leaves_original_and_no_temporary_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolution.core.paths import write_contained

    target = tmp_path / "tool.py"
    target.write_bytes(b"original")

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("synthetic replace refusal")

    monkeypatch.setattr("os.replace", denied)
    with pytest.raises(PermissionError):
        write_contained(tmp_path, "tool.py", b"changed")
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {"tool.py": b"original"}
