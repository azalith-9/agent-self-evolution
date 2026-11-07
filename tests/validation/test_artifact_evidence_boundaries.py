"""Drift and active-run locks must be checked before acting on live artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.validation.task import Task, TaskSuite
from evolution.validation.validator import (
    ChecksumDriftError,
    ClosedLoopValidator,
    ConcurrentRunError,
    ValidationInputs,
    _exclusive_lock,
)


def test_installed_checksum_is_verified_before_agent_task(tmp_path: Path) -> None:
    target = tmp_path / "prompt.txt"
    target.write_text("original")
    artifact = tmp_path / "candidate.txt"
    artifact.write_text("candidate")
    expected = hashlib.sha256(b"candidate").hexdigest()

    def corrupt_after_install(source: Path) -> str:
        target.write_text("unexpected drift")
        return expected

    installer = SimpleNamespace(target_path=target, install=corrupt_after_install,
                                verify_backup=lambda path: None)
    runner = SimpleNamespace(run=Mock(side_effect=AssertionError("agent saw unchecked artifact")))
    validator = ClosedLoopValidator(installer, runner)
    suite = TaskSuite(tmp_path / "suite.jsonl", "sha", (Task("t", "m"),))
    with pytest.raises(ChecksumDriftError):
        validator.validate(ValidationInputs("prompt", suite, artifact, artifact))
    runner.run.assert_not_called()
    assert target.read_text() == "original"


def test_active_validation_lock_outranks_stale_backup_warning(tmp_path: Path) -> None:
    target = tmp_path / "prompt.txt"
    target.write_text("active")
    backup = tmp_path / "prompt.txt.cl_backup"
    backup.write_text("preserved")
    verify = Mock()
    installer = SimpleNamespace(target_path=target, verify_backup=verify)
    validator = ClosedLoopValidator(installer, SimpleNamespace(run=Mock()))
    suite = TaskSuite(tmp_path / "suite.jsonl", "sha", (Task("t", "m"),))
    with _exclusive_lock(tmp_path):
        with pytest.raises(ConcurrentRunError):
            validator.validate(ValidationInputs("prompt", suite, target, target))
    verify.assert_not_called()
    assert (target.read_text(), backup.read_text()) == ("active", "preserved")
