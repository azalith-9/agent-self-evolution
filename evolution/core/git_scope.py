"""Checked NUL-delimited Git scope inspection."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScopeResult:
    ok: bool
    paths: tuple[str, ...]
    error: str | None
    invocation_id: str


def inspect_scope(root: Path, *, invocation_id: str) -> ScopeResult:
    """Keep both rename endpoints and reject failed or malformed inspections."""
    try:
        result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                                 "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                cwd=root, capture_output=True, timeout=15,
                                env={"PATH": os.defpath, "HOME": "/nonexistent",
                                     "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
        if result.returncode:
            error = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else result.stderr
            return ScopeResult(False, (), error or f"git exited {result.returncode}", invocation_id)
        raw = result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()
        if raw and not raw.endswith(b"\0"):
            raise ValueError("truncated NUL-delimited Git status")
        records = iter(raw.split(b"\0")[:-1])
        paths = []
        for record in records:
            if len(record) < 4 or record[2:3] != b" ":
                raise ValueError("malformed Git status record")
            paths.append(os.fsdecode(record[3:]))
            if b"R" in record[:2] or b"C" in record[:2]:
                paths.append(os.fsdecode(next(records)))
        return ScopeResult(True, tuple(paths), None, invocation_id)
    except (OSError, subprocess.SubprocessError, ValueError, StopIteration) as exc:
        return ScopeResult(False, (), f"Git scope inspection failed: {exc}", invocation_id)
