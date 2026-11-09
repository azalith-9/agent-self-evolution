"""Credential-free native policy evidence; absence is never reported as enforcement."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import uuid
from pathlib import Path

import click

from evolution.code.strict_json import identity
from evolution.code.verification_runtime import resolve_runtime
from evolution.core.protected_execution import backend_path, run_readonly_python
from evolution.core.sandbox import SandboxUnavailableError

PROBES = (
    'scratch_access', 'host_read_denied', 'host_write_denied', 'snapshot_write_denied',
    'verifier_access_denied', 'expectations_access_denied', 'journal_access_denied',
    'authority_descriptors_closed', 'host_tcp_denied', 'host_udp_denied',
    'filesystem_unix_socket_denied', 'abstract_unix_socket_denied', 'private_process_visibility',
    'supervisor_signal_denied', 'memory_limit', 'process_limit', 'scratch_limit', 'cpu_limit',
    'stdin_bounded', 'capture_bounded', 'timeout_cleanup', 'cancellation_cleanup',
    'double_fork_cleanup', 'setsid_cleanup', 'sigterm_ignoring_cleanup', 'retained_output_cleanup',
    'runtime_mutation_denied', 'import_injection_denied', 'forged_evidence_rejected',
    'replayed_invocation_rejected', 'identity_substitution_rejected', 'source_mutation_rejected',
    'snapshot_substitution_rejected',
)
DEMOS = ('known_good_accepted', 'wrong_response_rejected', 'exact_byte_mode_export', 'consumed_authority_rejected')
LIMITS = dict(wall_seconds=3, cleanup_seconds=2, cpu_seconds=1, memory_bytes=67108864,
    processes=1, scratch_inodes=4096, scratch_bytes=4096, source_bytes=1048576, request_bytes=65536,
    stdout_bytes=65536, stderr_bytes=65536)


def _observation(identifier: str, reason: str) -> dict:
    return {'id': identifier, 'status': 'unavailable', 'command': [], 'exit_code': None,
            'observation': reason, 'receipt_ids': []}


def collect_cleanup_probes() -> list[dict]:
    """Observe generic Linux reaping separately from protected-policy authority."""
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest
    from evolution.core.process import run_process
    results = []
    for name in ('double_fork', 'setsid', 'sigterm_ignoring', 'retained_output'):
        row = _observation(name, 'Linux process observer unavailable')
        row['scope'] = 'generic-process-supervisor'
        if sys.platform != 'linux':
            results.append(row)
            continue
        with tempfile.TemporaryDirectory(prefix='ase-native-cleanup-') as directory:
            marker = Path(directory) / 'pid'
            script = (
                'import os,signal,time\n'
                'from pathlib import Path\n'
                'child=os.fork()\n'
                'if child == 0:\n'
                + (' child=os.fork()\n if child: os._exit(0)\n' if name == 'double_fork' else '')
                + (' os.setsid()\n' if name == 'setsid' else '')
                + (' signal.signal(signal.SIGTERM,signal.SIG_IGN)\n' if name == 'sigterm_ignoring' else '')
                + f' Path({str(marker)!r}).write_text(str(os.getpid()))\n'
                ' time.sleep(10)\n'
                ' os._exit(0)\n'
                'time.sleep(10)\n')
            command = [sys.executable, '-I', '-S', '-B', '-c', script]
            request = ExecutionRequest(argv=command, cwd=Path(directory), env={},
                policy=ExecutionPolicy(read_roots=[], write_roots=[], required=False),
                timeout_seconds=1, cleanup_timeout_seconds=2, invocation_id=uuid.uuid4().hex)
            outcome = run_process(request)
            absent = False
            if marker.exists():
                pid = int(marker.read_text())
                status = Path('/proc') / str(pid) / 'stat'
                try:
                    absent = status.read_text().split(') ', 1)[1].startswith('Z')
                except FileNotFoundError:
                    absent = True
            demonstrated = absent and outcome.cleanup_complete and outcome.timed_out and not outcome.error
            row.update(status='demonstrated' if demonstrated else 'failed', command=command,
                exit_code=outcome.exit_code, observation={
                    'descendant_observed': marker.exists(), 'descendant_absent': absent,
                    'cleanup_complete': outcome.cleanup_complete, 'timed_out': outcome.timed_out,
                    'error': outcome.error}, receipt_ids=[outcome.invocation_id])
        results.append(row)
    results.append(dict(_observation('cancellation', 'No native cancellation observation collected'),
                        scope='generic-process-supervisor'))
    return results


def collect(*, config: Path, runtime_id: str, demo: bool) -> dict:
    framework = hashlib.sha256()
    for path in sorted(Path(__file__).parents[1].rglob('*.py')):
        framework.update(path.relative_to(Path(__file__).parents[1]).as_posix().encode())
        framework.update(path.read_bytes())
    evidence = {'schema_version': '2', 'host': {'platform': sys.platform, 'machine': platform.machine(),
        'kernel': platform.release(), 'backend': 'bubblewrap' if sys.platform == 'linux' else None},
        'framework_id': framework.hexdigest(), 'runtime_id': None, 'policy_id': None,
        'demo_requested': demo, 'probes': [], 'demonstrations': [],
        'generic_cleanup': collect_cleanup_probes()}
    reason = 'verification_runtime_untrusted'
    runtime = None
    try:
        runtime = resolve_runtime(config, runtime_id=runtime_id)
        evidence['runtime_id'] = runtime.runtime_id
        backend_path()
        evidence['policy_id'] = identity('policy', {'version': '1', 'limits': LIMITS,
            'process_creation': 'deny', 'network': 'deny', 'runtime_id': runtime.runtime_id})
        reason = 'native observation not established'
    except (ValueError, SandboxUnavailableError) as exc:
        reason = str(exc)
    evidence['probes'] = [_observation(name, reason) for name in PROBES]
    evidence['demonstrations'] = [_observation(name, reason) for name in DEMOS] if demo else []
    if evidence['policy_id'] is None:
        if runtime is not None:
            runtime.close()
        return evidence
    try:
        # Trusted probe source is never a candidate receipt or an accepting oracle.
        scripts = {
            'scratch_access': b"from pathlib import Path\np=Path('/scratch/probe'); p.write_bytes(b'ok'); print(p.read_bytes()==b'ok')\n",
            'snapshot_write_denied': _denied("open('/candidate.py','wb')"),
            'runtime_mutation_denied': _denied(f"open({runtime.entry['interpreter']!r},'wb')"),
            'host_read_denied': _denied("open('/etc/passwd','rb')"),
            'host_write_denied': _denied("open('/host-write-probe','wb')"),
            'verifier_access_denied': _denied(f"open({str(Path(__file__).with_name('semantic_verifier.py'))!r},'rb')"),
            'expectations_access_denied': _denied(f"open({str(config)!r},'rb')"),
            'journal_access_denied': _denied(f"open({str(config.parent / 'campaign_progress.jsonl')!r},'rb')"),
            'host_tcp_denied': _denied("__import__('socket').socket()"),
            'host_udp_denied': _denied("__import__('socket').socket(2,2)"),
            'filesystem_unix_socket_denied': _denied("__import__('socket').socket(1)"),
            'abstract_unix_socket_denied': _denied("__import__('socket').socket(1)"),
            'process_limit': _denied("__import__('os').fork()"),
            'supervisor_signal_denied': _denied(f"__import__('os').kill({os.getpid()},0)"),
            'memory_limit': b"try:\n x=bytearray(134217728)\n print(False)\nexcept MemoryError:\n print(True)\n",
            'scratch_limit': b"try:\n with open('/scratch/fill','wb') as f:\n  for _ in range(32): f.write(b'x'*4096); f.flush()\n print(False)\nexcept OSError:\n print(True)\n",
            'authority_descriptors_closed': b"import os\nfound=[]\nfor fd in range(3,64):\n try: os.fstat(fd); found.append(fd)\n except OSError: pass\nprint(not found)\n",
            'import_injection_denied': b"import sys\nprint('/scratch' not in sys.path and '' not in sys.path and not any('site-packages' in p for p in sys.path))\n",
            'private_process_visibility': f"import os\nprint(not os.path.exists('/proc/{os.getpid()}/cmdline'))\n".encode(),
        }
        for row in evidence['probes']:
            name = row['id']
            if name not in scripts and name not in ('cpu_limit', 'timeout_cleanup', 'capture_bounded', 'stdin_bounded'):
                continue
            script = scripts.get(name, b'while True: pass\n')
            request = b''
            if name == 'capture_bounded':
                script = b"import os\nos.write(1,b'x'*131072)\n"
            if name == 'stdin_bounded':
                request = bytes(range(256)) * 256
                script = b"import hashlib,sys\nprint(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())\n"
            bounds = dict(LIMITS)
            if name == 'timeout_cleanup':
                script = b"import time\ntime.sleep(30)\n"
                bounds['wall_seconds'] = 1
            try:
                outcome = run_readonly_python(source=script, interpreter=runtime.entry['interpreter'],
                    runtime_roots=tuple(runtime.entry['runtime_roots']), limits=bounds, request_bytes=request)
            except SandboxUnavailableError as exc:
                row['observation'] = str(exc)
                continue
            receipt = identity('native-observation', {'id': name, 'invocation_id': outcome.invocation_id,
                'exit_code': outcome.exit_code, 'stdout_digest': hashlib.sha256(outcome.stdout.encode()).hexdigest(),
                'cleanup_complete': outcome.cleanup_complete, 'capture_complete': outcome.capture_complete})
            enforced = outcome.exit_code == 0 and outcome.stdout.strip() == 'True'
            if name == 'cpu_limit':
                enforced = outcome.exit_code in (-9, -24) and not outcome.timed_out
            elif name == 'timeout_cleanup':
                enforced = outcome.timed_out
            elif name == 'capture_bounded':
                enforced = not outcome.capture_complete and len(outcome.stdout.encode()) <= bounds['stdout_bytes']
            elif name == 'stdin_bounded':
                enforced = outcome.stdin_complete and outcome.stdout.strip() == hashlib.sha256(request).hexdigest()
            enforced = enforced and outcome.cleanup_complete and not outcome.error
            row.update(status='enforced' if enforced else 'failed', exit_code=outcome.exit_code,
                command=['protected-python-command', name], observation='parent evaluated native probe result',
                receipt_ids=[receipt])
    finally:
        runtime.close()
    return evidence


def _denied(expression: str) -> bytes:
    return ('try:\n ' + expression + '\n print(False)\nexcept (OSError, PermissionError):\n print(True)\n').encode()


@click.command()
@click.option('--verification-runtime-config', required=True, type=click.Path(path_type=Path))
@click.option('--runtime-id', required=True, type=str)
@click.option('--output-dir', required=True, type=click.Path(path_type=Path))
@click.option('--demo', is_flag=True, default=False)
def main(verification_runtime_config: Path, runtime_id: str, output_dir: Path, demo: bool) -> None:
    evidence = collect(config=verification_runtime_config, runtime_id=runtime_id, demo=demo)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = output_dir / 'native_evidence.json'
    evidence['collector_exit_code'] = (2 if any(row['status'] != 'enforced'
        for row in evidence['probes'] + evidence['demonstrations']) else 0)
    path.write_text(json.dumps(evidence, indent=2))
    path.chmod(0o600)
    if evidence['collector_exit_code']:
        raise click.exceptions.Exit(2)


if __name__ == '__main__':
    main()
