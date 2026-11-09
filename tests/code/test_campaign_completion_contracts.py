"""Configured limits and legacy durability must describe the work actually done."""

from __future__ import annotations

from pathlib import Path

from evolution.code import strict_json as js
from evolution.code.campaign import diagnostic_seed_result, run_campaign
from evolution.code.campaign_report import OrganismResult
from evolution.code.harvest import Candidate


def candidates() -> list[Candidate]:
    return [Candidate(f"tools/{name}.py", f"tests/test_{name}.py", sha * 40, "a" * 40)
            for name, sha in (("one", "b"), ("two", "c"))]


def records(root: Path) -> list[dict]:
    return [js.loads(line) for line in (root / "campaign_progress.jsonl").read_bytes().splitlines()]


def test_configured_limit_completes_without_shrinking_requested_population(tmp_path: Path) -> None:
    population = candidates()
    called = []

    def legacy(candidate: Candidate) -> OrganismResult:
        called.append(candidate)
        return OrganismResult(candidate.tool_path, candidate.fix_sha, [True])

    report = run_campaign(
        tmp_path, output_dir=tmp_path / "progress", candidates=population,
        organism_runner=legacy, max_organisms=1, seeds=1, stages=(), require_sandbox=False,
    )
    assert called == population[:1]
    assert report["progress"]["requested_seeds"] == 2
    assert report["progress"]["completed"] is True
    rows = records(tmp_path / "progress")
    members = rows[0]["payload"]["organisms"]
    assert len(members) == 2
    assert rows[-1]["kind"] == "campaign_completed"
    assert rows[-1]["payload"]["stop_reason"] == "configured_limit_reached"
    assert rows[-1]["payload"]["unexecuted_organism_ids"] == [members[1]["organism_id"]]


def test_legacy_runner_has_durable_organism_start_before_invocation(tmp_path: Path) -> None:
    root = tmp_path / "progress"

    def legacy(candidate: Candidate) -> OrganismResult:
        assert records(root)[-1]["kind"] == "organism_started"
        return OrganismResult(candidate.tool_path, candidate.fix_sha, [True])

    run_campaign(
        tmp_path, output_dir=root, candidates=candidates()[:1], organism_runner=legacy,
        max_organisms=1, seeds=1, stages=(), require_sandbox=False,
    )
    assert not any(row["kind"].startswith("seed_") for row in records(root))


def test_missing_cost_observation_is_unknown_rather_than_measured_zero() -> None:
    result = diagnostic_seed_result({
        "diagnostic_comparison": {"status": "passed", "reason": "complete_diagnostics"}
    })
    assert result.get("cost_coverage") == "unknown_remainder"
    assert result.get("cost_observation_ids") == []
    assert "cost_usd" not in result
