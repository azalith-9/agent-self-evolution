"""Readonly Linux verification policy, separate from writable repair execution."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import weakref
import threading
from pathlib import Path

from evolution.core.process import ProcessResult
from evolution.core.sandbox import SandboxUnavailableError, sandbox_available


_LEASES: dict[int, tuple[weakref.ReferenceType, int, str]] = {}
_LEASE_LOCK = threading.RLock()


def _binding(*, source: bytes, interpreter: str, runtime_roots: tuple[str, ...],
             limits: dict, request_bytes: bytes) -> str:
    return hashlib.sha256(json.dumps({
        'source': hashlib.sha256(source).hexdigest(), 'interpreter': interpreter,
        'runtime_roots': runtime_roots, 'limits': limits,
        'request': hashlib.sha256(request_bytes).hexdigest(),
    }, sort_keys=True).encode()).hexdigest()


def enforcement_current(outcome: object, **inputs: object) -> bool:
    """Audit strings and reconstructed results never establish a launch lease."""
    with _LEASE_LOCK:
        lease = _LEASES.get(id(outcome))
        return bool(type(outcome) is ProcessResult and lease is not None and
                    lease[0]() is outcome and lease[1] == os.getpid() and
                    lease[2] == _binding(**inputs))


def _after_fork() -> None:
    global _LEASE_LOCK
    _LEASE_LOCK = threading.RLock()
    _LEASES.clear()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def backend_path() -> Path:
    """Only a host-admin-controlled backend is part of the trusted launcher."""
    backend = Path('/usr/bin/bwrap')
    try:
        info = backend.stat()
        if (sys.platform != 'linux' or info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or
                info.st_mode & 0o022 or not sandbox_available()):
            raise SandboxUnavailableError('verification_containment_unavailable')
    except OSError as exc:
        raise SandboxUnavailableError('verification_containment_unavailable') from exc
    return backend


def run_readonly_python(*, source: bytes, interpreter: str, runtime_roots: tuple[str, ...],
                        limits: dict, request_bytes: bytes, invocation_id: str | None = None) -> ProcessResult:
    """Refuse candidate entry until trusted setup can enforce and attest every bound.

    The retained worker is not a supported verifier: aggregate scratch metadata,
    independently observed setup and invocation-bound lease issuance are missing.
    """
    backend_path()
    raise SandboxUnavailableError(
        'verification_containment_unavailable: protected setup and aggregate scratch inode enforcement unavailable')
