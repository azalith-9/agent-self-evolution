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


@pytest.mark.parametrize("tail", [b'{', b'{"fix_sha": "unfinished', b'{"tool": "tools/x.py",'])
def test_resume_recovers_torn_record_regardless_of_first_key(tmp_path: Path, tail: bytes) -> None:
    ledger = tmp_path / "campaign_ledger.jsonl"
    complete = {"status": "not_valid", "tool": "tools/x.py", "fix_sha": "done"}
    prefix = (json.dumps(complete) + "\n").encode()
    ledger.write_bytes(prefix + tail)
    run_campaign(tmp_path, output_dir=tmp_path, stages=(), candidates=[], organism_runner=lambda c: None)
    assert ledger.read_bytes() == prefix


def test_resume_separates_complete_unterminated_record_from_next_append(tmp_path: Path) -> None:
    ledger = tmp_path / "campaign_ledger.jsonl"
    complete = {"status": "not_valid", "tool": "tools/x.py", "fix_sha": "done"}
    ledger.write_text(json.dumps(complete))
    candidate = Candidate("tools/x.py", "tests/test_x.py", "next", "parent")
    run_campaign(tmp_path, output_dir=tmp_path, stages=(), candidates=[candidate],
                 organism_runner=lambda c: OrganismResult(c.tool_path, c.fix_sha, [True]))
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["fix_sha"] for row in rows] == ["done", "next"]


@pytest.mark.parametrize("payload", [
    b'{"status": "not_valid", "fix_sha": "done"}{"fix_sha": "partial',
    b'[]\n',
])
def test_resume_does_not_truncate_completed_or_wrong_shape_record(tmp_path: Path, payload: bytes) -> None:
    ledger = tmp_path / "campaign_ledger.jsonl"
    ledger.write_bytes(payload)
    with pytest.raises(ValueError):
        run_campaign(tmp_path, output_dir=tmp_path, stages=(), candidates=[], organism_runner=lambda c: None)
    assert ledger.read_bytes() == payload
