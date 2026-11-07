"""Translate legacy command fixtures to the bounded execution seam."""
from __future__ import annotations

from typing import Callable

from evolution.core.execution import ExecutionRequest
from evolution.core.process import ProcessResult


def process_stub(command_stub: Callable) -> Callable:
    def run(request: ExecutionRequest, **kwargs: object) -> ProcessResult:
        completed = command_stub(list(request.argv), env=dict(request.env), cwd=str(request.cwd),
                                 timeout=request.timeout_seconds, check=False,
                                 capture_output=True, text=True)
        return ProcessResult(exit_code=completed.returncode, stdout=completed.stdout,
                             stderr=completed.stderr, timed_out=False, cleanup_complete=True,
                             invocation_id=request.invocation_id)
    return run
