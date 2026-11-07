"""A scan and completed attempts survive a later attempt failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from evolution.monitor.__main__ import main
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
