"""Durable sessions and costs cannot be inherited as fresh dispatch permission."""

from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code import strict_json as js
from evolution.code import campaign
from evolution.code.harvest import Candidate
from evolution.core import lm_timing_callback as timing
from tests.code.test_campaign_attempt_contracts import identity_v2, measured
from tests.code.test_campaign_session_contracts import budgeted_identity
from tests.code.test_campaign_state import open_journal
from tests.code.verification_fixtures import SOURCE, TARGET


def test_new_writer_process_requires_its_own_durable_session(tmp_path: Path) -> None:
    identity = budgeted_identity()
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="previous-process")
    path = tmp_path / "campaign_progress.jsonl"
    before = path.read_bytes()
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from evolution.code import strict_json as js
from evolution.code.campaign_state import CampaignJournal
root = Path(sys.argv[2])
identity = js.loads((root / 'campaign_progress.jsonl').read_bytes().splitlines()[0])['payload']
with CampaignJournal.open(root, identity=identity) as journal:
    try:
        journal.seed_progress(identity['organisms'][0]['organism_id']).start(0)
    except ValueError as error:
        if 'campaign_transition_invalid' not in str(error):
            raise
        print('refused')
    else:
        print('allowed')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script,
         str(Path(__file__).resolve().parents[2]), str(tmp_path)],
        capture_output=True, text=True, timeout=10, env={},
    )
    assert result.returncode == 0, result.stderr
    assert (result.stdout.strip(), path.read_bytes()) == ("refused", before)


def test_unknown_seed_cost_does_not_become_zero_after_ceiling_increase(tmp_path: Path) -> None:
    identity = budgeted_identity()
    oid = identity["organisms"][0]["organism_id"]
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="initial")
        journal.seed_progress(oid).start(0).commit(measured())
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="raised", ceiling_usd=Decimal("1000"))
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            journal.seed_progress(oid).start(1)
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


def test_completed_legacy_organism_without_costs_blocks_next_budgeted_dispatch(tmp_path: Path) -> None:
    identity = budgeted_identity()
    identity["configuration"].update(durability="organism", max_organisms=2)
    first = identity["organisms"][0]
    candidate = dict(first["candidate_identity"], tool_path="tools/second.py", fix_commit="c" * 40)
    second = {
        "organism_id": js.identity("organism", candidate),
        "candidate_identity": candidate, "seeds": [],
    }
    identity["organisms"].append(second)
    identity["stages"] = []
    for member in identity["organisms"]:
        member["seeds"] = [{
            "seed_index": index, "seed_value": 100 + index,
            "seed_id": js.identity("seed", {
                "organism_id": member["organism_id"], "seed_index": index,
                "seed_value": 100 + index, "configuration": identity["configuration"],
            }),
        } for index in range(identity["identity_manifest"]["seed_count"])]
    with open_journal(tmp_path, identity) as journal:
        journal.start_session(session_id="legacy")
        start = journal.append("organism_started", {
            "organism_id": first["organism_id"], "attempt_id": "legacy-first", "retry_of": None,
        })
        journal.append("organism_completed", {
            "organism_id": first["organism_id"], "attempt_id": "legacy-first",
            "start_record_hash": start, "seeds": [True, True], "deploy_reachable": True,
        })
        before = (tmp_path / "campaign_progress.jsonl").read_bytes()
        with pytest.raises(ValueError, match="campaign_transition_invalid"):
            journal.append("organism_started", {
                "organism_id": second["organism_id"], "attempt_id": "legacy-second", "retry_of": None,
            })
        assert (tmp_path / "campaign_progress.jsonl").read_bytes() == before


def test_production_seed_adapter_durably_attributes_observed_callback_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = identity_v2(seed_count=1)
    oid = identity["organisms"][0]["organism_id"]
    ledger = timing.CostLedger()
    monkeypatch.setattr(timing, "COST_LEDGER", ledger)
    monkeypatch.setattr(timing.litellm, "completion_cost", Mock(return_value=0.125))
    env = SimpleNamespace(assert_authoritative=Mock(), write_tool=Mock(), destroy=Mock())
    monkeypatch.setattr(campaign.WorktreeEnv, "create", Mock(return_value=env))
    monkeypatch.setattr(campaign, "_git_show", lambda *args: SOURCE.decode())
    monkeypatch.setattr(campaign, "_failures", Mock(side_effect=[set(), {"test_command.py::test_add"}]))
    monkeypatch.setattr(campaign, "run_code_oracle_gate", Mock(return_value=SimpleNamespace(
        close=Mock(), decision={
            "diagnostic_comparison": {"status": "passed", "reason": "complete_diagnostics"},
        },
    )))

    def repair(*args: object) -> object:
        timing._log_litellm_cost(
            {"model": "fixture", "litellm_call_id": "priced-call"},
            SimpleNamespace(id="priced-call", usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1)),
            None, None,
        )
        return SimpleNamespace(fixed=True)

    with open_journal(tmp_path / "progress", identity) as journal:
        journal.start_session(session_id="adapter-session")
        campaign.run_organism(
            tmp_path, Candidate(TARGET, "tests/test_command.py", "b" * 40, "a" * 40),
            SimpleNamespace(repair=repair), seeds=1, base_python=None,
            require_sandbox=False, seed_progress=journal.seed_progress(oid),
        )
    assert ledger.summary()["total_cost_usd"] == 0.125
    with open_journal(tmp_path / "progress", identity) as journal:
        costs = [row for row in journal.records if row["kind"] == "cost_observed"]
        assert len(costs) == 1, "observed production callback cost did not reach durable attempt history"
        assert costs[0]["payload"]["amount_usd"] == Decimal("0.125")
        terminal = next(row for row in journal.records if row["kind"] == "seed_completed")
        assert costs[0]["sequence"] < terminal["sequence"]
        assert terminal["payload"]["result"]["cost_observation_ids"] == [costs[0]["payload"]["observation_id"]]
