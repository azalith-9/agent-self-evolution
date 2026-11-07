"""Bounded file-backed subprocess execution with execution-wide cleanup evidence."""

from __future__ import annotations

import json
import math
import threading
import uuid
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from evolution.core.execution import ExecutionRequest, runtime_digest
from evolution.core.sandbox import wrap_argv


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    cleanup_complete: bool
    invocation_id: str
    error: str | None = None
    sandboxed: bool = False


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove known credential values before diagnostic persistence."""
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


_CONSUMED: set[tuple[Path, str]] = set()
_REQUEST_LOCK = threading.Lock()
_RECEIPT_FIELDS = {
    "schema_version", "invocation_id", "policy_id", "runtime_id", "snapshot_id", "scope_id",
    "launched", "exit_code", "timed_out", "cancelled", "duration_seconds", "capture_complete",
    "containment", "cleanup_complete", "error",
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate receipt field")
        result[key] = value
    return result


def _validate_receipt(evidence: object, expected: dict, supervisor_exit: int) -> dict:
    """Check process observations against this parent's single-use invocation."""
    if supervisor_exit != 0 or not isinstance(evidence, dict) or set(evidence) != _RECEIPT_FIELDS:
        raise ValueError("invalid supervisor completion")
    containment = evidence["containment"]
    if not isinstance(containment, dict) or set(containment) != set(expected["containment"]):
        raise ValueError("invalid containment fields")
    if not isinstance(containment["backend"], str) or any(
        type(value) is not bool for key, value in containment.items() if key != "backend"
    ):
        raise ValueError("invalid containment types")
    for key, value in expected.items():
        if evidence[key] != value or type(evidence[key]) is not type(value):
            raise ValueError("supervisor binding mismatch")
    for key in ("launched", "timed_out", "cancelled", "capture_complete", "cleanup_complete"):
        if type(evidence[key]) is not bool:
            raise ValueError("invalid supervisor Boolean field")
    exit_code = evidence["exit_code"]
    if exit_code is not None and type(exit_code) is not int:
        raise ValueError("invalid supervisor exit status")
    duration = evidence["duration_seconds"]
    if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
        raise ValueError("invalid supervisor duration")
    if evidence["error"] is not None and not isinstance(evidence["error"], str):
        raise ValueError("invalid supervisor error")
    if not evidence["launched"] and (exit_code is not None or evidence["timed_out"]):
        raise ValueError("contradictory launch evidence")
    if not evidence["launched"] and not evidence["error"]:
        raise ValueError("missing launch failure")
    if evidence["launched"] and exit_code is None and not (evidence["error"] or evidence["timed_out"] or evidence["cancelled"]):
        raise ValueError("missing execution outcome")
    if evidence["cancelled"]:
        raise ValueError("execution was cancelled")
    if not evidence["capture_complete"]:
        raise ValueError("incomplete process capture")
    if evidence["cleanup_complete"] and not evidence["containment"]["descendant_cleanup_certified"]:
        raise ValueError("uncertified cleanup")
    return evidence


def run_process(request: ExecutionRequest, *, secrets: Iterable[str] = ()) -> ProcessResult:
    """Run a request once; receipts establish process facts, never test authority."""
    def refused(reason: str, *, no_launch: bool = False) -> ProcessResult:
        return ProcessResult(None, "", "", False, no_launch, request.invocation_id, error=reason)

    with _REQUEST_LOCK:
        key = (request.cwd, request.invocation_id)
        if key in _CONSUMED:
            return refused("execution invocation already consumed in this scope")
        _CONSUMED.add(key)
    if request._runtime is None:
        return refused("execution has no selected executable", no_launch=True)
    if request._runtime is not None:
        try:
            if runtime_digest(Path(request._runtime[0])) != request._runtime[1]:
                return refused("selected executable changed after request preparation")
        except OSError:
            return refused("selected executable is unavailable")
    selected_secrets = tuple(secrets) + tuple(value for key, value in request.env.items()
        if any(part in key.upper() for part in ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL")))
    argv, sandboxed = (wrap_argv(list(request.argv), write_roots=list(request.policy.write_roots),
                               read_roots=list(request.policy.read_roots),
                               network=request.policy.network, require=True)
                        if request.policy.required else (list(request.argv), False))
    containment = dict(backend=("linux" if sys.platform.startswith("linux") else "macos") if sandboxed else "unconfined",
                       read_isolated=sandboxed, write_confined=sandboxed,
                       network_isolated=sandboxed and request.policy.network == "deny",
                       descendant_cleanup_certified=sys.platform.startswith("linux"))
    bindings = dict(schema_version="1", invocation_id=request.invocation_id,
                    policy_id=uuid.uuid4().hex, runtime_id=uuid.uuid4().hex,
                    snapshot_id=uuid.uuid4().hex, scope_id=uuid.uuid4().hex,
                    containment=containment)
    payload = dict(argv=argv, cwd=str(request.cwd), env=dict(request.env),
                   timeout_seconds=request.timeout_seconds,
                   cleanup_timeout_seconds=request.cleanup_timeout_seconds,
                   pid_namespace=sandboxed and sys.platform.startswith("linux"),
                   bindings=bindings)
    with tempfile.TemporaryDirectory(prefix="ase-process-") as directory:
        root = Path(directory)
        with (root / "stdout").open("w+b") as stdout, (root / "stderr").open("w+b") as stderr, \
                (root / "status").open("w+b") as status:
            supervisor = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("process_worker.py")), str(status.fileno())],
                stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, pass_fds=(status.fileno(),),
                start_new_session=True, env={"PATH": os.defpath})
            bound = request.timeout_seconds + request.cleanup_timeout_seconds + 2
            try:
                supervisor.communicate(json.dumps(payload).encode(), timeout=bound)
            except BaseException:
                if supervisor.poll() is None:
                    supervisor.send_signal(signal.SIGTERM)
                try:
                    supervisor.wait(timeout=request.cleanup_timeout_seconds + 0.5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(supervisor.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    supervisor.wait(timeout=0.5)
                raise
            status.seek(0)
            try:
                evidence = _validate_receipt(json.load(status, object_pairs_hook=_unique_object),
                                             bindings, supervisor.returncode)
            except (ValueError, UnicodeError, KeyError, TypeError):
                evidence = dict(exit_code=None, timed_out=False, cleanup_complete=False,
                                error="execution supervisor produced invalid or unbound completion evidence")
            stdout.seek(0)
            stderr.seek(0)
            return ProcessResult(
                exit_code=evidence["exit_code"], stdout=redact(stdout.read().decode(errors="replace"), selected_secrets),
                stderr=redact(stderr.read().decode(errors="replace"), selected_secrets),
                timed_out=evidence["timed_out"], cleanup_complete=evidence["cleanup_complete"],
                invocation_id=request.invocation_id,
                error=redact(evidence["error"], selected_secrets) if evidence["error"] else None,
                sandboxed=sandboxed)
