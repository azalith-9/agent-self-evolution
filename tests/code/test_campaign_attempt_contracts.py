"""Durable starts distinguish committed work from uncertain interrupted attempts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from evolution.code import strict_json as js
from tests.code.test_campaign_state import open_journal
from tests.code.verification_fixtures import campaign_identity, seed_result


def identity_v2(*, seed_count: int = 2) -> dict:
    identity = campaign_identity(seed_count=seed_count)
    identity["identity_manifest"]["journal_version"] = "2"
    identity["configuration"]["max_organisms"] = 1
    member = identity["organisms"][0]
    for seed in member["seeds"]:
        seed["seed_id"] = js.identity("seed", {
            "organism_id": member["organism_id"], "seed_index": seed["seed_index"],
            "seed_value": seed["seed_value"], "configuration": identity["configuration"],
        })
    return identity


def measured(*, cost_ids: tuple[str, ...] = (), coverage: str = "unknown_remainder") -> dict:
    result = seed_result()
    result.pop("cost_usd", None)
    return dict(result, cost_observation_ids=list(cost_ids), cost_coverage=coverage)


def observe(attempt_id: str, *, amount: Decimal | None = Decimal("0.125")) -> dict:
    return {
        "observation_id": "cost-1", "owner": "seed_attempt", "attempt_id": attempt_id,
        "status": "unknown" if amount is None else "measured", "amount_usd": amount,
        "coverage": "partial" if amount is None else "complete",
        "source": "credential-free-fixture", "observation_digest": "f" * 64,
    }


def test_strengthened_journal_writes_version_two(tmp_path: Path) -> None:
    with open_journal(tmp_path, identity_v2()) as journal:
        assert journal.records[0]["schema_version"] == "2"


def test_historical_journal_version_is_preserved_and_refuses_compatible_resume(tmp_path: Path) -> None:
    identity = identity_v2()
    old = {
        "schema_version": "1", "sequence": 0, "campaign_id": js.identity("campaign", identity),
        "kind": "campaign_initialized", "previous_hash": "0" * 64, "payload": identity,
    }
    old["record_hash"] = js.identity("journal-record", old)
    path = tmp_path / "campaign_progress.jsonl"
    path.write_bytes(js.dumps(old) + b"\n")
    path.chmod(0o600)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="campaign_state_(incompatible|corrupt)"):
        with open_journal(tmp_path, identity):
            pytest.fail("historical records were silently treated as current transitions")
    assert path.read_bytes() == before


@pytest.mark.parametrize("conflicting", [False, True])
def test_rehashed_duplicate_terminal_record_is_corruption(
    tmp_path: Path, conflicting: bool,
) -> None:
    identity = identity_v2(seed_count=1)
    with open_journal(tmp_path, identity) as journal:
        attempt = journal.seed_progress(identity["organisms"][0]["organism_id"]).start(0)
        attempt.commit(measured())
        duplicate = journal.records[-1]
    path = tmp_path / "campaign_progress.jsonl"
    duplicate["sequence"] += 1
    duplicate["previous_hash"] = duplicate.pop("record_hash")
    if conflicting:
        duplicate["payload"]["result"]["diagnostic_status"] = "failed"
    duplicate["record_hash"] = js.identity("journal-record", duplicate)
    path.write_bytes(path.read_bytes() + js.dumps(duplicate) + b"\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="campaign_state_corrupt"):
        with open_journal(tmp_path, identity):
            pytest.fail("a newly hashed duplicate terminal was accepted")
    assert path.read_bytes() == before


def test_terminal_wrapper_cannot_create_retrospective_start(tmp_path: Path) -> None:
    identity = identity_v2()
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(identity["organisms"][0]["organism_id"])
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            progress.commit(0, attempt_id="never-started", result=seed_result())
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


def test_start_is_durable_before_dispatch_and_commit_reuses_its_reference(tmp_path: Path) -> None:
    identity = identity_v2()
    oid = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(oid)
        attempt = progress.start(0)
        disk = [js.loads(line) for line in (tmp_path / "campaign_progress.jsonl").read_bytes().splitlines()]
        start = disk[-1]
        assert start["kind"] == "seed_started"
        assert start["payload"]["attempt_id"] == attempt.attempt_id
        digest = attempt.commit(measured())
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        assert attempt.commit(measured()) == digest
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before
        assert journal.records[-1]["payload"]["start_record_hash"] == start["record_hash"]
    with open_journal(tmp_path, identity) as journal:
        assert dict(journal.seed_progress(oid).completed) == {0: measured()}


def test_interrupted_start_survives_reopen_and_retry_has_distinct_identity(tmp_path: Path) -> None:
    identity = identity_v2()
    oid = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        first = journal.seed_progress(oid).start(0)
        first_id = first.attempt_id
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(oid)
        assert not progress.completed
        assert any(row["kind"] == "seed_started" and row["payload"]["attempt_id"] == first_id
                   for row in journal.records)
        progress.record_attempt(0, attempt_id=first_id, reason="interrupted_before_commit")
        terminal = journal.records[-1]
        assert terminal["kind"] == "seed_inconclusive"
        assert terminal["payload"]["cost_coverage"] == "unknown_remainder"
        retry = progress.start(0, retry_of=first_id)
        assert retry.attempt_id != first_id
        assert journal.records[-1]["payload"]["retry_of"] == first_id


def test_dependent_seed_cannot_start_while_prior_seed_is_outstanding(tmp_path: Path) -> None:
    identity = identity_v2()
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(identity["organisms"][0]["organism_id"])
        progress.start(0)
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            progress.start(1)
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("0.125"), None])
def test_cost_observations_are_idempotent_and_survive_resume(
    tmp_path: Path, amount: Decimal | None
) -> None:
    identity = identity_v2()
    oid = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        attempt = journal.seed_progress(oid).start(0)
        observation = observe(attempt.attempt_id, amount=amount)
        first = attempt.observe_cost(observation)
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        assert attempt.observe_cost(observation) == first
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            attempt.observe_cost(dict(observation, amount_usd=Decimal("9")))
        attempt.commit(measured(cost_ids=("cost-1",), coverage=(
            "unknown_remainder" if amount is None else "complete"
        )))
    with open_journal(tmp_path, identity) as journal:
        costs = [row["payload"] for row in journal.records if row["kind"] == "cost_observed"]
        assert costs == [observation]
        assert journal.seed_progress(oid).completed[0]["cost_coverage"] == (
            "unknown_remainder" if amount is None else "complete"
        )


@pytest.mark.parametrize("acknowledged", [False, True])
def test_replay_refuses_terminal_without_start_even_with_valid_chain(
    tmp_path: Path, acknowledged: bool
) -> None:
    identity = identity_v2()
    member = identity["organisms"][0]
    with open_journal(tmp_path, identity) as journal:
        first = journal.records[0]
        assert first["schema_version"] == "2", "replay must exercise the current writer version"
    path = tmp_path / "campaign_progress.jsonl"
    forged = {
        "schema_version": "2", "sequence": 1, "campaign_id": first["campaign_id"],
        "kind": "seed_completed", "previous_hash": first["record_hash"],
        "payload": {
            "organism_id": member["organism_id"], "seed_id": member["seeds"][0]["seed_id"],
            "seed_index": 0, "attempt_id": "orphan", "start_record_hash": "a" * 64,
            "result": measured(),
        },
    }
    forged["record_hash"] = js.identity("journal-record", forged)
    path.write_bytes(path.read_bytes() + js.dumps(forged) + (b"\n" if acknowledged else b""))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="campaign_state_corrupt"):
        with open_journal(tmp_path, identity):
            pytest.fail("a valid hash was mistaken for a valid transition")
    assert path.read_bytes() == before
