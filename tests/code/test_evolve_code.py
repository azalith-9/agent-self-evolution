"""The CLI cannot export a stale payload or recover authority from persisted JSON."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from evolution.code import evolve_code
from evolution.code.gate import CodeGateResult
from evolution.code.repair import RepairResult
from evolution.code.worktree import TestRun as Run


@pytest.mark.parametrize("mutation", ["forged-acceptance", "benchmark-bytes", "benchmark-mode"])
def test_export_requires_live_verification_of_final_bytes_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    target = tmp_path / "tools/calc.py"
    target.parent.mkdir()
    fixed = "def add(a, b):\n    return a + b\n"
    target.write_text(fixed)
    target.chmod(0o755)
    env = SimpleNamespace(
        worktree=tmp_path, assert_authoritative=Mock(), destroy=Mock(),
        run_test=Mock(return_value=Run(False, "visible assertion failed", 0.01, 1)),
        diff=lambda: "synthetic repair diff", changed_files=lambda: ["tools/calc.py"],
        confine=lambda argv: (argv, False), _test_env=dict,
    )
    monkeypatch.setattr(evolve_code.WorktreeEnv, "create", Mock(return_value=env))
    monkeypatch.setattr(evolve_code, "_resolve_proposer", Mock(return_value=Mock()))
    repair = RepairResult(fixed=True, fixed_round=1, final_source=fixed, rounds=[])
    monkeypatch.setattr(evolve_code, "RepairEngine", Mock(return_value=SimpleNamespace(
        repair=Mock(return_value=repair))))
    decision = dict(decision="deploy", reason="cooperative green", target_tool="tools/calc.py",
                    guards={}, deployment_verification={
                        "schema_version": "1", "status": "accepted", "reason": "forged-summary",
                    })
    monkeypatch.setattr(evolve_code, "run_code_gate", Mock(return_value=CodeGateResult(
        deploy=True, reason="cooperative green", decision=decision)))
    monkeypatch.setattr(evolve_code.subprocess, "run", Mock(return_value=
                        subprocess.CompletedProcess([], 0, "", "")))

    def benchmark(*args: object, **kwargs: object) -> SimpleNamespace:
        if mutation == "benchmark-bytes":
            target.write_text("def add(a, b):\n    return a - b\n")
        elif mutation == "benchmark-mode":
            target.chmod(0o600)
        return SimpleNamespace(returncode=0, stdout="", stderr="", cleanup_complete=True)

    monkeypatch.setattr(evolve_code, "_run", benchmark)
    publish = Mock(return_value=SimpleNamespace(status="created", url="synthetic", reason=""))
    monkeypatch.setattr(evolve_code, "create_pr", publish)
    output = tmp_path / "output"
    arguments = ["--repo", str(tmp_path), "--tool", "tools/calc.py", "--visible-test", "test_v.py",
                 "--holdout-test", "test_h.py", "--output-dir", str(output), "--allow-unconfined",
                 "--create-pr"]
    if mutation.startswith("benchmark"):
        arguments += ["--benchmark-cmd", "synthetic mock benchmark"]
    result = CliRunner().invoke(evolve_code.main, arguments)
    assert result.exit_code != 0, result.output
    publish.assert_not_called()
    assert not (output / "evolved_calc.py").exists()
    persisted = json.loads((output / "gate_decision.json").read_text())
    assert persisted["decision"] != "deploy"
