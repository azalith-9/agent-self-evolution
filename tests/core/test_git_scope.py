"""Checked, NUL-delimited Git status is required before trusting a code gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_failed_scope_inspection_is_explicit(tmp_path: Path) -> None:
    from evolution.core.git_scope import inspect_scope

    result = inspect_scope(tmp_path, invocation_id="scope-a")
    assert result.ok is False
    assert result.invocation_id == "scope-a"
    assert result.error


def test_nul_status_preserves_unusual_names_and_both_rename_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolution.core.git_scope import inspect_scope

    def status(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert "-z" in argv
        return subprocess.CompletedProcess(argv, 0,
            b"R  tools/new name.py\0tests/old\nname.py\0?? tools/quote\".py\0", b"")

    monkeypatch.setattr(subprocess, "run", status)
    result = inspect_scope(tmp_path, invocation_id="scope-b")
    assert result.ok is True
    assert set(result.paths) == {"tools/new name.py", "tests/old\nname.py", 'tools/quote".py'}


def test_scope_command_failure_never_returns_verified_empty_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolution.core.git_scope import inspect_scope

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 128, b"", b"fatal: index unavailable"))
    result = inspect_scope(tmp_path, invocation_id="scope-c")
    assert result.ok is False
    assert "index unavailable" in result.error
