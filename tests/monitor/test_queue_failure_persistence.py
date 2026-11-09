"""A scan and completed attempts survive a later attempt failure."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from evolution.code import strict_json as js
from evolution.code.campaign_report import OrganismResult
from evolution.monitor.__main__ import main
from evolution.monitor.attempt import attempt_candidates
from evolution.monitor.queue import build_queue
from evolution.monitor.sentinel import RepairCandidate


def test_queue_is_persisted_when_attempt_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = RepairCandidate(tool_path="tools/x.py", test_path="tests/test_x.py",
                                fix_sha="fix", parent_sha="parent", kind="bug_fix", committed_at="date")
    monkeypatch.setattr("evolution.monitor.__main__.scan", lambda *args, **kwargs: [candidate])

    def fail_after_progress(repo: Path, candidates: list, payload: dict, **kwargs: object) -> None:
        payload["candidates"][0]["attempt"] = {"status": "attempted", "correct_seeds": 1}
        raise RuntimeError("synthetic failure after progress")

    monkeypatch.setattr("evolution.monitor.attempt.attempt_candidates", fail_after_progress)
    out = tmp_path / "out"
    result = CliRunner().invoke(main, ["--repo", str(tmp_path), "--output-dir", str(out),
                                      "--attempt-top", "1", "--max-cost-usd", "1"])
    assert result.exit_code != 0
    saved = json.loads((out / "triage_queue.json").read_text())
    assert saved["candidates"][0]["attempt"]["correct_seeds"] == 1


def test_durable_monitor_reconstructs_committed_annotations_when_later_attempt_raises(
    tmp_path: Path,
) -> None:
    candidates = [RepairCandidate(
        tool_path=f"tools/{name}.py", test_path=f"tests/test_{name}.py",
        fix_sha=sha * 40, parent_sha="a" * 40, kind="bug_fix",
        committed_at="2026-01-01T00:00:00+00:00",
    ) for name, sha in (("one", "b"), ("two", "c"))]
    payload = build_queue(candidates, repo=str(tmp_path), since_days=90)
    persisted = []

    def runner(repo: Path, candidate: object) -> OrganismResult:
        if candidate.fix_sha == "c" * 40:
            raise RuntimeError("interrupted second organism")
        return OrganismResult(candidate.tool_path, candidate.fix_sha, [True])

    progress_root = tmp_path / "progress"
    with pytest.raises(RuntimeError, match="interrupted second organism"):
        attempt_candidates(
            tmp_path, candidates, payload, organism_runner=runner, seeds=1,
            require_sandbox=False, progress_root=progress_root,
            persist=lambda data: persisted.append(copy.deepcopy(data)),
        )
    records = [js.loads(line) for line in (progress_root / "campaign_progress.jsonl").read_bytes().splitlines()]
    assert any(record["kind"] == "organism_completed" for record in records)
    assert persisted, "the durable first result was never reflected in the queue"
    first = next(row for row in persisted[-1]["candidates"] if row["fix_sha"] == "b" * 40)
    assert first["attempt"] == {
        "status": "attempted", "correct_seeds": 1, "seeds": 1, "deploy_reachable": True,
    }
