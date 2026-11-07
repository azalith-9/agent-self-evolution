"""Descriptor-relative contained I/O, rejecting symlink races at each component."""

from __future__ import annotations

import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def relative_parts(relative: str | Path) -> tuple[str, ...]:
    """Validate an untrusted relative path before touching the filesystem."""
    if not isinstance(relative, (str, Path)) or not str(relative) or "\0" in str(relative):
        raise ValueError("a nonempty relative path is required")
    path = Path(relative)
    if path.is_absolute() or any(p in {"..", "."} for p in str(relative).split("/")):
        raise ValueError("absolute paths and traversal are forbidden")
    if not path.parts:
        raise ValueError("a file path is required")
    return path.parts


def contained_relative(root: Path, path: Path | str) -> Path:
    """Convert an explicitly selected contained path to a validated relative name."""
    candidate = Path(path)
    if ".." in candidate.parts:
        raise ValueError("path traversal is forbidden")
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(root.absolute())
        except ValueError as exc:
            raise ValueError("selected path is outside its source root") from exc
    relative_parts(candidate)
    return candidate


@contextmanager
def _parent(root: Path, relative: str | Path, *, create: bool) -> Iterator[tuple[int, str]]:
    parts = relative_parts(relative)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root.resolve(strict=True), flags))
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptors[-1])
                except FileExistsError:
                    pass
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        yield descriptors[-1], parts[-1]
    except OSError as exc:
        if exc.errno in {20, 40}:
            raise ValueError("path contains a symlink or non-directory component") from exc
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def read_contained(root: Path, relative: str | Path) -> bytes:
    """Read a regular file without following any symlink below root."""
    with _parent(root, relative, create=False) as (directory, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise ValueError("contained source must be a regular file")
            return source.read()


def write_contained(root: Path, relative: str | Path, data: bytes, *, mode: int | None = None) -> None:
    """Atomically replace a regular file through a pinned parent descriptor."""
    if mode is not None and (type(mode) is not int or not 0 <= mode <= 0o777):
        raise ValueError("mode must contain only ordinary permission bits")
    with _parent(root, relative, create=True) as (directory, name):
        desired_mode = 0o600 if mode is None else mode
        try:
            existing = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError("contained destination must be a regular file, never a symlink")
            if mode is None:
                desired_mode = stat.S_IMODE(existing.st_mode)
        except FileNotFoundError:
            pass
        temporary = ".atomic-" + uuid.uuid4().hex
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as target:
                target.write(data)
                target.flush()
                if type(desired_mode) is not int or not 0 <= desired_mode <= 0o777:
                    raise ValueError("destination mode contains privileged permission bits")
                os.fchmod(target.fileno(), desired_mode)
                os.fsync(target.fileno())
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
