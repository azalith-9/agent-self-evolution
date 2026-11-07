"""Binary discovery alone cannot establish enforceable containment."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.core.sandbox import sandbox_available


def test_installed_but_unusable_sandbox_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evolution.core.sandbox.sys.platform", "darwin")
    monkeypatch.setattr("evolution.core.sandbox.shutil.which", lambda name: "/synthetic/sandbox-exec")
    monkeypatch.setattr(subprocess, "run", Mock(return_value=
                        subprocess.CompletedProcess([], 1, "", "sandbox initialization denied")))
    assert sandbox_available() is False


def test_required_containment_refuses_before_candidate_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest
    from evolution.core.process import run_process
    from evolution.core.sandbox import SandboxUnavailableError

    monkeypatch.setattr("evolution.core.sandbox.sandbox_available", lambda: False)
    marker = tmp_path / "must-not-exist"
    request = ExecutionRequest(argv=["/bin/sh", "-c", 'printf invoked > "$1"', "sh", str(marker)],
                               cwd=tmp_path, env={},
                               policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                                                      network="deny", required=True),
                               timeout_seconds=1, cleanup_timeout_seconds=1,
                               invocation_id="refusal")
    with pytest.raises(SandboxUnavailableError):
        run_process(request)
    assert not marker.exists()
