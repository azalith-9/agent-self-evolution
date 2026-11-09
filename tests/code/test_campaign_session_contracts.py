"""Scheduling ceilings are durable campaign-total audit state across sessions."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from evolution.code import strict_json as js
from tests.code.test_campaign_attempt_contracts import identity_v2
from tests.code.test_campaign_state import open_journal


def budgeted_identity() -> dict:
    identity = identity_v2()
    configuration = identity["configuration"]
    configuration["budget_policy"] = {
        "currency": "USD", "scope": "campaign_total", "initial_ceiling_usd": Decimal("1.0"),
        "change_rule": "increase_only",
    }
    member = identity["organisms"][0]
    for seed in member["seeds"]:
        seed["seed_id"] = js.identity("seed", {
            "organism_id": member["organism_id"], "seed_index": seed["seed_index"],
            "seed_value": seed["seed_value"], "configuration": configuration,
        })
    return identity


def test_initial_session_is_durable_and_identical_retry_appends_nothing(tmp_path: Path) -> None:
    with open_journal(tmp_path, budgeted_identity()) as journal:
        digest = journal.start_session(session_id="initial")
        path = tmp_path / "campaign_progress.jsonl"
        before = path.read_bytes()
        record = js.loads(before.splitlines()[-1])
        assert (record["kind"], record["record_hash"], record["payload"]) == (
            "session_started", digest, {
                "session_id": "initial", "previous_session_record_hash": None,
                "previous_ceiling_usd": Decimal("1.0"), "ceiling_usd": Decimal("1.0"),
                "reason": "initial",
            },
        )
        assert journal.start_session(session_id="initial") == digest
        assert path.read_bytes() == before


def test_ceiling_increase_is_linked_and_omitted_resume_inherits_it(tmp_path: Path) -> None:
    identity = budgeted_identity()
    with open_journal(tmp_path, identity) as journal:
        first = journal.start_session(session_id="first")
    with open_journal(tmp_path, identity) as journal:
        raised = journal.start_session(session_id="raised", ceiling_usd=Decimal("2.5"))
        assert journal.records[-1]["payload"] == {
            "session_id": "raised", "previous_session_record_hash": first,
            "previous_ceiling_usd": Decimal("1.0"), "ceiling_usd": Decimal("2.5"),
            "reason": "ceiling_increase",
        }
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="resumed")
        assert journal.records[-1]["payload"] == {
            "session_id": "resumed", "previous_session_record_hash": raised,
            "previous_ceiling_usd": Decimal("2.5"), "ceiling_usd": Decimal("2.5"),
            "reason": "resume",
        }


def test_ceiling_decrease_refuses_without_modifying_history(tmp_path: Path) -> None:
    identity = budgeted_identity()
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="first")
    with open_journal(tmp_path, identity) as journal:
        path = tmp_path / "campaign_progress.jsonl"
        before = path.read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            journal.start_session(session_id="lower", ceiling_usd=Decimal("0.5"))
        assert path.read_bytes() == before


def test_unlimited_ceiling_cannot_be_replaced_by_finite_ceiling(tmp_path):
    identity = budgeted_identity()
    identity['configuration']['budget_policy']['initial_ceiling_usd'] = None
    for member in identity['organisms']:
        for seed in member['seeds']:
            seed['seed_id'] = js.identity('seed', {
                'organism_id': member['organism_id'], 'seed_index': seed['seed_index'],
                'seed_value': seed['seed_value'], 'configuration': identity['configuration']})
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id='unlimited')
        before = (tmp_path / 'campaign_progress.jsonl').read_bytes()
        with pytest.raises(ValueError, match='campaign_transition_invalid'):
            journal.start_session(session_id='finite', ceiling_usd=Decimal('100'))
        assert (tmp_path / 'campaign_progress.jsonl').read_bytes() == before
