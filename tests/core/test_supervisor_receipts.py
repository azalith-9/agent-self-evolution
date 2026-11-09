"""Malformed, stale or unsuccessful supervisor observations cannot report success."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.core.execution import ExecutionPolicy, ExecutionRequest
from evolution.core.process import run_process


def receipt() -> dict:
    return dict(
        schema_version="1", invocation_id="receipt-request", policy_id="unregistered-policy",
        runtime_id="unregistered-runtime", snapshot_id="unregistered-snapshot",
        scope_id="unregistered-scope", launched=True, exit_code=0, timed_out=False,
        cancelled=False, duration_seconds=0.01, capture_complete=True, stdin_complete=True,
        containment=dict(backend="unconfined", read_isolated=False, write_confined=False,
                         network_isolated=False, descendant_cleanup_certified=True),
        cleanup_complete=True, error=None,
    )


@pytest.mark.parametrize("defect", [
    "unregistered-bindings", "legacy", "stale-invocation", "boolean-exit", "unknown-key",
    "missing-key", "duplicate-key", "contradictory-launch", "unknown-cleanup",
    "failed-supervisor", "nonfinite-duration", "invalid-containment",
])
def test_invalid_receipt_cannot_certify_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    evidence = receipt()
    if defect == "legacy":
        evidence = {k: evidence[k] for k in ("exit_code", "timed_out", "cleanup_complete", "error")}
    elif defect == "stale-invocation":
        evidence["invocation_id"] = "previous-request"
    elif defect == "boolean-exit":
        evidence["exit_code"] = False
    elif defect == "unknown-key":
        evidence["deployment_authorized"] = True
    elif defect == "missing-key":
        del evidence["exit_code"]
    elif defect == "contradictory-launch":
        evidence["launched"] = False
    elif defect == "unknown-cleanup":
        evidence["cleanup_complete"] = None
    elif defect == "nonfinite-duration":
        evidence["duration_seconds"] = float("nan")
    elif defect == "invalid-containment":
        evidence["containment"]["read_isolated"] = True
    raw = json.dumps(evidence)
    if defect == "duplicate-key":
        raw = raw[:-1] + ', "cleanup_complete": true}'

    def launch(argv: list[str], **kwargs: object) -> Mock:
        supervisor = Mock(returncode=9 if defect == "failed-supervisor" else 0)
        supervisor.poll.return_value = supervisor.returncode

        def communicate(payload: bytes, timeout: float) -> tuple[None, None]:
            os.write(int(argv[-1]), raw.encode())
            return None, None

        supervisor.communicate.side_effect = communicate
        return supervisor

    monkeypatch.setattr("evolution.core.process.subprocess.Popen", launch)
    result = run_process(ExecutionRequest(
        argv=[sys.executable, "-c", "pass"], cwd=tmp_path, env={},
        policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path], required=False),
        timeout_seconds=1, cleanup_timeout_seconds=1, invocation_id="receipt-request",
    ))
    assert result.error and result.cleanup_complete is not True
