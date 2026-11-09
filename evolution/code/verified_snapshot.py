"""Parent-owned retained bytes, independent of mutable candidate pathnames."""
from __future__ import annotations

import hashlib
import os
import threading
import weakref

from evolution.code.strict_json import identity
from evolution.core.secure_paths import ProtectedRoot, relative_parts

_REGISTERED: weakref.WeakSet = weakref.WeakSet()
_LOCK = threading.RLock()


class ProtectedSnapshot:
    """Capture bounded single-file source; close disposes its parent memory lease."""
    def __init__(self) -> None:
        raise ValueError('verification_context_stale: capture a snapshot')

    @classmethod
    def capture(cls, env: object, *, tool_relpath: str) -> ProtectedSnapshot:
        relative_parts(tool_relpath)
        if not tool_relpath.endswith('.py'):
            raise ValueError('unsupported source type')
        # Production WorktreeEnv tracks every execution generation and cleanup.
        if getattr(env, '_execution_active', False) or not getattr(env, '_execution_clean', True):
            raise ValueError('verification_cleanup_unconfirmed')
        with ProtectedRoot.open(env.worktree) as root:
            fd = root.open_regular(tool_relpath)
            try:
                if os.fstat(fd).st_nlink != 1:
                    raise ValueError("verification_context_stale: source has aliases")
            finally:
                os.close(fd)
            payload, mode = root.read_with_mode(tool_relpath, max_bytes=1048576)
        try:
            payload.decode('utf-8')
        except UnicodeError as exc:
            raise ValueError('unsupported source encoding') from exc
        result = object.__new__(cls)
        result._pid = os.getpid()
        result._bytes = payload
        result._mode = mode
        result._target = tool_relpath
        result._env = env
        result._generation = getattr(env, '_execution_generation', 0)
        result._source_sha256 = hashlib.sha256(payload).hexdigest()
        result._snapshot_id = identity('snapshot', {'target': tool_relpath, 'mode': mode,
                                                  'source_sha256': result._source_sha256})
        with _LOCK:
            _REGISTERED.add(result)
        return result

    def __copy__(self) -> object:
        raise TypeError('live snapshots cannot be copied')

    def __deepcopy__(self, memo: dict) -> object:
        raise TypeError('live snapshots cannot be copied')

    def __reduce__(self) -> object:
        raise TypeError('live snapshots cannot be serialized')

    @property
    def target(self) -> str:
        return self._target

    @property
    def mode(self) -> int:
        return self._mode

    @property
    def source_sha256(self) -> str:
        return self._source_sha256

    @property
    def snapshot_id(self) -> str:
        return self._snapshot_id

    def current(self) -> bool:
        if (not registered(self) or getattr(self._env, '_execution_active', False) or
                not getattr(self._env, '_execution_clean', True) or
                getattr(self._env, '_execution_generation', 0) != self._generation):
            return False
        try:
            with ProtectedRoot.open(self._env.worktree) as root:
                payload, mode = root.read_with_mode(self.target, max_bytes=1048576)
            return payload == self._bytes and mode == self.mode
        except ValueError:
            return False

    def read_bytes(self) -> bytes:
        if not registered(self):
            raise ValueError('verification_context_stale')
        return self._bytes

    def close(self) -> None:
        with _LOCK:
            _REGISTERED.discard(self)
            self._bytes = b''

    def __enter__(self) -> ProtectedSnapshot:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def registered(snapshot: object) -> bool:
    return (type(snapshot) is ProtectedSnapshot and snapshot in _REGISTERED and
            snapshot._pid == os.getpid())


def _after_fork() -> None:
    global _LOCK
    _LOCK = threading.RLock()
    _REGISTERED.clear()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)
