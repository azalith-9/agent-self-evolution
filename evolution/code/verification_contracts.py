"""Versioned contracts for protected single-file semantic checks."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from evolution.code import strict_json
from evolution.core.secure_paths import ProtectedRoot, relative_parts

LIMIT_RANGES = {
    'wall_seconds': (1, 60), 'cleanup_seconds': (1, 30), 'cpu_seconds': (1, 30),
    'memory_bytes': (67108864, 1073741824), 'processes': (1, 1),
    'scratch_inodes': (16, 65536), 'scratch_bytes': (4096, 67108864), 'source_bytes': (1, 1048576),
    'request_bytes': (1, 65536), 'stdout_bytes': (1, 1048576), 'stderr_bytes': (1, 1048576),
}


def fields(value: object, names: set[str]) -> dict:
    if type(value) is not dict or set(value) != names:
        raise ValueError('unexpected object fields')
    return value


def text(value: object) -> str:
    if type(value) is not str or not value.strip() or '\0' in value:
        raise ValueError('nonempty string required')
    return value


def digest(value: object) -> str:
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('lowercase SHA-256 required')
    return value


@dataclass(frozen=True)
class VerificationLimits:
    wall_seconds: int
    cleanup_seconds: int
    cpu_seconds: int
    memory_bytes: int
    processes: int
    scratch_bytes: int
    scratch_inodes: int
    source_bytes: int
    request_bytes: int
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class SemanticCase:
    id: str
    request: bytes
    expected_bytes: bytes

    @property
    def expected(self) -> object:
        return strict_json.loads(self.expected_bytes)


@dataclass(frozen=True)
class SemanticSpec:
    baseline: Mapping[str, str]
    runtime_id: str
    required_case_ids: tuple[str, ...]
    cases: tuple[SemanticCase, ...]
    limits: VerificationLimits
    specification_id: str


def load_semantic_spec(path: Path) -> SemanticSpec:
    """Read and validate the entire required case population before execution."""
    try:
        with ProtectedRoot.open(path.parent) as root:
            data = strict_json.loads(root.read_regular(path.name, max_bytes=4 * 1024 * 1024))
        fields(data, {'schema_version', 'kind', 'baseline', 'runtime_id', 'required_case_ids', 'cases', 'limits'})
        if data['schema_version'] != '2' or data['kind'] != 'python-json-command-v1':
            raise ValueError('unsupported specification version or kind')
        baseline = fields(data['baseline'], {'repository_id', 'commit', 'target', 'source_sha256'})
        text(baseline['repository_id'])
        if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', text(baseline['commit'])):
            raise ValueError('full commit required')
        relative_parts(baseline['target'])
        if not baseline['target'].endswith('.py'):
            raise ValueError('only Python source is supported')
        digest(baseline['source_sha256'])
        text(data['runtime_id'])
        raw_limits = fields(data['limits'], set(LIMIT_RANGES))
        for key, (lower, upper) in LIMIT_RANGES.items():
            if type(raw_limits[key]) is not int or not lower <= raw_limits[key] <= upper:
                raise ValueError('unsupported limit: ' + key)
        limits = VerificationLimits(**raw_limits)
        ids, cases = data['required_case_ids'], data['cases']
        if type(ids) is not list or not 1 <= len(ids) <= 256 or len(set(map(text, ids))) != len(ids):
            raise ValueError('required cases must be unique and nonempty')
        if type(cases) is not list or len(cases) != len(ids):
            raise ValueError('incomplete case population')
        parsed = []
        for identifier, case in zip(ids, cases):
            fields(case, {'id', 'request_base64', 'expected'})
            if case['id'] != identifier or type(case['request_base64']) is not str:
                raise ValueError('case identity mismatch')
            request = base64.b64decode(case['request_base64'], validate=True)
            if (base64.b64encode(request).decode() != case['request_base64'] or
                    len(request) > limits.request_bytes):
                raise ValueError('invalid request encoding or size')
            parsed.append(SemanticCase(identifier, request, strict_json.dumps(case['expected'])))
        return SemanticSpec(MappingProxyType(dict(baseline)), data['runtime_id'], tuple(ids),
                            tuple(parsed), limits, strict_json.identity('specification', data))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        raise ValueError('semantic_spec_invalid: ' + str(exc)) from exc
