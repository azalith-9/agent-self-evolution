"""Behavioral contracts for bounded execution and descendant cleanup.

Only synthetic Python children run here. Every child PID is recorded so the test
can clean it up even if the implementation fails its cleanup assertion.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest


def _request(tmp_path: Path, script: str, *, timeout: float = 2, required: bool = False) -> object:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest

    return ExecutionRequest(argv=[sys.executable, "-c", script], cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
                            policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                                                   network="deny", required=required),
                            timeout_seconds=timeout, cleanup_timeout_seconds=1,
                            invocation_id="process-a")


def _alive(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_capture_preserves_output_and_invocation_identity(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    result = run_process(_request(tmp_path, "import sys; print('answer'); print('detail', file=sys.stderr)"))
    assert (result.exit_code, result.stdout.strip(), result.stderr.strip()) == (0, "answer", "detail")
    assert result.invocation_id == "process-a"
    assert result.cleanup_complete and not result.timed_out


@pytest.mark.skipif(os.name != "posix", reason="POSIX descendant lifecycle")
@pytest.mark.parametrize("detached", [False, True], ids=["same-session", "new-session"])
@pytest.mark.parametrize("parent_exits", [False, True], ids=["timeout", "normal-exit"])
def test_execution_cleans_descendants_even_when_output_pipes_remain_open(tmp_path: Path, detached: bool, parent_exits: bool) -> None:
    from evolution.core.process import run_process

    marker = tmp_path / "descendant.pid"
    child_script = "import time; time.sleep(60)"
    parent = (
        "import subprocess,sys,time\n"
        "from pathlib import Path\n"
        f"child=subprocess.Popen([sys.executable,'-c',{child_script!r}],start_new_session={detached!r})\n"
        f"Path({str(marker)!r}).write_text(str(child.pid))\n"
        + ("sys.exit(0)\n" if parent_exits else "time.sleep(60)\n")
    )
    started = time.monotonic()
    try:
        result = run_process(_request(tmp_path, parent, timeout=0.5))
        assert time.monotonic() - started < 4
        assert result.cleanup_complete
        assert result.timed_out is (not parent_exits)
        assert marker.exists(), "synthetic descendant must start before asserting cleanup"
        assert not _alive(int(marker.read_text()))
    finally:
        if marker.exists():
            try:
                os.kill(int(marker.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_durable_diagnostics_redact_known_secrets(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    secret = "synthetic-sensitive-canary-123456"
    request = _request(tmp_path, f"import sys; print({secret!r},file=sys.stderr); sys.exit(1)")
    result = run_process(request, secrets=[secret])
    assert secret not in result.stderr
    assert result.exit_code == 1
    assert result.cleanup_complete


def test_launch_error_has_bounded_cleanup_and_no_raw_capture_leaks(tmp_path: Path) -> None:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest
    from evolution.core.process import run_process

    request = ExecutionRequest(argv=[str(tmp_path / "missing-binary")], cwd=tmp_path, env={},
                               policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                                                      network="deny", required=False),
                               timeout_seconds=1, cleanup_timeout_seconds=1,
                               invocation_id="launch-error")
    result = run_process(request)
    assert result.exit_code is None and result.error
    assert result.cleanup_complete
    assert list(tmp_path.iterdir()) == []
