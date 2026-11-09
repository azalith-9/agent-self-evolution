"""Interrupted execution cannot become untouched eligibility or implicit retry."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from evolution.code import strict_json as js
from tests.code.test_campaign_attempt_contracts import identity_v2
from tests.code.test_campaign_state import open_journal


def interrupted(root: Path, identity: dict) -> None:
    oid = identity["organisms"][0]["organism_id"]
    with open_journal(root, identity) as journal:
        progress = journal.seed_progress(oid)
        attempt = progress.start(0)
        progress.record_attempt(0, attempt_id=attempt.attempt_id, reason="interrupted_before_commit")


@pytest.mark.parametrize("persisted", [False, True], ids=["live", "replay"])
def test_inconclusive_execution_cannot_be_discarded_as_eligibility_skip(
    tmp_path: Path, persisted: bool,
) -> None:
    identity = identity_v2()
    interrupted(tmp_path, identity)
    oid = identity["organisms"][0]["organism_id"]
    path = tmp_path / "campaign_progress.jsonl"
    if not persisted:
        before = path.read_bytes()
        with open_journal(tmp_path, identity) as journal:
            with pytest.raises(ValueError, match="campaign_transition_invalid"):
                journal.append("organism_skipped", {"organism_id": oid, "reason": "not_valid"})
        assert path.read_bytes() == before
    else:
        previous = js.loads(path.read_bytes().splitlines()[-1])
        forged = {
            "schema_version": "2", "sequence": previous["sequence"] + 1,
            "campaign_id": previous["campaign_id"], "kind": "organism_skipped",
            "previous_hash": previous["record_hash"],
            "payload": {"organism_id": oid, "reason": "not_valid"},
        }
        forged["record_hash"] = js.identity("journal-record", forged)
        path.write_bytes(path.read_bytes() + js.dumps(forged) + b"\n")
        before = path.read_bytes()
        with pytest.raises(ValueError, match="campaign_state_corrupt"):
            with open_journal(tmp_path, identity):
                pytest.fail("a valid chain discarded an attempted seed as untouched eligibility")
        assert path.read_bytes() == before


def test_retry_requires_explicit_link_to_inconclusive_attempt(tmp_path: Path) -> None:
    identity = identity_v2()
    interrupted(tmp_path, identity)
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(identity["organisms"][0]["organism_id"])
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            progress.start(0)
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


@pytest.mark.parametrize("owner", ["journal", "progress", "attempt"])
def test_live_campaign_owners_cannot_be_shallow_copied(tmp_path: Path, owner: str) -> None:
    identity = identity_v2()
    with open_journal(tmp_path, identity) as journal:
        progress = journal.seed_progress(identity["organisms"][0]["organism_id"])
        attempt = progress.start(0)
        resource = {"journal": journal, "progress": progress, "attempt": attempt}[owner]
        with pytest.raises(TypeError):
            copy.copy(resource)
