"""Durable seed commits, strict transitions, private storage, and exclusive writers."""

from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

import pytest

from tests.code.verification_fixtures import campaign_identity, component, seed_result, start_attempt


def open_journal(root: Path, identity: dict) -> object:
    return component("evolution.code.campaign_state").CampaignJournal.open(root, identity=identity)


def test_initialization_and_seed_commits_are_private_hash_chained_records(tmp_path: Path) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        start_attempt(journal.seed_progress(organism_id), 0, "attempt-0")
        journal.seed_progress(organism_id).commit(0, attempt_id="attempt-0", result=seed_result())
    rows = [
        json.loads(line)
        for line in (tmp_path / "campaign_progress.jsonl").read_bytes().splitlines()
    ]
    assert [row["kind"] for row in rows] == ["campaign_initialized", "seed_started", "seed_completed"]
    canonical = component("evolution.code.strict_json")
    for sequence, row in enumerate(rows):
        assert set(row) == {
            "schema_version",
            "sequence",
            "campaign_id",
            "kind",
            "previous_hash",
            "payload",
            "record_hash",
        }
        assert row["schema_version"] == "2" and type(row["sequence"]) is int
        assert row["sequence"] == sequence
        assert row["previous_hash"] == (
            "0" * 64 if sequence == 0 else rows[sequence - 1]["record_hash"]
        )
        document = canonical.loads(
            (tmp_path / "campaign_progress.jsonl").read_bytes().splitlines()[sequence]
        )
        digest = document.pop("record_hash")
        assert canonical.identity("journal-record", document) == digest
    for path in (tmp_path / "campaign_progress.jsonl", tmp_path / "campaign_progress.lock"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_completed_seed_survives_reopen_and_is_readonly(tmp_path: Path) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        start_attempt(progress, 0, "attempt-1")
        progress.commit(0, attempt_id="attempt-1", result=seed_result(False))
    with open_journal(tmp_path, identity) as journal:
        completed = journal.seed_progress(organism_id).completed
        assert dict(completed) == {0: seed_result(False)}
        with pytest.raises(TypeError):
            completed[1] = seed_result()
        try:
            completed[0]["diagnostic_status"] = "passed"
        except TypeError:
            pass
        assert journal.seed_progress(organism_id).completed[0]["diagnostic_status"] == "failed"


def test_identical_retry_does_not_append_but_conflicting_commit_refuses(tmp_path: Path) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        start_attempt(progress, 0, "attempt-0")
        first = progress.commit(0, attempt_id="attempt-0", result=seed_result())
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        assert progress.commit(0, attempt_id="attempt-0", result=seed_result()) == first
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            progress.commit(0, attempt_id="conflict", result=seed_result(False))
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean_index",
        "unknown_seed",
        "inconclusive_result",
        "negative_cost",
        "nonfinite_cost",
        "unknown_field",
        "missing_observation",
        "blank_attempt",
    ],
)
def test_malformed_completions_never_consume_seed(tmp_path: Path, mutation: str) -> None:
    from decimal import Decimal

    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    result = seed_result()
    index, attempt = 0, "attempt-0"
    if mutation == "boolean_index":
        index = True
    elif mutation == "unknown_seed":
        index = 3
    elif mutation == "inconclusive_result":
        result["diagnostic_status"] = "inconclusive"
    elif mutation == "negative_cost":
        result["cost_usd"] = Decimal("-0.1")
    elif mutation == "nonfinite_cost":
        result["cost_usd"] = Decimal("NaN")
    elif mutation == "unknown_field":
        result["deploy"] = True
    elif mutation == "missing_observation":
        del result["observation_digest"]
    elif mutation == "blank_attempt":
        attempt = ""
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        start_attempt(progress, 0, "attempt-0")
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            progress.commit(index, attempt_id=attempt, result=result)
        assert not progress.completed
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


def test_inconclusive_attempt_is_durable_but_does_not_complete_seed(tmp_path: Path) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        start_attempt(progress, 0, "timed-out")
        progress.record_attempt(
            0, attempt_id="timed-out", reason="execution_incomplete", observation_digest=None
        )
        assert not progress.completed
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        assert not progress.completed
        start_attempt(progress, 0, "retry", retry_of="timed-out")
        progress.commit(0, attempt_id="retry", result=seed_result())
        assert list(progress.completed) == [0]
    rows = [
        json.loads(line)
        for line in (tmp_path / "campaign_progress.jsonl").read_bytes().splitlines()
    ]
    assert [r["kind"] for r in rows] == ["campaign_initialized", "seed_started", "seed_inconclusive", "seed_started", "seed_completed"]


def test_concurrent_writer_is_rejected_and_retained_lock_reopens(tmp_path: Path) -> None:
    identity = campaign_identity()
    with open_journal(tmp_path, identity):
        with pytest.raises(ValueError, match="campaign_writer_busy"):
            with open_journal(tmp_path, identity):
                pytest.fail("second writer acquired the live journal")
    assert (tmp_path / "campaign_progress.lock").exists()
    with open_journal(tmp_path, identity) as journal:
        assert not journal.seed_progress(identity["organisms"][0]["organism_id"]).completed


@pytest.mark.parametrize("name", ["campaign_progress.jsonl", "campaign_progress.lock"])
def test_symlink_storage_refuses_without_touching_target(tmp_path: Path, name: str) -> None:
    identity = campaign_identity()
    outside = tmp_path / "do-not-touch"
    outside.write_bytes(b"preserved")
    (tmp_path / name).symlink_to(outside)
    with pytest.raises(ValueError, match="campaign_storage_untrusted"):
        with open_journal(tmp_path, identity):
            pytest.fail("unsafe storage accepted")
    assert outside.read_bytes() == b"preserved"


def test_closed_progress_context_cannot_append(tmp_path: Path) -> None:
    identity = campaign_identity()
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(identity["organisms"][0]["organism_id"])
    with pytest.raises(ValueError):
        progress.commit(0, attempt_id="late", result=seed_result())


@pytest.mark.parametrize(
    "field", ["max_rounds", "runtime_id", "require_sandbox", "stages", "seed_value"]
)
def test_incompatible_resume_preserves_completed_progress(tmp_path: Path, field: str) -> None:
    identity = campaign_identity()
    with open_journal(tmp_path, identity) as journal:
        start_attempt(journal.seed_progress(identity["organisms"][0]["organism_id"]), 0, "done")
        journal.seed_progress(identity["organisms"][0]["organism_id"]).commit(
            0, attempt_id="done", result=seed_result()
        )
    before = (tmp_path / "campaign_progress.jsonl").read_bytes()
    changed = copy.deepcopy(identity)
    if field == "stages":
        changed["stages"] = [1, 2]
    elif field == "seed_value":
        changed["organisms"][0]["seeds"][0]["seed_value"] += 1
    elif field == "max_rounds":
        changed["configuration"][field] = 3
    elif field == "runtime_id":
        changed["configuration"][field] = "9" * 64
    else:
        changed["configuration"][field] = False
    with pytest.raises(ValueError, match="campaign_state_incompatible"):
        with open_journal(tmp_path, changed):
            pytest.fail("incompatible state reused")
    assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


def test_fsync_uncertainty_stops_session_and_reuses_surviving_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = campaign_identity()
    organism_id = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        journal_inode = (tmp_path / "campaign_progress.jsonl").stat().st_ino
        start_attempt(progress, 0, "survived")
        real_fsync = os.fsync
        failed = False

        def lose_acknowledgment(fd: int) -> None:
            nonlocal failed
            real_fsync(fd)
            if not failed and os.fstat(fd).st_ino == journal_inode:
                failed = True
                raise OSError("synthetic fsync acknowledgment loss")

        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", lose_acknowledgment)
            with pytest.raises(ValueError, match="campaign_persistence_uncertain"):
                progress.commit(0, attempt_id="survived", result=seed_result())
            with pytest.raises(ValueError, match="campaign_persistence_uncertain"):
                progress.commit(1, attempt_id="must-not-advance", result=seed_result())
        assert failed
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(organism_id)
        assert dict(progress.completed) == {0: seed_result()}
        progress.commit(0, attempt_id="survived", result=seed_result())
    rows = [
        json.loads(line)
        for line in (tmp_path / "campaign_progress.jsonl").read_bytes().splitlines()
    ]
    assert [r["kind"] for r in rows].count("seed_completed") == 1
