"""Acceptance ownership contracts; these tests do not certify native containment."""

from __future__ import annotations

import dataclasses
import inspect
import os
from pathlib import Path

import pytest

from evolution.code.gate import CodeGateResult, finalize_verification
from evolution.code.semantic_verifier import SemanticAssessment, VerificationContext
from evolution.code.verification_contracts import load_semantic_spec
from evolution.code.verified_snapshot import ProtectedSnapshot
from tests.code.test_verified_snapshot import environment
from tests.code.verification_fixtures import TARGET, protected_json, semantic_spec


@pytest.mark.parametrize("processes", [2, 16, 32])
def test_semantic_policy_refuses_every_multiprocess_request(
    tmp_path: Path, processes: int
) -> None:
    document = semantic_spec()
    document["limits"]["processes"] = processes
    with pytest.raises(ValueError, match="semantic_spec_invalid"):
        load_semantic_spec(protected_json(tmp_path / "spec.json", document))


def test_snapshot_refuses_hardlinked_candidate_source(tmp_path: Path) -> None:
    env = environment(tmp_path)
    os.link(env.worktree / TARGET, tmp_path / "candidate-alias.py")
    with pytest.raises(ValueError):
        with ProtectedSnapshot.capture(env, tool_relpath=TARGET):
            pytest.fail("a writable alias was accepted as a single-link source")


def test_snapshot_is_stale_while_candidate_execution_is_active(tmp_path: Path) -> None:
    env = environment(tmp_path)
    with ProtectedSnapshot.capture(env, tool_relpath=TARGET) as snapshot:
        env._execution_active = True
        assert snapshot.current() is False


def test_deployment_readiness_cannot_be_created_by_constructor_boolean() -> None:
    with CodeGateResult(True, "semantic_checks_passed", {}) as result:
        assert result.deploy is False


def test_result_closure_removes_readiness_even_for_historical_accepted_summary() -> None:
    result = CodeGateResult(True, "semantic_checks_passed", {
        "deployment_verification": {
            "schema_version": "1", "status": "accepted", "reason": "semantic_checks_passed"
        }
    })
    result.close()
    result.close()
    assert result.deploy is False
    assert result.export_authorization is None


def test_refinalization_clears_old_audit_before_missing_context_return(tmp_path: Path) -> None:
    result = CodeGateResult(False, "semantic_checks_passed", {"decision": "deploy"})
    result._semantic_audit = {"status": "accepted", "snapshot_id": "a" * 64}
    finalize_verification(
        result, env=environment(tmp_path), tool_relpath=TARGET,
        base_source="", verification=None,
    )
    try:
        assert result.deploy is False
        assert getattr(result, "_semantic_audit", None) is None
    finally:
        result.close()


def test_assessment_serialization_contains_no_authority_field() -> None:
    assessment = SemanticAssessment("accepted", "semantic_checks_passed", {"schema_version": "2"})
    assert set(dataclasses.asdict(assessment)) == {"status", "reason", "audit"}


def test_preparation_exposes_optional_explicit_export_destination() -> None:
    parameter = inspect.signature(VerificationContext.prepare).parameters.get("export_root")
    assert parameter is not None, "preparation cannot bind export to an owned destination"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
