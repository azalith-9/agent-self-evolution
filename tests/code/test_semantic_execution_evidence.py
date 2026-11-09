"""Parent comparisons with synthetic registered inputs and mocked child transport.

Registration here is test setup, not evidence that runtime preparation or native
containment works. No candidate code executes in this module.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code import semantic_verifier as api
from evolution.code import verification_runtime as runtimes
from evolution.code.verification_contracts import load_semantic_spec
from evolution.code.verified_snapshot import ProtectedSnapshot
from evolution.core.process import ProcessResult
from tests.code.test_verified_snapshot import environment
from tests.code.verification_fixtures import TARGET, protected_json, semantic_spec


@pytest.fixture
def registered_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    document = semantic_spec()
    document["limits"]["processes"] = 1
    spec = load_semantic_spec(protected_json(tmp_path / "spec.json", document))
    runtime = object.__new__(runtimes.TrustedRuntime)
    runtime.runtime_id = "d" * 64
    runtime.entry = MappingProxyType({
        "interpreter": str(tmp_path / "runtime/python"),
        "runtime_roots": (str(tmp_path / "runtime"),),
    })
    runtimes._RUNTIMES.add(runtime)
    monkeypatch.setattr(runtimes.TrustedRuntime, "current", lambda self: True)
    context = api.VerificationContext()
    context.spec, context.runtime, context.spec_path = spec, runtime, tmp_path / "spec.json"
    api._CONTEXTS.add(context)
    monkeypatch.setattr(api.VerificationContext, "current", lambda self: True)
    snapshot = ProtectedSnapshot.capture(environment(tmp_path), tool_relpath=TARGET)
    prerequisites = api._Prerequisites()
    prerequisites.context = context
    prerequisites.snapshot = snapshot
    prerequisites.prerequisite_id = "f" * 64
    api._PREREQUISITES.add(prerequisites)
    try:
        yield snapshot, dict(spec=spec, runtime=runtime, prerequisites=prerequisites)
    finally:
        for handle, record in list(api._AUTHORIZATIONS.items()):
            if record["snapshot"] is snapshot:
                api.revoke(handle)
        api._PREREQUISITES.discard(prerequisites)
        api._CONTEXTS.discard(context)
        runtimes._RUNTIMES.discard(runtime)
        snapshot.close()


def child(stdout: str, invocation_id: str) -> ProcessResult:
    return ProcessResult(
        exit_code=0, stdout=stdout, stderr="", timed_out=False,
        cleanup_complete=True, invocation_id=invocation_id,
        stdin_complete=True, capture_complete=True,
    )


@pytest.mark.parametrize(
    "mutation",
    ["partial_input", "capture_incomplete", "cleanup_uncertain", "replayed_invocation", "timeout", "supervisor_error"],
)
def test_matching_response_cannot_override_incomplete_execution(
    registered_inputs: tuple, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    snapshot, kwargs = registered_inputs

    def dispatch(**request: object) -> ProcessResult:
        if "invocation_id" not in request:
            return child("ready", "canary")
        outcome = child('{"sum":5}', request["invocation_id"])
        changes = {
            "partial_input": {"stdin_complete": False},
            "capture_incomplete": {"capture_complete": False},
            "cleanup_uncertain": {"cleanup_complete": False},
            "replayed_invocation": {"invocation_id": "another-execution"},
            "timeout": {"timed_out": True},
            "supervisor_error": {"error": "untrusted completion"},
        }
        return replace(outcome, **changes[mutation])

    execute = Mock(side_effect=dispatch)
    monkeypatch.setattr(api, "run_readonly_python", execute)
    assessment = api.SemanticVerifier().assess(snapshot, **kwargs)
    assert assessment.status == "unverifiable"
    assert execute.call_count <= 2, "dependent cases ran after incomplete execution"


@pytest.mark.parametrize(
    "response",
    ['{"sum":true}', '{"sum":5}\n{"status":"accepted"}', '{"status":"accepted","cleanup_complete":true}'],
)
def test_candidate_response_cannot_supply_verdict_or_forge_complete_evidence(
    registered_inputs: tuple, monkeypatch: pytest.MonkeyPatch, response: str,
) -> None:
    snapshot, kwargs = registered_inputs
    monkeypatch.setattr(api, "run_readonly_python", Mock(side_effect=lambda **request: (
        child("ready", "canary") if "invocation_id" not in request
        else child(response, request["invocation_id"])
    )))
    assessment = api.SemanticVerifier().assess(snapshot, **kwargs)
    assert assessment.status in {"rejected", "unverifiable"}
    assert not any(record["snapshot"] is snapshot for record in api._AUTHORIZATIONS.values())


def test_generic_process_success_without_enforcement_receipt_cannot_authorize(
    registered_inputs: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, kwargs = registered_inputs
    outputs = iter(['{"sum":5}', '{"sum":1}'])
    monkeypatch.setattr(api, "run_readonly_python", Mock(side_effect=lambda **request: (
        child("ready", "canary") if "invocation_id" not in request
        else child(next(outputs), request["invocation_id"])
    )))
    assessment = api.SemanticVerifier().assess(snapshot, **kwargs)
    assert assessment.status == "unverifiable", (
        "generic success booleans cannot prove resource enforcement, stream EOFs or scope reaping"
    )


@pytest.mark.parametrize("representation", ["constructed_result", "lookalike"])
def test_matching_enforcement_identifiers_do_not_create_a_protected_lease(
    registered_inputs: tuple, monkeypatch: pytest.MonkeyPatch, representation: str,
) -> None:
    snapshot, kwargs = registered_inputs
    responses = iter(['{"sum":5}', '{"sum":1}'])

    def forged_dispatch(**request: object) -> object:
        outcome = child(
            next(responses) if "invocation_id" in request else "ready",
            request.get("invocation_id", "canary"),
        )
        if representation == "lookalike":
            return SimpleNamespace(**vars(outcome), enforcement_id="fabricated-policy-receipt")
        object.__setattr__(outcome, "enforcement_id", "fabricated-policy-receipt")
        return outcome

    monkeypatch.setattr(api, "run_readonly_python", forged_dispatch)
    assessment = api.SemanticVerifier().assess(snapshot, **kwargs)
    assert assessment.status == "unverifiable", (
        "matching audit strings and correct answers cannot replace a supervisor-owned lease"
    )
