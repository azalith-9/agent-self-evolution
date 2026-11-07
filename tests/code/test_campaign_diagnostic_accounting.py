"""Diagnostic successes retain their measurement meaning when deployment refuses."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code import campaign
from evolution.code.campaign_report import OrganismResult
from evolution.code.harvest import Candidate


def test_seed_results_follow_diagnostic_comparison_not_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = SimpleNamespace(assert_authoritative=Mock(), write_tool=Mock(), destroy=Mock())
    monkeypatch.setattr(campaign.WorktreeEnv, "create", Mock(return_value=env))
    monkeypatch.setattr(campaign, "_git_show", lambda *args: "def add(a,b): return a-b\n")
    monkeypatch.setattr(campaign, "_failures", Mock(side_effect=[set(), {"test_calc.py::test_add"}]))
    outcomes = [SimpleNamespace(deploy=False, decision={
        "decision": "correct" if status == "passed" else "incorrect",
        "diagnostic_comparison": {"status": status, "reason": "complete diagnostics"},
        "deployment_verification": {"schema_version": "1", "status": "unverifiable",
                                    "reason": "independent_test_verification_unavailable"},
    }) for status in ("passed", "failed", "passed")]
    monkeypatch.setattr(campaign, "run_code_oracle_gate", Mock(side_effect=outcomes))
    result = campaign.run_organism(
        tmp_path, Candidate("tools/calc.py", "test_calc.py", "fix", "parent"),
        Mock(), seeds=3, base_python=None,
    )
    assert isinstance(result, OrganismResult)
    assert result.seeds == [True, False, True]
    env.destroy.assert_called_once()


def test_inconclusive_measurement_is_retried_on_resume(tmp_path: Path) -> None:
    candidate = Candidate("tools/calc.py", "test_calc.py", "fix", "parent")
    measure = Mock(return_value=campaign.Skip("run_inconclusive"))
    for _ in range(2):
        campaign.run_campaign(tmp_path, output_dir=tmp_path / "results", candidates=[candidate],
                              organism_runner=measure, max_organisms=1, stages=())
    assert measure.call_count == 2


@pytest.mark.parametrize("seeds,reachable", [([True, False], True), ([False, False], False)])
def test_even_seed_tie_preserves_at_least_half_contract(seeds: list[bool], reachable: bool) -> None:
    assert OrganismResult("tools/calc.py", "fix", seeds).deploy_reachable is reachable
