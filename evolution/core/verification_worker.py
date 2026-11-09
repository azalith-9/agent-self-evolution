"""Trusted Linux launcher for a single-process, readonly Python command policy.

This file is executed by the private supervisor, outside candidate namespaces.
It exposes neither its source nor the source backing file to the candidate.
"""
from __future__ import annotations

import json
import os
import platform
import resource
import struct
import sys


def verification_filter(machine: str) -> bytes:
    """Deny process creation, sockets, tracing, signaling and namespace changes."""
    architectures = {
        'x86_64': (0xC000003E, [29, 30, 31, 41, 53, 56, 57, 58, 62, 67, 101, 155, 165, 166, 200, 234, 240,
                              246, 272, 298, 308, 310, 311, 319, 321, 425, 426, 427, 435, 438]),
        'aarch64': (0xC00000B7, [40, 39, 97, 98, 117, 129, 130, 131, 180, 194, 195, 196, 197, 198, 199, 220,
                               241, 268, 270, 271, 279, 280, 282, 425, 426, 427, 435, 438]),
    }
    if machine not in architectures:
        raise ValueError('unsupported verification syscall architecture')
    architecture, denied = architectures[machine]
    instructions = [(0x20, 0, 0, 4), (0x15, 1, 0, architecture),
                    (0x06, 0, 0, 0x80000000), (0x20, 0, 0, 0),
                    (0x35, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for number in denied:
        instructions += [(0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)]
    instructions.append((0x06, 0, 0, 0x7FFF0000))
    return b''.join(struct.pack('HBBI', *instruction) for instruction in instructions)


def main() -> None:
    document = json.loads(sys.argv[1])
    limits = document['limits']
    for key, value in ((resource.RLIMIT_CORE, 0), (resource.RLIMIT_AS, limits['memory_bytes']),
                       (resource.RLIMIT_CPU, limits['cpu_seconds']),
                       (resource.RLIMIT_NOFILE, 64)):
        resource.setrlimit(key, (value, value))
    source = os.memfd_create('candidate-source', flags=0)
    filter_fd = os.memfd_create('verification-filter', flags=0)
    try:
        with open(document['source'], 'rb') as stream:
            payload = stream.read(limits['source_bytes'] + 1)
        if len(payload) > limits['source_bytes']:
            raise ValueError('source exceeds execution bound')
        if os.write(source, payload) != len(payload):
            raise OSError('short snapshot write')
        program = verification_filter(platform.machine())
        if os.write(filter_fd, program) != len(program):
            raise OSError('short filter write')
        os.lseek(source, 0, os.SEEK_SET)
        os.lseek(filter_fd, 0, os.SEEK_SET)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits['scratch_bytes'], limits['scratch_bytes']))
        os.set_inheritable(source, True)
        os.set_inheritable(filter_fd, True)
        argv = [document['backend'], '--unshare-all', '--die-with-parent', '--new-session',
                '--cap-drop', 'ALL', '--clearenv', '--proc', '/proc', '--remount-ro', '/proc',
                '--dev', '/dev', '--remount-ro', '/dev', '--size', str(limits['scratch_bytes']),
                '--perms', '0777', '--tmpfs', '/scratch', '--ro-bind-data', str(source), '/candidate.py',
                '--seccomp', str(filter_fd), '--chdir', '/scratch', '--setenv', 'HOME', '/scratch',
                '--setenv', 'TMPDIR', '/scratch']
        for root in document['runtime_roots']:
            argv += ['--ro-bind', root, root]
        argv += ['--remount-ro', '/', '--', document['interpreter'], '-I', '-S', '-B', '/candidate.py']
        os.execv(document['backend'], argv)
    finally:
        os.close(source)
        os.close(filter_fd)


if __name__ == '__main__':
    main()
