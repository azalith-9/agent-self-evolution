"""Credential-free transport checks; these do not certify native containment."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

from evolution.core.execution import ExecutionPolicy, ExecutionRequest
from evolution.core.process import run_process


def request(tmp_path: Path, script: str, **changes: object) -> ExecutionRequest:
    arguments = dict(
        argv=[sys.executable, "-I", "-S", "-B", "-c", script],
        cwd=tmp_path,
        env={},
        policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path], required=False),
        timeout_seconds=1,
        cleanup_timeout_seconds=1,
        invocation_id="transport-test",
        stdin_bytes=b"",
        max_stdout_bytes=4096,
        max_stderr_bytes=4096,
    )
    arguments.update(changes)
    return ExecutionRequest(**arguments)


def test_stdin_delivery_preserves_binary_data_and_does_not_append_newline(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 256
    outcome = run_process(
        request(
            tmp_path,
            "import base64,sys; print(base64.b64encode(sys.stdin.buffer.read()).decode())",
            stdin_bytes=payload,
            max_stdout_bytes=100000,
        )
    )
    assert outcome.exit_code == 0 and outcome.stdin_complete and outcome.capture_complete
    assert base64.b64decode(outcome.stdout.strip()) == payload


def test_stdout_and_stderr_are_drained_concurrently_under_separate_bounds(tmp_path: Path) -> None:
    outcome = run_process(
        request(tmp_path, "import os; os.write(1,b'x'*131072); os.write(2,b'y'*131072)")
    )
    assert len(outcome.stdout.encode()) <= 4096
    assert len(outcome.stderr.encode()) <= 4096
    assert outcome.capture_complete is False
    assert outcome.cleanup_complete is True


def test_early_stdin_close_is_incomplete_not_successful_empty_delivery(tmp_path: Path) -> None:
    outcome = run_process(
        request(tmp_path, "import os; os.close(0)", stdin_bytes=b"x" * (2 * 1024 * 1024))
    )
    assert outcome.stdin_complete is False
    assert outcome.cleanup_complete is True


@pytest.mark.parametrize(
    "field,value",
    [("max_stdout_bytes", True), ("max_stderr_bytes", 0), ("stdin_bytes", "text-instead-of-bytes")],
)
def test_invalid_transport_bounds_reject_at_construction(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        request(tmp_path, "pass", **{field: value})


def test_stdin_backpressure_is_included_in_deadline(tmp_path: Path) -> None:
    outcome = run_process(
        request(tmp_path, "import time; time.sleep(10)", stdin_bytes=b"x" * (2 * 1024 * 1024))
    )
    assert outcome.timed_out and outcome.cleanup_complete
    assert outcome.stdin_complete is False
