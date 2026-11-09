"""Credential-free inputs shared by the pending verification contract tests.

These are data fixtures, never runtime provisioning or export authority.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType


TARGET = "tools/command.py"
SOURCE = b"import json, sys\na, b = json.load(sys.stdin)\nprint(json.dumps({'sum': a + b}))\n"
LIMITS = {
    "wall_seconds": 5,
    "cleanup_seconds": 5,
    "cpu_seconds": 2,
    "memory_bytes": 268435456,
    "processes": 1,
    "scratch_inodes": 4096,
    "scratch_bytes": 16777216,
    "source_bytes": 1048576,
    "request_bytes": 65536,
    "stdout_bytes": 65536,
    "stderr_bytes": 65536,
}


def component(name: str) -> ModuleType:
    return importlib.import_module(name)


def semantic_spec() -> dict:
    return {
        "schema_version": "2",
        "kind": "python-json-command-v1",
        "baseline": {
            "repository_id": "fixture-repository",
            "commit": "a" * 40,
            "target": TARGET,
            "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
        },
        "runtime_id": "independent-python",
        "required_case_ids": ["positive", "negative"],
        "cases": [
            {"id": "positive", "request_base64": "WzIsM10K", "expected": {"sum": 5}},
            {"id": "negative", "request_base64": "Wy0yLDNdCg==", "expected": {"sum": 1}},
        ],
        "limits": dict(LIMITS),
    }


def protected_json(path: Path, value: object) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def request_case(data: bytes) -> dict:
    return {
        "id": "bytes",
        "request_base64": base64.b64encode(data).decode("ascii"),
        "expected": None,
    }


def campaign_identity(*, seed_count: int = 3) -> dict:
    canonical = component("evolution.code.strict_json").identity
    candidate = {
        "repository_id": "fixture-repository",
        "baseline_commit": "a" * 40,
        "fix_commit": "b" * 40,
        "tool_path": TARGET,
        "test_path": "tests/test_command.py",
        "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
        "test_sha256": "c" * 64,
        "adapter_kind": "hermes",
    }
    organism_id = canonical("organism", candidate)
    configuration = {
        "durability": "seed",
        "reporting_algorithm": "cluster-honest-v1",
        "max_rounds": 2,
        "proposer_model": "deterministic-fixture",
        "require_sandbox": True,
        "runtime_id": "d" * 64,
    }
    seeds = []
    for index in range(seed_count):
        value = 100 + index
        seed_id = canonical(
            "seed",
            {
                "organism_id": organism_id,
                "seed_index": index,
                "seed_value": value,
                "configuration": configuration,
            },
        )
        seeds.append({"seed_id": seed_id, "seed_index": index, "seed_value": value})
    return {
        "identity_manifest": {
            "repository_id": "fixture-repository",
            "method": "repair",
            "seed_count": seed_count,
            "journal_version": "2",
        },
        "configuration": configuration,
        "organisms": [
            {"organism_id": organism_id, "candidate_identity": candidate, "seeds": seeds}
        ],
        "stages": [1],
    }


def seed_result(passed: bool = True) -> dict:
    return {
        "diagnostic_status": "passed" if passed else "failed",
        "reason": "fixture_comparison",
        "candidate_snapshot_id": "e" * 64,
        "observation_digest": "f" * 64,
        "cost_observation_ids": [],
        "cost_coverage": "unknown_remainder",
    }


def start_attempt(progress: object, index: int, attempt_id: str, *, retry_of: str | None = None) -> None:
    """Explicit synthetic dispatch boundary for recovery tests with stable IDs."""
    journal = progress._journal
    seed = journal.seed(progress.organism_id, index)
    journal.append('seed_started', {
        'organism_id': progress.organism_id, 'seed_id': seed['seed_id'],
        'seed_index': index, 'attempt_id': attempt_id, 'retry_of': retry_of})
