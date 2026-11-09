"""Captured source is a retained resource, never a mutable pathname alias."""

from __future__ import annotations

import hashlib
import os
import copy
import pickle
from pathlib import Path

import pytest

from evolution.code.worktree import WorktreeEnv
from tests.code.verification_fixtures import SOURCE, TARGET, component


def environment(tmp_path: Path) -> WorktreeEnv:
    work = tmp_path / "candidate"
    (work / "tools").mkdir(parents=True)
    (work / TARGET).write_bytes(SOURCE)
    (work / TARGET).chmod(0o750)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    return WorktreeEnv(work, private, work, tmp_path / "venv", require_sandbox=False)


def test_capture_retains_exact_bytes_and_mode_after_source_replacement(tmp_path: Path) -> None:
    api = component("evolution.code.verified_snapshot")
    env = environment(tmp_path)
    with api.ProtectedSnapshot.capture(env, tool_relpath=TARGET) as snapshot:
        (env.worktree / TARGET).write_bytes(b"raise RuntimeError('substituted')\n")
        (env.worktree / TARGET).chmod(0o600)
        assert (snapshot.read_bytes(), snapshot.mode, snapshot.target, snapshot.source_sha256) == (
            SOURCE,
            0o750,
            TARGET,
            hashlib.sha256(SOURCE).hexdigest(),
        )


def test_snapshot_disposal_is_idempotent_and_prevents_reuse(tmp_path: Path) -> None:
    api = component("evolution.code.verified_snapshot")
    snapshot = api.ProtectedSnapshot.capture(environment(tmp_path), tool_relpath=TARGET)
    snapshot.close()
    snapshot.close()
    with pytest.raises(ValueError, match="verification_context_stale"):
        snapshot.read_bytes()


@pytest.mark.parametrize("mutation", ["symlink", "special_mode", "non_utf8", "oversized"])
def test_capture_rejects_unsupported_source_before_executing(tmp_path: Path, mutation: str) -> None:
    api = component("evolution.code.verified_snapshot")
    env = environment(tmp_path)
    target = env.worktree / TARGET
    if mutation == "symlink":
        other = tmp_path / "outside.py"
        other.write_bytes(SOURCE)
        target.unlink()
        target.symlink_to(other)
    elif mutation == "special_mode":
        target.chmod(0o4750)
    elif mutation == "non_utf8":
        target.write_bytes(b"\xff")
    elif mutation == "oversized":
        target.write_bytes(b"x" * 1048577)
    with pytest.raises(ValueError):
        api.ProtectedSnapshot.capture(env, tool_relpath=TARGET)


def test_mode_and_target_participate_in_snapshot_identity(tmp_path: Path) -> None:
    api = component("evolution.code.verified_snapshot")
    env = environment(tmp_path)
    (env.worktree / "tools/other.py").write_bytes(SOURCE)
    (env.worktree / "tools/other.py").chmod(0o750)
    with api.ProtectedSnapshot.capture(env, tool_relpath=TARGET) as first:
        (env.worktree / TARGET).chmod(0o700)
        with (
            api.ProtectedSnapshot.capture(env, tool_relpath=TARGET) as second,
            api.ProtectedSnapshot.capture(env, tool_relpath="tools/other.py") as third,
        ):
            assert len({first.snapshot_id, second.snapshot_id, third.snapshot_id}) == 3


@pytest.mark.parametrize('operation', [copy.copy, copy.deepcopy, pickle.dumps])
def test_snapshot_ownership_cannot_be_copied(tmp_path, operation):
    api = component('evolution.code.verified_snapshot')
    with api.ProtectedSnapshot.capture(environment(tmp_path), tool_relpath=TARGET) as snapshot:
        with pytest.raises(TypeError):
            operation(snapshot)


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires fork')
def test_inherited_snapshot_cannot_be_used_in_child_process(tmp_path):
    api = component('evolution.code.verified_snapshot')
    with api.ProtectedSnapshot.capture(environment(tmp_path), tool_relpath=TARGET) as snapshot:
        child = os.fork()
        if child == 0:
            try:
                if snapshot.current():
                    os._exit(2)
                snapshot.read_bytes()
            except ValueError:
                os._exit(0)
            except BaseException:
                os._exit(3)
            os._exit(4)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert snapshot.read_bytes() == SOURCE
