"""Parent-interpreted semantic checks across an OS-protected command boundary."""
from __future__ import annotations

import dataclasses
import hashlib
import os
import threading
import uuid
import weakref
from dataclasses import dataclass
from pathlib import Path

from evolution.code import strict_json as js
from evolution.code.verification_contracts import SemanticSpec, load_semantic_spec
from evolution.code.verification_runtime import resolve_runtime, registered as runtime_registered
from evolution.code.verified_snapshot import ProtectedSnapshot, registered as snapshot_registered
from evolution.core.protected_execution import run_readonly_python, enforcement_current
from evolution.core.sandbox import SandboxUnavailableError
from evolution.core.secure_paths import ProtectedRoot

_CONTEXTS: weakref.WeakSet = weakref.WeakSet()
_PREREQUISITES: weakref.WeakSet = weakref.WeakSet()
_AUTHORIZATIONS: dict[object, dict] = {}
_AUTH_LOCK = threading.RLock()
_ASSESSMENTS: dict[int, tuple[weakref.ReferenceType, object]] = {}


class VerificationContext:
    """Explicit configuration lease. Persisted descriptions cannot recreate authority."""
    @classmethod
    def prepare(cls, *, spec_path: Path, runtime_config: Path, runtime_id: str,
                export_root: Path | None = None) -> VerificationContext:
        spec = load_semantic_spec(spec_path)
        if spec.runtime_id != runtime_id:
            raise ValueError('verification_runtime_untrusted: runtime key mismatch')
        runtime = resolve_runtime(runtime_config, runtime_id=runtime_id)
        self = cls()
        self.spec, self.runtime, self.spec_path = spec, runtime, Path(spec_path)
        self._pid = os.getpid()
        self._destination = None
        self._parent_fd = -1
        self.export_root = Path(export_root).absolute() if export_root is not None else None
        if self.export_root is not None:
            try:
                self._destination = ProtectedRoot.open(self.export_root)
                info = os.fstat(self._destination.fd)
                if info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ValueError('export_destination_invalid: unprotected root')
                self._destination_identity = (info.st_dev, info.st_ino)
                self._parent_fd, self._leaf = self._destination.parent(spec.baseline['target'])
                parent_info = os.fstat(self._parent_fd)
                if parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o022:
                    raise ValueError('export_destination_invalid: unprotected target parent')
                self._parent_identity = (parent_info.st_dev, parent_info.st_ino)
            except BaseException:
                self.close()
                raise
        _CONTEXTS.add(self)
        return self

    def current(self) -> bool:
        try:
            return (self in _CONTEXTS and getattr(self, "_pid", None) == os.getpid() and
                    self._destination_current() and self.runtime.current() and
                    load_semantic_spec(self.spec_path) == self.spec)
        except ValueError:
            return False

    def _destination_current(self) -> bool:
        if self.export_root is None:
            return True
        try:
            with ProtectedRoot.open(self.export_root) as root:
                info = os.fstat(root.fd)
                parent, _ = root.parent(self.spec.baseline['target'])
                try:
                    parent_info = os.fstat(parent)
                    return ((info.st_dev, info.st_ino) == self._destination_identity and
                            info.st_uid == os.getuid() and not info.st_mode & 0o022 and
                            (parent_info.st_dev, parent_info.st_ino) == self._parent_identity and
                            parent_info.st_uid == os.getuid() and not parent_info.st_mode & 0o022)
                finally:
                    os.close(parent)
        except ValueError:
            return False

    def close(self) -> None:
        with _AUTH_LOCK:
            for handle, record in list(_AUTHORIZATIONS.items()):
                if record['context'] is self:
                    revoke(handle)
            _CONTEXTS.discard(self)
            if getattr(self, '_parent_fd', -1) >= 0:
                os.close(self._parent_fd)
                self._parent_fd = -1
            if getattr(self, '_destination', None) is not None:
                self._destination.close()
            if hasattr(self, 'runtime'):
                self.runtime.close()

    def __enter__(self) -> VerificationContext:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class _Prerequisites:
    pass


def _gate_prerequisites(snapshot: ProtectedSnapshot, *, base_source: str,
                        decision: dict, context: VerificationContext) -> _Prerequisites:
    """Refuse authority until every selected retained-byte prerequisite has a protected evaluator.

    Scope and surface checks on retained bytes can reject a candidate, but cannot
    replace protected replay of oracle, holdout, regression or benchmark work.
    Mutable diagnostic decisions therefore never create prerequisite capabilities.
    """
    raise ValueError('verification_prerequisites_unavailable: protected retained-byte replay required')


@dataclass(frozen=True)
class SemanticAssessment:
    status: str
    reason: str
    audit: dict
    @property
    def authorization(self) -> object | None:
        owned = _ASSESSMENTS.get(id(self))
        return owned[1] if owned is not None and owned[0]() is self else None

    @property
    def summary(self) -> dict[str, str]:
        return {'schema_version': '1', 'status': self.status, 'reason': self.reason}


class _Authorization:
    def __reduce__(self) -> object:
        raise TypeError('export authority cannot be serialized')

    def __copy__(self) -> object:
        raise TypeError('export authority cannot be copied')

    def __deepcopy__(self, memo: dict) -> object:
        raise TypeError('export authority cannot be copied')


def revoke(authorization: object) -> None:
    with _AUTH_LOCK:
        record = _AUTHORIZATIONS.get(authorization)
        if record is not None and record['state'] == 'issued':
            record['state'] = 'consumed'
            record['snapshot'].close()
            del _AUTHORIZATIONS[authorization]
            for key, (_, handle) in list(_ASSESSMENTS.items()):
                if handle is authorization:
                    del _ASSESSMENTS[key]


def claim(authorization: object, *, target: str, destination_root: Path | None = None) -> dict:
    with _AUTH_LOCK:
        try:
            record = _AUTHORIZATIONS.get(authorization)
        except TypeError:
            record = None
        if (type(authorization) is not _Authorization or record is None or record['state'] != 'issued' or
                record.get('pid') != os.getpid()):
            raise ValueError('export_authorization_invalid')
        # Every identified claim is single use, including a stale or wrong-target attempt.
        record['state'] = 'exporting'
        if (destination_root is None or Path(destination_root).absolute() != record['context'].export_root or
                target != record['snapshot'].target or not record['snapshot'].current() or
                not record['context'].current()):
            record['state'] = 'consumed'
            record['snapshot'].close()
            del _AUTHORIZATIONS[authorization]
            raise ValueError('export_authorization_invalid: verification_context_stale')
        parent = -1
        try:
            context = record['context']
            parent, leaf = os.dup(context._parent_fd), context._leaf
            metadata = os.fstat(parent)
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
                raise ValueError('export_destination_invalid: unsafe parent')
            payload = record['snapshot'].read_bytes()
            claimed = dict(record, parent_fd=parent, leaf=leaf, payload=payload,
                           destination_id=record['destination_id'])
        except BaseException:
            if parent >= 0:
                os.close(parent)
            consume(authorization)
            raise
        return claimed


def consume(authorization: object) -> None:
    with _AUTH_LOCK:
        record = _AUTHORIZATIONS.pop(authorization, None)
        for key, (_, handle) in list(_ASSESSMENTS.items()):
            if handle is authorization:
                del _ASSESSMENTS[key]
        if record is not None:
            record['state'] = 'consumed'
            record['snapshot'].close()


class SemanticVerifier:
    """No child-produced record or cooperative pytest result is semantic authority."""
    def assess(self, snapshot: object, *, spec: object, runtime: object,
               prerequisites: object) -> SemanticAssessment:
        audit = {'schema_version': '2', 'status': 'unverifiable', 'reason': 'verification_evidence_invalid',
            'baseline': None, 'snapshot_id': None, 'specification_id': None, 'runtime_id': None,
            'policy_id': None, 'prerequisite_id': None, 'required_case_ids': [], 'cases': []}

        def finish(status: str, reason: str, authorization: object = None) -> SemanticAssessment:
            audit.update(status=status, reason=reason)
            assessment = SemanticAssessment(status, reason, dict(audit))
            if authorization is not None:
                key = id(assessment)
                _ASSESSMENTS[key] = (weakref.ref(assessment, lambda ref: _ASSESSMENTS.pop(key, None)), authorization)
            return assessment

        if (not snapshot_registered(snapshot) or type(spec) is not SemanticSpec or
                not runtime_registered(runtime) or type(prerequisites) is not _Prerequisites or
                prerequisites not in _PREREQUISITES or prerequisites.snapshot is not snapshot or
                prerequisites.context.spec is not spec or prerequisites.context.runtime is not runtime):
            return finish('unverifiable', 'verification_evidence_invalid')
        context = prerequisites.context
        revoke_snapshot(snapshot)
        if not snapshot.current() or not context.current():
            return finish('unverifiable', 'verification_context_stale')
        limits = dataclasses.asdict(spec.limits)
        if len(snapshot.read_bytes()) > limits['source_bytes']:
            return finish('unverifiable', 'verification_context_stale')
        policy_id = js.identity('policy', {'kind': 'python-json-command-v1', 'version': '1',
            'limits': limits, 'process_creation': 'deny', 'network': 'deny', 'runtime_id': runtime.runtime_id})
        audit.update(baseline=dict(spec.baseline), snapshot_id=snapshot.snapshot_id,
            specification_id=spec.specification_id, runtime_id=runtime.runtime_id,
            policy_id=policy_id, prerequisite_id=prerequisites.prerequisite_id,
            required_case_ids=list(spec.required_case_ids))
        entry = runtime.entry
        roots = tuple(entry['runtime_roots'])
        if any(snapshot._env.worktree.is_relative_to(Path(root)) or context.spec_path.is_relative_to(Path(root))
               for root in roots):
            return finish('unverifiable', 'verification_runtime_untrusted')
        try:
            # A fresh trusted command proves launch/transport before interpreting candidate exits.
            canary = run_readonly_python(source=b'import sys; sys.stdout.write("ready")\n',
                interpreter=entry['interpreter'], runtime_roots=roots, limits=limits, request_bytes=b'')
            if (not enforcement_current(canary, source=b'import sys; sys.stdout.write("ready")\n',
                    interpreter=entry['interpreter'], runtime_roots=roots, limits=limits, request_bytes=b'') or canary.exit_code != 0 or canary.stdout != 'ready' or not canary.cleanup_complete or
                    not canary.capture_complete or not canary.stdin_complete or canary.error):
                return finish('unverifiable', 'verification_containment_unavailable')
            for case in spec.cases:
                if not snapshot.current() or not context.current():
                    return finish('unverifiable', 'verification_context_stale')
                invocation = uuid.uuid4().hex
                outcome = run_readonly_python(source=snapshot.read_bytes(), interpreter=entry['interpreter'],
                    runtime_roots=roots, limits=limits, request_bytes=case.request, invocation_id=invocation)
                audit['cases'].append({'id': case.id, 'invocation_id': invocation,
                    'request_sha256': hashlib.sha256(case.request).hexdigest(),
                    'response_sha256': hashlib.sha256(outcome.stdout_bytes).hexdigest() if outcome.stdout_bytes is not None else None,
                    'exit_code': outcome.exit_code, 'cleanup_complete': outcome.cleanup_complete,
                    'capture_complete': outcome.capture_complete, 'stdin_complete': outcome.stdin_complete})
                if not outcome.cleanup_complete:
                    return finish('unverifiable', 'verification_cleanup_unconfirmed')
                if (not enforcement_current(outcome, source=snapshot.read_bytes(), interpreter=entry['interpreter'],
                        runtime_roots=roots, limits=limits, request_bytes=case.request) or
                        outcome.invocation_id != invocation or outcome.error or outcome.timed_out or
                        not outcome.stdin_complete or not outcome.capture_complete):
                    return finish('unverifiable', 'verification_execution_incomplete')
                if outcome.exit_code != 0:
                    return finish('rejected', 'semantic_child_failed')
                try:
                    if outcome.stdout_bytes is None:
                        return finish('unverifiable', 'verification_execution_incomplete')
                    response = js.loads(outcome.stdout_bytes)
                except ValueError:
                    return finish('rejected', 'semantic_response_invalid')
                if not js.equivalent(response, case.expected):
                    return finish('rejected', 'semantic_response_mismatch')
        except SandboxUnavailableError:
            return finish('unverifiable', 'verification_containment_unavailable')
        if not snapshot.current() or not context.current():
            return finish('unverifiable', 'verification_context_stale')
        if getattr(context, 'export_root', None) is None:
            return finish('accepted', 'semantic_checks_passed')
        authorization = _Authorization()
        with _AUTH_LOCK:
            _AUTHORIZATIONS[authorization] = {'snapshot': snapshot, 'context': context,
                'state': 'issued', 'pid': os.getpid(), 'audit_id': js.identity('assessment', audit),
                'destination_id': js.identity('destination', {'root': str(context.export_root),
                    'device': context._destination_identity[0], 'inode': context._destination_identity[1]})}
        return finish('accepted', 'semantic_checks_passed', authorization)


def authority_live(authorization: object) -> bool:
    with _AUTH_LOCK:
        record = _AUTHORIZATIONS.get(authorization)
        return bool(record is not None and record.get('pid') == os.getpid() and
                    record['state'] == 'issued' and record['snapshot'].current() and
                    record['context'].current())


def revoke_snapshot(snapshot: object) -> None:
    with _AUTH_LOCK:
        for handle, record in list(_AUTHORIZATIONS.items()):
            if record['snapshot'] is snapshot:
                revoke(handle)


def revoke_environment(env: object) -> None:
    with _AUTH_LOCK:
        for handle, record in list(_AUTHORIZATIONS.items()):
            if record['snapshot']._env is env:
                revoke(handle)


def _reset_after_fork() -> None:
    global _AUTH_LOCK
    _AUTH_LOCK = threading.RLock()
    _AUTHORIZATIONS.clear()
    _ASSESSMENTS.clear()
    _CONTEXTS.clear()
    _PREREQUISITES.clear()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_after_fork)
