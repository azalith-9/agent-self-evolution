"""Lookalike snapshots, runtimes and candidate receipts never confer authority.

These refusal tests deliberately do not mock a successful trusted execution.
Successful acceptance is exercised separately by opt-in native demonstrations.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.code.verification_fixtures import SOURCE, TARGET, component, semantic_spec


@pytest.mark.parametrize(
    "evidence",
    [
        {"schema_version": "1", "status": "accepted", "reason": "semantic_checks_passed"},
        {"exit_code": 0, "cleanup_complete": True, "stdout": '{"sum":5}'},
        {"invocation_id": "replayed", "receipt_id": "a" * 64, "status": "accepted"},
    ],
)
def test_candidate_written_evidence_and_forged_handles_are_non_authoritative(
    tmp_path: Path,
    evidence: dict,
) -> None:
    api = component("evolution.code.semantic_verifier")
    marker = tmp_path / "must-not-run"
    snapshot = SimpleNamespace(
        target=TARGET,
        mode=0o700,
        snapshot_id="a" * 64,
        read_bytes=lambda: SOURCE + f"open({str(marker)!r}, 'w')".encode(),
        evidence=evidence,
    )
    assessment = api.SemanticVerifier().assess(
        snapshot,
        spec=semantic_spec(),
        runtime=SimpleNamespace(**evidence),
        prerequisites={"passed": True, "evidence": evidence},
    )
    assert assessment.status == "unverifiable"
    assert assessment.authorization is None
    assert not marker.exists()


def test_missing_trusted_prerequisites_cannot_be_supplied_as_boolean_mapping(
    tmp_path: Path,
) -> None:
    from tests.code.test_verified_snapshot import environment

    snapshots = component("evolution.code.verified_snapshot")
    contracts = component("evolution.code.verification_contracts")
    verifier = component("evolution.code.semantic_verifier")
    from tests.code.verification_fixtures import protected_json

    spec = contracts.load_semantic_spec(protected_json(tmp_path / "spec.json", semantic_spec()))
    with snapshots.ProtectedSnapshot.capture(
        environment(tmp_path), tool_relpath=TARGET
    ) as snapshot:
        result = verifier.SemanticVerifier().assess(
            snapshot,
            spec=spec,
            runtime=None,
            prerequisites={
                "diagnostics": True,
                "scope": True,
                "surface": True,
                "retain_floor": True,
                "benchmark": True,
            },
        )
    assert (result.status, result.authorization) == ("unverifiable", None)
