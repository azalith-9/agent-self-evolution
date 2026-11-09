"""Single-use local export from a retained, live-authorized snapshot."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from evolution.code.semantic_verifier import claim, consume
from evolution.core.secure_paths import ProtectedRoot


class ExportError(ValueError):
    def __init__(self, receipt: dict) -> None:
        super().__init__(receipt['reason'] + ': replacement=' + receipt['replacement'])
        self.receipt = receipt


def export_verified(authorization: object, *, destination_root: Path, target: str) -> dict:
    """Claim atomically, install exact bytes/mode, and consume even on failure."""
    record = claim(authorization, target=target, destination_root=Path(destination_root))
    snapshot = record['snapshot']
    receipt = {'schema_version': '2', 'status': 'failed', 'reason': 'export_destination_invalid',
        'assessment_id': record.get('audit_id'),
        'destination_id': record.get('destination_id'),
        'snapshot_id': snapshot.snapshot_id, 'target': snapshot.target,
        'source_sha256': snapshot.source_sha256, 'mode': snapshot.mode, 'replacement': 'not_replaced', 'phase': 'destination'}
    parent, temp = record.get('parent_fd', -1), None
    payload = record.get('payload')
    try:
        if payload is None:
            payload = snapshot.read_bytes()
        with ProtectedRoot(os.dup(parent)) if parent >= 0 else ProtectedRoot.open(Path(destination_root)) as root:
            if parent < 0:
                parent, leaf = root.parent(target)
                verify_target = target
            else:
                leaf = record['leaf']
                verify_target = leaf
            metadata = os.fstat(parent)
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
                raise ValueError('destination parent is not independently protected')
            try:
                os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                descriptor = root.open_regular(verify_target)
                os.close(descriptor)
            temp = '.verified-' + uuid.uuid4().hex
            descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            receipt['reason'] = 'export_io_failed'
            receipt['phase'] = 'write'
            with os.fdopen(descriptor, 'wb') as stream:
                if stream.write(payload) != len(payload):
                    raise OSError('short verified export write')
                stream.flush()
                os.fchmod(stream.fileno(), snapshot.mode)
                receipt['phase'] = 'file_sync'
                os.fsync(stream.fileno())
            receipt.update(phase='replace', replacement='replacement_unknown')
            os.replace(temp, leaf, src_dir_fd=parent, dst_dir_fd=parent)
            receipt.update(phase='directory_sync', replacement='replaced_durability_uncertain')
            os.fsync(parent)
            receipt['phase'] = 'verify'
            installed, mode = root.read_with_mode(verify_target, max_bytes=1048576)
            if installed != payload or mode != snapshot.mode:
                raise OSError('installed snapshot differs')
            receipt.update(status='succeeded', reason='export_completed',
                           replacement='replaced_durable', phase='complete')
            return receipt
    except (OSError, ValueError) as exc:
        raise ExportError(receipt) from exc
    except BaseException as exc:
        exc.export_receipt = dict(receipt)
        raise
    finally:
        try:
            if parent >= 0:
                try:
                    if temp:
                        try:
                            os.unlink(temp, dir_fd=parent)
                        except FileNotFoundError:
                            pass
                finally:
                    os.close(parent)
        finally:
            consume(authorization)
