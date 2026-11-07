"""Cooperative diagnostics, including forged certificates, cannot authorize export."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from evolution.code.gate import run_code_gate, run_code_oracle_gate
from evolution.code.repair import RepairResult
from evolution.code.worktree import TestRun as Run, WorktreeEnv


BASE = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TARGET = "tools/calc.py"


class CooperativeEnv(WorktreeEnv):
    """An execution adapter that supplies diagnostics but no independent oracle."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, root, root, root / "venv", require_sandbox=False)
        (root / "tools").mkdir()
        (root / TARGET).write_text(FIXED)
        self.mutate = False

    def changed_files(self) -> list[str]:
        return [TARGET]

    def run_test(self, *paths: str, **kwargs: object) -> Run:
        if self.mutate:
            (self.worktree / TARGET).write_text(BASE)
        return Run(True, "cooperative green report", 0.01, 0,
                   evidence_complete=True, cleanup_complete=True,
                   failures=frozenset(), invocation_id="cooperative-request")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CooperativeEnv:
    monkeypatch.setattr("evolution.code.gate._base_source", lambda *args: BASE)
    return CooperativeEnv(tmp_path)


def evaluate(env: CooperativeEnv, gate: str) -> object:
    repair = RepairResult(fixed=True, fixed_round=1, final_source=FIXED, rounds=[])
    if gate == "held-out":
        return run_code_gate(
            env, tool_relpath=TARGET, visible_test_relpath="tests/test_visible.py",
            holdout_test_relpath="tests/test_holdout.py", repair_result=repair,
            floor_paths=("tests/floor",),
        )
    return run_code_oracle_gate(
        env, tool_relpath=TARGET, test_relpath="tests/test_calc.py",
        bug_tests=("tests/test_calc.py::test_add",), oracle_failures=frozenset(),
        base_src=BASE, repair_result=repair,
    )


@pytest.mark.parametrize("gate", ["held-out", "oracle"])
@pytest.mark.parametrize("forged", [None, "summary", "constructed-object"])
def test_cooperative_green_and_constructed_certificates_never_authorize_deployment(
    env: CooperativeEnv, gate: str, forged: str | None,
) -> None:
    if forged:
        summary = dict(schema_version="1", status="accepted", reason="all-green")
        env.deployment_verification = (
            summary if forged == "summary" else SimpleNamespace(**summary)
        )
    result = evaluate(env, gate)
    assert result.deploy is False
    assert result.decision["deployment_verification"] == {
        "schema_version": "1", "status": "unverifiable",
        "reason": "independent_test_verification_unavailable",
    }


@pytest.mark.parametrize("gate", ["held-out", "oracle"])
def test_target_mutation_during_green_run_cannot_certify_earlier_source(
    env: CooperativeEnv, gate: str,
) -> None:
    env.mutate = True
    result = evaluate(env, gate)
    assert result.deploy is False
    assert result.decision["deployment_verification"]["status"] != "accepted"


@pytest.mark.parametrize("gate", ["held-out", "oracle"])
def test_missing_independent_proof_is_separate_from_diagnostic_incompleteness(
    env: CooperativeEnv, gate: str,
) -> None:
    result = evaluate(env, gate)
    diagnostic = result.decision["diagnostic_comparison"]
    assert diagnostic["status"] in {"passed", "inconclusive"}
    assert diagnostic["reason"]
    assert result.decision["repair"]["fixed"] is True
    if gate == "oracle":
        assert result.decision["decision"] != "incorrect"


@pytest.mark.parametrize("skipped_floor", [False, True], ids=["green-diagnostic", "required-skip"])
def test_real_diagnostic_runs_keep_success_and_missing_execution_distinct(
    tmp_path: Path, skipped_floor: bool,
) -> None:
    from tests.code.conftest import HOLDOUT_TEST, VISIBLE_TEST, StagedRepo

    repo = StagedRepo(tmp_path)
    repo.write(TARGET, BASE)
    visible = "tests/tools/test_visible.py"
    holdout = "tests/tools/test_holdout.py"
    floor = "tests/tools/test_floor.py"
    repo.write(visible, VISIBLE_TEST)
    repo.write(holdout, HOLDOUT_TEST)
    repo.write(floor, "import pytest\n" + (
        "@pytest.mark.skip(reason='required test did not execute')\n" if skipped_floor else ""
    ) + "def test_required_floor(): pass\n")
    for arguments in [("init", "-q"), ("config", "user.email", "synthetic@example.invalid"),
                      ("config", "user.name", "Synthetic Test"),
                      ("add", "tools", "tests"), ("commit", "-qm", "baseline")]:
        outcome = repo._git(*arguments)
        assert outcome.returncode == 0, outcome.stderr
    repo.write_tool(TARGET, FIXED)
    result = run_code_gate(
        repo, tool_relpath=TARGET, visible_test_relpath=visible, holdout_test_relpath=holdout,
        repair_result=RepairResult(fixed=True, fixed_round=1, final_source=FIXED, rounds=[]),
        floor_paths=(floor + "::test_required_floor",),
    )
    assert result.decision["diagnostic_comparison"]["status"] == (
        "inconclusive" if skipped_floor else "passed"
    )
    assert result.deploy is False
