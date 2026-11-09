"""The organism adapter commits each diagnostic result before the next repair.

Execution and repair are synthetic here; journal durability uses real files.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code import campaign
from evolution.code.campaign_report import OrganismResult
from evolution.code.harvest import Candidate
from tests.code.test_campaign_state import open_journal
from tests.code.verification_fixtures import SOURCE, TARGET, campaign_identity, seed_result, start_attempt


def test_organism_reuses_seed_progress_and_commits_before_next_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    env = SimpleNamespace(assert_authoritative=Mock(), write_tool=Mock(), destroy=Mock())
    monkeypatch.setattr(campaign.WorktreeEnv, "create", Mock(return_value=env))
    monkeypatch.setattr(campaign, "_git_show", lambda *args: SOURCE.decode())
    monkeypatch.setattr(
        campaign, "_failures", Mock(side_effect=[set(), {"test_command.py::test_add"}])
    )
    gates = [
        SimpleNamespace(
            deploy=False,
            close=Mock(),
            decision={
                "diagnostic_comparison": {"status": status, "reason": "complete_diagnostics"},
                "deployment_verification": {
                    "schema_version": "1",
                    "status": "unverifiable",
                    "reason": "independent_test_verification_unavailable",
                },
            },
        )
        for status in ("failed", "passed")
    ]
    monkeypatch.setattr(campaign, "run_code_oracle_gate", Mock(side_effect=gates))
    candidate = Candidate(TARGET, "tests/test_command.py", "b" * 40, "a" * 40)
    with open_journal(tmp_path / "progress", identity) as journal:
        progress = journal.seed_progress(organism_id)
        start_attempt(progress, 0, "already-durable")
        progress.commit(0, attempt_id="already-durable", result=seed_result())
        seen = []

        def repair(*args: object, **kwargs: object) -> object:
            seen.append(sorted(progress.completed))
            assert seen[-1] == ([0] if len(seen) == 1 else [0, 1])
            return SimpleNamespace(fixed=True)

        result = campaign.run_organism(
            tmp_path,
            candidate,
            SimpleNamespace(repair=repair),
            seeds=3,
            base_python=None,
            require_sandbox=False,
            seed_progress=progress,
        )
        assert isinstance(result, OrganismResult)
        assert result.seeds == [True, False, True]
        assert sorted(progress.completed) == [0, 1, 2]
        assert len(seen) == 2
    env.destroy.assert_called_once()
