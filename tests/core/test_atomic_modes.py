"""Atomic replacement preserves requested executable bits independently of umask."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from evolution.core.paths import write_contained


@pytest.mark.parametrize("existing,explicit,expected", [
    (0o755, None, 0o755), (None, 0o755, 0o755), (0o700, 0o644, 0o644),
    (None, None, 0o600),
], ids=["preserve", "new-executable", "explicit-precedence", "private-default"])
def test_final_mode_is_independent_of_restrictive_umask(
    tmp_path: Path, existing: int | None, explicit: int | None, expected: int,
) -> None:
    target = tmp_path / "tool"
    if existing is not None:
        target.write_bytes(b"old")
        target.chmod(existing)
    previous = os.umask(0o077)
    try:
        write_contained(tmp_path, "tool", b"verified bytes", mode=explicit)
        observed_umask = os.umask(0o077)
    finally:
        os.umask(previous)
    assert (target.read_bytes(), stat.S_IMODE(target.stat().st_mode), observed_umask) == (
        b"verified bytes", expected, 0o077,
    )


@pytest.mark.parametrize("mode", [True, -1, 0o4755, 0o100755])
def test_invalid_mode_does_not_replace_original(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "tool"
    target.write_bytes(b"original")
    with pytest.raises(ValueError):
        write_contained(tmp_path, "tool", b"untrusted", mode=mode)
    assert target.read_bytes() == b"original"


def test_mode_application_failure_leaves_original_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "tool"
    target.write_bytes(b"original")

    def denied(fd: int, mode: int) -> None:
        raise PermissionError("synthetic fchmod failure")

    monkeypatch.setattr(os, "fchmod", denied)
    with pytest.raises(PermissionError):
        write_contained(tmp_path, "tool", b"replacement", mode=0o755)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {"tool": b"original"}
