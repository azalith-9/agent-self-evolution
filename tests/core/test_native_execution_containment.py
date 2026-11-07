"""Optional native checks use synthetic files and sockets, never real credentials.

Unsupported native containment is an explicit skip, not claimed as passing.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest


def _run_confined(tmp_path: Path, script: str) -> object:
    from evolution.core.sandbox import SandboxUnavailableError, sandbox_available

    if not sandbox_available():
        pytest.skip("native sandbox capabilities unavailable")
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest
    from evolution.core.process import run_process

    workspace = tmp_path / "work"
    workspace.mkdir(exist_ok=True)
    runtime = [Path(sys.executable).resolve().parent.parent,
               *(Path(p) for p in ("/usr", "/bin", "/lib", "/lib64") if Path(p).exists())]
    request = ExecutionRequest(argv=[str(Path(sys.executable).resolve()), "-c", script], cwd=workspace,
                               env={"PATH": os.defpath, "HOME": str(workspace), "TMPDIR": str(workspace)},
                               policy=ExecutionPolicy(read_roots=[workspace, *runtime], write_roots=[workspace],
                                                      network="deny", required=True),
                               timeout_seconds=3, cleanup_timeout_seconds=1,
                               invocation_id="native-a")
    try:
        return run_process(request)
    except SandboxUnavailableError as exc:
        pytest.skip(f"native policy unavailable: {exc}")


def test_native_policy_denies_unlisted_reads_and_writes(tmp_path: Path) -> None:
    outside = tmp_path / "private"
    outside.mkdir()
    canary = outside / "canary"
    canary.write_text("synthetic-canary")
    script = f'''from pathlib import Path
import json
result = {{}}
for action in ('read', 'write'):
    try:
        p = Path({str(canary)!r})
        p.read_text() if action == 'read' else p.write_text('changed')
        result[action] = 'allowed'
    except OSError:
        result[action] = 'denied'
Path('allowed').write_text('inside')
print(json.dumps(result))
'''
    result = _run_confined(tmp_path, script)
    assert result.exit_code == 0 and result.cleanup_complete
    assert json.loads(result.stdout) == {"read": "denied", "write": "denied"}
    assert canary.read_text() == "synthetic-canary"
    assert (tmp_path / "work/allowed").read_text() == "inside"


def test_native_policy_cannot_reach_host_loopback(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        script = f'''import socket
s=socket.socket()
s.settimeout(0.5)
try:
    s.connect(('127.0.0.1', {port}))
except OSError:
    print('denied')
else:
    print('allowed')
finally:
    s.close()
'''
        result = _run_confined(tmp_path, script)
    assert result.exit_code == 0
    assert result.stdout.strip() == "denied"


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix domain sockets")
def test_native_policy_cannot_reach_unlisted_host_socket(tmp_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ase-socket-", dir="/tmp") as directory, \
            socket.socket(socket.AF_UNIX) as listener:
        path = Path(directory) / "host.sock"
        listener.bind(str(path))
        listener.listen(1)
        script = f'''import socket
s=socket.socket(socket.AF_UNIX)
s.settimeout(0.5)
try:
    s.connect({str(path)!r})
except OSError:
    print('denied')
else:
    print('allowed')
finally:
    s.close()
'''
        result = _run_confined(tmp_path, script)
    assert result.exit_code == 0
    assert result.stdout.strip() == "denied"
