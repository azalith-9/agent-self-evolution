"""Explicit independently provisioned Python runtimes; no ambient fallback."""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import weakref
from pathlib import Path
from types import MappingProxyType

from evolution.code import strict_json as js
from evolution.code.verification_contracts import digest, fields, text
from evolution.core.secure_paths import ProtectedRoot, validate_protection, metadata_identity

_RUNTIMES: weakref.WeakSet = weakref.WeakSet()


def runtime_manifest(roots: tuple[Path, ...]) -> list[dict]:
    """Inventory coherent bytes and metadata; resolution separately validates ancestry."""
    records = []
    total_bytes = 0
    for index, root in enumerate(roots):
        with ProtectedRoot.open(root) as pinned:
            pending = [('', metadata_identity(os.fstat(pinned.fd)))]
            retained = []
            try:
                while pending:
                    relative_parent, expected_directory = pending.pop()
                    if relative_parent:
                        parent_fd, leaf = pinned.parent(relative_parent)
                        try:
                            directory = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                                dir_fd=parent_fd)
                        finally:
                            os.close(parent_fd)
                    else:
                        directory = os.dup(pinned.fd)
                    try:
                        validate_protection(directory)
                        if metadata_identity(os.fstat(directory)) != expected_directory:
                            raise ValueError('runtime directory changed during traversal')
                        retained.append((os.dup(directory), expected_directory))
                        for name in sorted(os.listdir(directory)):
                            relative = relative_parent + '/' + name if relative_parent else name
                            observed = (root / relative).lstat()
                            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                                 dir_fd=directory)
                            try:
                                metadata = os.fstat(descriptor)
                                validate_protection(descriptor)
                                if metadata_identity(observed) != metadata_identity(metadata):
                                    raise ValueError('runtime entry changed during lookup')
                                if stat.S_ISDIR(metadata.st_mode):
                                    source_digest, kind = None, 'directory'
                                    pending.append((relative, metadata_identity(metadata)))
                                elif stat.S_ISREG(metadata.st_mode):
                                    payload, captured = pinned.read_snapshot(relative, max_bytes=67108864)
                                    if metadata_identity(captured) != metadata_identity(metadata):
                                        raise ValueError('runtime entry changed during capture')
                                    total_bytes += len(payload)
                                    if total_bytes > 268435456:
                                        raise ValueError('runtime exceeds supported storage bound')
                                    source_digest, kind = hashlib.sha256(payload).hexdigest(), 'file'
                                else:
                                    raise ValueError('special runtime entry')
                                retained.append((os.dup(descriptor), metadata_identity(metadata)))
                                records.append({'root_index': index, 'path': relative, 'kind': kind,
                                                'mode': stat.S_IMODE(metadata.st_mode), 'source_sha256': source_digest})
                                if len(records) > 2048:
                                    raise ValueError('runtime manifest exceeds supported population')
                            finally:
                                os.close(descriptor)
                    finally:
                        os.close(directory)
                for descriptor, expected in retained:
                    if metadata_identity(os.fstat(descriptor)) != expected:
                        raise ValueError('runtime changed during inventory')
            finally:
                for descriptor, _ in retained:
                    os.close(descriptor)
    return sorted(records, key=lambda row: (row['root_index'], row['path']))


class TrustedRuntime:
    def __init__(self) -> None:
        raise ValueError('verification_runtime_untrusted: resolve an explicit runtime')

    def current(self) -> bool:
        if self not in _RUNTIMES:
            return False
        try:
            return _load(self.config, self.key) == self._entry
        except ValueError:
            return False

    def close(self) -> None:
        _RUNTIMES.discard(self)


def _load(config: Path, key: str) -> dict:
    try:
        if not config.is_absolute() or sys.platform != 'linux':
            raise ValueError('supported Linux registry must be absolute')
        with ProtectedRoot.open(config.parent, require_protected=True) as pinned:
            info = os.fstat(pinned.fd)
            if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                raise ValueError('registry parent must be independently protected')
            fd = pinned.open_regular(config.name)
            try:
                meta = os.fstat(fd)
                validate_protection(fd)
                if meta.st_uid not in (0, os.getuid()) or meta.st_mode & 0o077 or meta.st_nlink != 1:
                    raise ValueError('registry must be private with a single link')
            finally:
                os.close(fd)
            document = js.loads(pinned.read_regular(config.name, max_bytes=1048576))
        fields(document, {'schema_version', 'runtimes'})
        if document['schema_version'] != '1' or type(document['runtimes']) is not dict:
            raise ValueError('unsupported runtime registry')
        entry = fields(document['runtimes'][key], {'interpreter', 'interpreter_sha256', 'runtime_roots',
            'runtime_manifest_sha256', 'backend', 'policy'})
        if entry['backend'] != 'bubblewrap' or entry['policy'] != 'python-json-command-v1':
            raise ValueError('unsupported verification backend or policy')
        interpreter = Path(text(entry['interpreter']))
        if not interpreter.is_absolute() or not interpreter.stat().st_mode & 0o111:
            raise ValueError('explicit executable required')
        roots = entry['runtime_roots']
        if type(roots) is not list or not 1 <= len(roots) <= 16 or len(set(roots)) != len(roots):
            raise ValueError('invalid runtime roots')
        paths = tuple(Path(text(root)) for root in roots)
        forbidden = {Path('/'), Path('/usr'), Path('/bin'), Path('/lib'), Path('/lib64'),
                     Path('/tmp'), Path('/home'), Path('/etc'), Path('/var'), Path('/proc'), Path('/dev')}
        for root in paths:
            if not root.is_absolute() or root in forbidden or root != Path(os.path.normpath(root)):
                raise ValueError('runtime needs a dedicated bundle, not broad host mounts')
            with ProtectedRoot.open(root, require_protected=True) as pinned:
                info = os.fstat(pinned.fd)
                if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o7022:
                    raise ValueError('runtime root is writable by other principals')
            if config.is_relative_to(root) or any(other != root and root.is_relative_to(other) for other in paths):
                raise ValueError('runtime roots overlap authority or one another')
        owner = next((root for root in paths if interpreter.is_relative_to(root)), None)
        if owner is None:
            raise ValueError('interpreter must be inside inventoried bundle')
        with ProtectedRoot.open(owner, require_protected=True) as pinned:
            payload = pinned.read_regular(interpreter.relative_to(owner).as_posix(), max_bytes=67108864)
        if hashlib.sha256(payload).hexdigest() != digest(entry['interpreter_sha256']):
            raise ValueError('interpreter digest mismatch')
        if hashlib.sha256(js.canonical_bytes(runtime_manifest(paths))).hexdigest() != digest(entry['runtime_manifest_sha256']):
            raise ValueError('runtime manifest mismatch')
        return entry
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('verification_runtime_untrusted: ' + str(exc)) from exc


def resolve_runtime(config: Path, *, runtime_id: str) -> TrustedRuntime:
    entry = _load(Path(config), runtime_id)
    runtime = object.__new__(TrustedRuntime)
    runtime.config, runtime.key = Path(config), runtime_id
    runtime._entry = entry
    runtime.entry = MappingProxyType(dict(entry, runtime_roots=tuple(entry['runtime_roots'])))
    runtime.runtime_id = js.identity('runtime', entry)
    _RUNTIMES.add(runtime)
    return runtime


def registered(runtime: object) -> bool:
    return type(runtime) is TrustedRuntime and runtime in _RUNTIMES
