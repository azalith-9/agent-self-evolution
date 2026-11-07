"""Partial named failures must never authorize an oracle deployment."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolution.code.gate import run_code_gate, run_code_oracle_gate
from evolution.code.repair import RepairResult
from evolution.code.worktree import NonAuthoritativeRunError, TestRun as Run, WorktreeEnv


BASE = "def add(a, b):\n    return a - b\n"
REPAIRED = "def add(a, b):\n    return a + b\n"


class EvidenceEnv(WorktreeEnv):
    def __init__(self, tmp_path: Path, floor: Run) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        super().__init__(tmp_path, tmp_path, wt, tmp_path / "venv")
        self.floor = floor
        self.source = REPAIRED

    def read_tool(self, relpath: str) -> str:
        return self.source

    def write_tool(self, relpath: str, src: str) -> None:
        self.source = src

    def changed_files(self) -> list[str]:
        return ["tools/calc.py"]

    def run_test(self, *paths: str, **kwargs: object) -> Run:
        if paths == ("tests/tools",):
            return self.floor
        return Run(True, "1 passed", 0.01, 0)


@pytest.mark.parametrize("exit_code", [None, -9, 2, 3, 4])
def test_partial_failures_cannot_certify_oracle(tmp_path: Path, exit_code: int | None) -> None:
    run = Run(False, "ERROR tests/tools/test_calc.py\nInterrupted: collection failed", 0.1, exit_code)
    env = EvidenceEnv(tmp_path, run)
    env.run_test = lambda *paths, **kwargs: (
        run if paths == ("tests/tools/test_calc.py",) else Run(True, "1 passed", 0.01, 0)
    )
    repair = RepairResult(fixed=True, fixed_round=1, final_source=REPAIRED, rounds=[])
    try:
        result = run_code_oracle_gate(
            env, tool_relpath="tools/calc.py", test_relpath="tests/tools/test_calc.py",
            bug_tests=("tests/test_bug.py::test_add",),
            oracle_failures=frozenset({"tests/tools/test_calc.py"}),
            base_src=BASE, repair_result=repair,
        )
    except NonAuthoritativeRunError:
        return
    assert result.deploy is False


@pytest.mark.parametrize("base", ["", BASE], ids=["new-file", "existing-file"])
def test_failed_floor_with_suppressed_summary_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    env = EvidenceEnv(tmp_path, Run(False, "F\n1 failed", 0.01, 1))
    monkeypatch.setattr("evolution.code.gate._base_source", lambda *args: base)
    result = run_code_gate(
        env, tool_relpath="tools/calc.py", visible_test_relpath="tests/test_v.py",
        holdout_test_relpath="tests/test_h.py",
        repair_result=RepairResult(fixed=True, fixed_round=1, final_source=REPAIRED, rounds=[]),
        floor_paths=("tests/tools",),
    )
    assert result.deploy is False


def test_dot_prefixed_out_of_scope_path_cannot_alias_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = EvidenceEnv(tmp_path, Run(True, "1 passed", 0.01, 0))
    monkeypatch.setattr(env, "changed_files", lambda: ["..tools/calc.py"])
    monkeypatch.setattr("evolution.code.gate._base_source", lambda *args: BASE)
    result = run_code_gate(
        env, tool_relpath="tools/calc.py", visible_test_relpath="tests/test_v.py",
        holdout_test_relpath="tests/test_h.py",
        repair_result=RepairResult(fixed=True, fixed_round=1, final_source=REPAIRED, rounds=[]),
    )
    assert result.deploy is False
