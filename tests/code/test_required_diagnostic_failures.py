"""Completed required failures remain repair feedback and negative measurements."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from evolution.code.gate import run_code_oracle_gate
from evolution.code.repair import RepairResult
from evolution.code.worktree import TestRun as Run
from tests.code.conftest import BUGGY_CALC, FIXED_CALC, VISIBLE_TEST, StagedRepo


def test_required_failure_is_complete_feedback(tmp_path: Path) -> None:
    repo = StagedRepo(tmp_path)
    repo.write("tools/calc.py", BUGGY_CALC)
    repo.write("tests/tools/test_visible.py", VISIBLE_TEST)
    node = "tests/tools/test_visible.py::test_add_visible"
    observed = repo.run_test(node)
    assert observed.diagnostic_complete
    assert observed.missing == frozenset({node})
    assert not observed.unexecuted
    assert repo.failing_tests(node) == {node}


def test_oracle_complete_negative_preserves_measurement(tmp_path: Path) -> None:
    repo = StagedRepo(tmp_path)
    repo.changed_files = Mock(return_value=["tools/calc.py"])
    repo.failing_tests = Mock(return_value={"tests/tools/test_visible.py::test_add_visible"})
    result = run_code_oracle_gate(
        repo, tool_relpath="tools/calc.py", test_relpath="tests/tools/test_visible.py",
        bug_tests=("tests/tools/test_visible.py::test_add_visible",), oracle_failures=frozenset(),
        base_src=BUGGY_CALC, repair_result=RepairResult(True, 1, FIXED_CALC, []),
    )
    assert not result.deploy
    assert result.decision["decision"] == "incorrect"
    assert result.decision["diagnostic_comparison"]["status"] == "failed"


def test_completed_failure_with_no_required_call_is_inconclusive() -> None:
    run = Run(False, "setup failed", .01, 1, evidence_complete=True, cleanup_complete=True,
              failures=frozenset({"test_a"}), invocation_id="diagnostic", unexecuted=frozenset({"test_a"}))
    assert not run.diagnostic_complete
