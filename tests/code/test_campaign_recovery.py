"""Resume only an identifiable torn final ledger record, never interior corruption."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolution.code.campaign import run_campaign
from evolution.code.campaign_report import OrganismResult
from evolution.code.harvest import Candidate


def test_resume_recovers_torn_eof_without_losing_completed_organism(tmp_path: Path) -> None:
    ledger = tmp_path / "campaign_ledger.jsonl"
    complete = {"status": "organism", "tool": "tools/x.py", "fix_sha": "done", "seeds": [True]}
    ledger.write_text(json.dumps(complete) + '\n{"status": "organism", "fix_sha": "next"')
    seen = []

    def runner(candidate: Candidate) -> OrganismResult:
        seen.append(candidate.fix_sha)
        return OrganismResult(candidate.tool_path, candidate.fix_sha, [True])

    run_campaign(tmp_path, output_dir=tmp_path, max_organisms=3, stages=(), organism_runner=runner,
                 candidates=[Candidate("tools/x.py", "tests/test_x.py", sha, "parent") for sha in ("done", "next")])
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert seen == ["next"]
    assert [row["fix_sha"] for row in rows] == ["done", "next"]


def test_interior_ledger_corruption_is_not_silently_discarded(tmp_path: Path) -> None:
    ledger = tmp_path / "campaign_ledger.jsonl"
    ledger.write_text('not-json\n{"status":"not_valid","fix_sha":"done"}\n')
    with pytest.raises(ValueError):
        run_campaign(tmp_path, output_dir=tmp_path, stages=(), candidates=[], organism_runner=lambda c: None)
