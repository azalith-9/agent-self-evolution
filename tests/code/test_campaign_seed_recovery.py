"""The public progress-runner seam resumes only durably committed seeds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolution.code.campaign import run_campaign
from evolution.code.campaign_report import OrganismResult
from evolution.code.harvest import Candidate
from tests.code.verification_fixtures import seed_result, start_attempt


@pytest.mark.parametrize("interrupt", ["before_commit", "after_commit", "before_organism_return"])
def test_resume_retains_committed_seeds_and_matches_uninterrupted_fixture(
    tmp_path: Path,
    interrupt: str,
) -> None:
    candidate = Candidate("tools/command.py", "tests/test_command.py", "b" * 40, "a" * 40)
    calls: list[int] = []
    interrupted = False
    checkpoints: dict[int, dict] = {}

    def runner(c: Candidate, *, seed_progress: object) -> OrganismResult:
        nonlocal interrupted
        for index, passed in enumerate((True, False, True)):
            if index in seed_progress.completed:
                continue
            calls.append(index)
            aid = f"seed-{index}-{calls.count(index)}"
            start_attempt(seed_progress, index, aid, retry_of=seed_progress.latest_inconclusive(index))
            if not interrupted and interrupt == "before_commit" and index == 1:
                interrupted = True
                raise KeyboardInterrupt("synthetic interruption before commit")
            seed_progress.commit(
                index, attempt_id=aid, result=seed_result(passed)
            )
            checkpoints[index] = dict(seed_progress.completed)
            if not interrupted and interrupt == "after_commit" and index == 1:
                interrupted = True
                raise KeyboardInterrupt("synthetic interruption after commit")
        if not interrupted and interrupt == "before_organism_return":
            interrupted = True
            raise KeyboardInterrupt("synthetic interruption before organism aggregate")
        return OrganismResult(
            c.tool_path,
            c.fix_sha,
            [seed_progress.completed[i]["diagnostic_status"] == "passed" for i in range(3)],
        )

    arguments = dict(
        output_dir=tmp_path / "resumed",
        candidates=[candidate],
        max_organisms=1,
        stages=(1,),
        seeds=3,
        require_sandbox=False,
        progress_runner=runner,
    )
    with pytest.raises(KeyboardInterrupt):
        run_campaign(tmp_path, **arguments)
    report = run_campaign(tmp_path, **arguments)
    assert calls == ([0, 1, 1, 2] if interrupt == "before_commit" else [0, 1, 2])
    assert len(checkpoints[2]) == 3
    calls.clear()
    arguments["output_dir"] = tmp_path / "uninterrupted"
    uninterrupted = run_campaign(tmp_path, **arguments)
    assert calls == [0, 1, 2]
    for key in ("deploy_reachable", "pooled_per_seed_rate_FOR_CONTRAST", "verdict"):
        assert report[key] == uninterrupted[key]
    rows = [
        json.loads(line)
        for line in (tmp_path / "resumed/campaign_progress.jsonl").read_bytes().splitlines()
    ]
    kinds = [row["kind"] for row in rows]
    assert kinds.count("seed_completed") == 3
    assert kinds.count("organism_completed") == kinds.count("stage_decided") == 1
    assert kinds.index("organism_completed") > max(
        i for i, kind in enumerate(kinds) if kind == "seed_completed"
    )


def test_legacy_and_progress_runners_cannot_both_be_selected(tmp_path: Path) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("ambiguous runner configuration executed")

    with pytest.raises(ValueError):
        run_campaign(
            tmp_path,
            output_dir=tmp_path,
            candidates=[],
            require_sandbox=False,
            organism_runner=forbidden,
            progress_runner=forbidden,
        )


def test_progress_runner_type_error_is_not_retried_as_legacy(tmp_path: Path) -> None:
    candidate = Candidate("tools/command.py", "tests/test_command.py", "b" * 40, "a" * 40)
    calls = []

    def runner(c: Candidate, *, seed_progress: object) -> OrganismResult:
        calls.append(c.fix_sha)
        raise TypeError("synthetic runner implementation defect")

    with pytest.raises(TypeError, match="synthetic runner implementation defect"):
        run_campaign(
            tmp_path,
            output_dir=tmp_path,
            candidates=[candidate],
            require_sandbox=False,
            progress_runner=runner,
        )
    assert calls == [candidate.fix_sha]


@pytest.mark.parametrize(
    "boundary", ["seed_completed", "organism_completed", "stage_decided", "campaign_completed"]
)
def test_durable_boundary_interruption_recovers_aggregates_before_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    import os

    candidates = [
        Candidate("tools/command.py", "tests/test_command.py", letter * 40, "a" * 40)
        for letter in ("b", "c", "d")
    ]
    calls = []
    seed_calls = []
    interrupted = False
    real_fsync = os.fsync
    output_dir = tmp_path / "campaign"

    def runner(c: Candidate, *, seed_progress: object) -> OrganismResult:
        calls.append(c.fix_sha)
        for index in range(2):
            if index not in seed_progress.completed:
                seed_calls.append((c.fix_sha, index))
                start_attempt(seed_progress, index, f"{c.fix_sha}-{index}")
                seed_progress.commit(
                    index, attempt_id=f"{c.fix_sha}-{index}", result=seed_result(False)
                )
        return OrganismResult(c.tool_path, c.fix_sha, [False, False])

    def interrupt_after_sync(fd: int) -> None:
        nonlocal interrupted
        real_fsync(fd)
        path = output_dir / "campaign_progress.jsonl"
        if interrupted or not path.exists() or os.fstat(fd).st_ino != path.stat().st_ino:
            return
        payload = path.read_bytes()
        rows = [json.loads(line) for line in payload.splitlines()]
        if not rows:
            return
        count = sum(row["kind"] == "seed_completed" for row in rows)
        if rows[-1]["kind"] == boundary and (boundary != "seed_completed" or count == 2):
            interrupted = True
            raise KeyboardInterrupt("synthetic interruption at durable boundary")

    arguments = dict(
        output_dir=output_dir,
        candidates=candidates,
        max_organisms=3,
        max_per_tool=3,
        stages=(1, 3),
        seeds=2,
        require_sandbox=False,
        progress_runner=runner,
    )
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", interrupt_after_sync)
        with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
            run_campaign(tmp_path, **arguments)
    assert interrupted
    report = run_campaign(tmp_path, **arguments)
    assert set(calls) == {"b" * 40}, "resume advanced past a reconstructed futility stop"
    assert seed_calls == [("b" * 40, 0), ("b" * 40, 1)]
    assert report["deploy_reachable"]["n"] == 1
    rows = [
        json.loads(line)
        for line in (output_dir / "campaign_progress.jsonl").read_bytes().splitlines()
    ]
    kinds = [row["kind"] for row in rows]
    assert kinds.count("organism_completed") == kinds.count("stage_decided") == 1
    assert kinds.count("campaign_completed") == 1
    assert rows[-1]["payload"]["stop_reason"] == "futility_stop"
