"""Public gate ownership and configuration; no mocked semantic acceptance."""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from evolution.code import campaign, evolve_code, gate
from evolution.code.deployment_evidence import verify_deployment
from tests.code.test_deployment_evidence import CooperativeEnv, evaluate
from tests.code.verification_fixtures import TARGET


@pytest.mark.parametrize("entrypoint", [gate.run_code_gate, gate.run_code_oracle_gate])
def test_both_gates_accept_explicit_keyword_only_verification_context(entrypoint: object) -> None:
    parameter = inspect.signature(entrypoint).parameters.get("verification")
    assert parameter is not None, "gate lacks the protected verification integration seam"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None


def test_missing_context_preserves_compact_refusal_schema(tmp_path: Path) -> None:
    env = CooperativeEnv(tmp_path)
    summary = verify_deployment(env, tool_relpath=TARGET, verification=None)
    assert summary == {
        "schema_version": "1",
        "status": "unverifiable",
        "reason": "independent_test_verification_unavailable",
    }


@pytest.mark.parametrize("forged", [{"status": "accepted"}, SimpleNamespace(status="accepted")])
def test_verification_argument_cannot_inject_an_accepting_adapter(
    tmp_path: Path, forged: object
) -> None:
    env = CooperativeEnv(tmp_path)
    summary = verify_deployment(env, tool_relpath=TARGET, verification=forged)
    assert summary["status"] == "unverifiable"
    assert set(summary) == {"schema_version", "status", "reason"}


@pytest.mark.parametrize("kind", ["held-out", "oracle"])
def test_rejected_gate_result_is_closeable_without_acquiring_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    monkeypatch.setattr(gate, "_base_source", lambda *args: "def add(a, b):\n    return a - b\n")
    env = CooperativeEnv(tmp_path)
    with evaluate(env, kind) as result:
        assert result.export_authorization is None
        assert result.deploy is False
        assert "export_authorization" not in json.dumps(result.decision)
    result.close()
    assert result.export_authorization is None


def test_result_authority_is_readonly_and_excluded_from_dataclass_serialization() -> None:
    result = gate.CodeGateResult(False, "unverifiable", {})
    try:
        assert result.export_authorization is None
        assert "export_authorization" not in dataclasses.asdict(result)
        with pytest.raises((AttributeError, TypeError)):
            result.export_authorization = SimpleNamespace(status="accepted")
    finally:
        close = getattr(result, "close", None)
        if close is not None:
            close()


def test_code_cli_exposes_local_verification_and_export_without_publication() -> None:
    outcome = CliRunner().invoke(evolve_code.main, ["--help"])
    assert outcome.exit_code == 0
    for option in (
        "--semantic-spec",
        "--verification-runtime-config",
        "--runtime-id",
        "--export-to",
    ):
        assert option in outcome.output


@pytest.mark.parametrize("entrypoint", [campaign.run_campaign, campaign.run_organism])
def test_campaign_public_api_requires_containment_by_default(entrypoint: object) -> None:
    assert inspect.signature(entrypoint).parameters["require_sandbox"].default is True


def test_campaign_cli_defaults_to_required_containment() -> None:
    parameter = next(option for option in campaign.main.params if option.name == "require_sandbox")
    assert parameter.default is True


def test_organism_seed_progress_is_keyword_only_and_optional() -> None:
    parameter = inspect.signature(campaign.run_organism).parameters.get("seed_progress")
    assert parameter is not None, "organism loop lacks durable seed progress"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None
