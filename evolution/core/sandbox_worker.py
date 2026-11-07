"""Install the Bubblewrap socket filter through a private inherited descriptor."""

from __future__ import annotations

import os
import platform
import struct
import sys


def socket_filter(machine: str) -> bytes:
    """Deny filesystem Unix sockets, including those inside explicitly mounted roots."""
    architectures = {"x86_64": (0xC000003E, 41), "aarch64": (0xC00000B7, 198)}
    if machine not in architectures:
        raise RuntimeError("socket containment requires a supported Linux syscall architecture")
    architecture, socket_number = architectures[machine]
    instructions = [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, architecture),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
        (0x35, 0, 1, 0x40000000),
        (0x06, 0, 0, 0x80000000),
        (0x15, 0, 3, socket_number),
        (0x20, 0, 0, 16),
        (0x15, 0, 1, 1),
        (0x06, 0, 0, 0x00050001),
        (0x06, 0, 0, 0x7FFF0000),
    ]
    return b"".join(struct.pack("HBBI", *instruction) for instruction in instructions)


def main() -> None:
    descriptor = os.memfd_create("execution-seccomp", flags=0)
    try:
        os.write(descriptor, socket_filter(platform.machine()))
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.set_inheritable(descriptor, True)
        os.execv(sys.argv[1], [sys.argv[1], "--seccomp", str(descriptor), *sys.argv[2:]])
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    main()
