"""Descriptor-relative regular-file access beneath a pinned directory."""
from __future__ import annotations

import os
import stat
from pathlib import Path


def relative_parts(target: str) -> tuple[str, ...]:
    if type(target) is not str or not target or '\0' in target or '\\' in target:
        raise ValueError("invalid relative path")
    parts = tuple(target.split('/'))
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError("path must be canonical and relative")
    return parts


def metadata_identity(info: os.stat_result) -> tuple:
    """Stable identity excludes access time, which a read may legitimately change."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def validate_protection(descriptor: int, *, sticky_ancestor: bool = False) -> None:
    """Conservatively refuse write-sharing and extended filesystem ACLs.

    A root-owned sticky ancestor permits traversal to an independently owned
    child, but is never itself accepted as protected runtime storage.
    """
    info = os.fstat(descriptor)
    sticky = sticky_ancestor and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
    if (info.st_uid not in (0, os.getuid()) or info.st_mode & 0o6000 or
            info.st_mode & 0o022 and not sticky):
        raise ValueError('unprotected ownership or writable ancestry')
    try:
        attributes = os.listxattr(descriptor)
    except OSError as exc:
        raise ValueError('filesystem ACL protection cannot be established') from exc
    if any(name in attributes for name in ('system.posix_acl_access', 'system.posix_acl_default')):
        raise ValueError('extended ACL protection is unsupported')


class ProtectedRoot:
    """Own a pinned directory descriptor; never follow candidate symlinks."""
    def __init__(self, descriptor: int) -> None:
        self.fd = descriptor

    @classmethod
    def open(cls, path: Path, *, require_protected: bool = False) -> ProtectedRoot:
        path = Path(path)
        if not path.is_absolute():
            raise ValueError("protected root must be absolute")
        descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if require_protected:
                validate_protection(descriptor)
            for index, part in enumerate(path.parts[1:]):
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_fd
                if require_protected:
                    validate_protection(descriptor, sticky_ancestor=index < len(path.parts) - 2)
            return cls(descriptor)
        except (OSError, ValueError) as exc:
            os.close(descriptor)
            raise ValueError("protected root is not a protected nonsymlink directory") from exc

    def parent(self, target: str) -> tuple[int, str]:
        parts = relative_parts(target)
        if self.fd < 0:
            raise ValueError("protected root is closed")
        descriptor = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_fd
            return descriptor, parts[-1]
        except OSError as exc:
            os.close(descriptor)
            raise ValueError("unsafe path component") from exc

    def open_regular(self, target: str, *, flags: int = os.O_RDONLY, mode: int = 0o600) -> int:
        parent, leaf = self.parent(target)
        try:
            descriptor = os.open(leaf, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                 mode, dir_fd=parent)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o7000:
                os.close(descriptor)
                raise ValueError("expected a regular file with ordinary permissions")
            return descriptor
        except OSError as exc:
            raise ValueError("regular file access refused") from exc
        finally:
            os.close(parent)

    def read_snapshot(self, target: str, *, max_bytes: int) -> tuple[bytes, os.stat_result]:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("invalid read bound")
        descriptor = self.open_regular(target)
        try:
            before = os.fstat(descriptor)
            if before.st_nlink != 1:
                raise ValueError("regular source must have exactly one link")
            if before.st_size > max_bytes:
                raise ValueError("file exceeds read bound")
            chunks, remaining = [], max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            result = b''.join(chunks)
            after = os.fstat(descriptor)
            if (len(result) > max_bytes or len(result) != after.st_size or
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode) !=
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode)):
                raise ValueError("file changed during bounded read")
            return result, after
        finally:
            os.close(descriptor)

    def read_with_mode(self, target: str, *, max_bytes: int) -> tuple[bytes, int]:
        payload, metadata = self.read_snapshot(target, max_bytes=max_bytes)
        return payload, stat.S_IMODE(metadata.st_mode)

    def read_regular(self, target: str, *, max_bytes: int) -> bytes:
        return self.read_with_mode(target, max_bytes=max_bytes)[0]

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> ProtectedRoot:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
