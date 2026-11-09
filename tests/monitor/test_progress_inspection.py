"""Reconstruction observes committed progress without changing journal storage."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.code.campaign_report import OrganismResult
from evolution.composition import monitor_code as composition
from evolution.monitor.attempt import attempt_candidates
from evolution.monitor.queue import build_queue
from evolution.monitor.sentinel import RepairCandidate


def completed_progress(tmp_path: Path) -> tuple[Path, list[RepairCandidate], dict]:
    candidate = RepairCandidate(
        tool_path="tools/one.py", test_path="tests/test_one.py",
        fix_sha="b" * 40, parent_sha="a" * 40, kind="bug_fix",
        committed_at="2026-01-01T00:00:00+00:00",
    )
    candidates = [candidate]
    root = tmp_path / "progress"
    attempt_candidates(
        tmp_path, candidates, build_queue(candidates, repo=str(tmp_path), since_days=90),
        progress_root=root, seeds=1, require_sandbox=False,
        organism_runner=lambda repo, current: OrganismResult(current.tool_path, current.fix_sha, [True]),
    )
    return root, candidates, build_queue(candidates, repo=str(tmp_path), since_days=90)


def test_reconstruction_does_not_create_writer_lockfile(tmp_path: Path) -> None:
    root, candidates, payload = completed_progress(tmp_path)
    lock = root / "campaign_progress.lock"
    lock.unlink()
    before = (root / "campaign_progress.jsonl").read_bytes()
    composition._reconstruct_progress(root, candidates, payload, report=None, persist=None)
    assert payload["candidates"][0]["attempt"]["status"] == "attempted"
    assert not lock.exists(), "observational reconstruction created writer state"
    assert (root / "campaign_progress.jsonl").read_bytes() == before


def test_reconstruction_never_repairs_torn_tail(tmp_path: Path) -> None:
    root, candidates, payload = completed_progress(tmp_path)
    journal = root / "campaign_progress.jsonl"
    journal.write_bytes(journal.read_bytes() + b'{"schema_version":"2","sequence":')
    before = journal.read_bytes()
    try:
        composition._reconstruct_progress(root, candidates, payload, report=None, persist=None)
    except ValueError as error:
        assert "campaign_state_corrupt" in str(error)
    finally:
        assert journal.read_bytes() == before, "inspection changed the interrupted writer's bytes"


@pytest.mark.parametrize("field", ["test_path", "parent_sha"])
def test_full_candidate_identity_is_validated_before_annotation(
    tmp_path: Path, field: str,
) -> None:
    root, candidates, _ = completed_progress(tmp_path)
    replacement = "tests/different.py" if field == "test_path" else "d" * 40
    changed = [replace(candidates[0], **{field: replacement})]
    payload = build_queue(changed, repo=str(tmp_path), since_days=90)
    before = copy.deepcopy(payload)
    persist = Mock()
    with pytest.raises(ValueError, match="campaign_state_incompatible"):
        composition._reconstruct_progress(root, changed, payload, report=None, persist=persist)
    assert payload == before
    persist.assert_not_called()


def test_duplicate_queue_keys_refuse_before_any_annotations(tmp_path: Path) -> None:
    root, candidates, payload = completed_progress(tmp_path)
    payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))
    before = copy.deepcopy(payload)
    persist = Mock()
    with pytest.raises(ValueError, match="campaign_state_incompatible"):
        composition._reconstruct_progress(root, candidates, payload, report=None, persist=persist)
    assert payload == before
    persist.assert_not_called()


@pytest.mark.parametrize("exception_type", [RuntimeError, KeyboardInterrupt])
def test_reconstruction_failure_preserves_original_exception_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exception_type: type[BaseException],
) -> None:
    original = exception_type("campaign interrupted")
    secondary = OSError("queue persistence unavailable")
    monkeypatch.setattr("evolution.code.campaign.run_campaign", Mock(side_effect=original))
    monkeypatch.setattr(composition, "_reconstruct_progress", Mock(side_effect=secondary))
    with pytest.raises(exception_type) as caught:
        composition._attempt_with_progress(
            tmp_path, [], {}, progress_root=tmp_path / "progress", max_cost_usd=None,
            proposer_model=None, base_python=None, seeds=1, max_rounds=1,
            require_sandbox=False, organism_runner=None, persist=None,
        )
    assert caught.value is original


@pytest.mark.parametrize('field,value', [('test', 'tests/other.py'), ('parent_sha', 'd' * 40),
    ('kind', 'dependency_regression'), ('committed_at', '2026-03-01T00:00:00+00:00'), ('score', 999)])
def test_payload_identity_drift_refuses_before_annotations(tmp_path, field, value):
    root, candidates, payload = completed_progress(tmp_path)
    payload['candidates'][0][field] = value
    before = copy.deepcopy(payload)
    persist = Mock()
    with pytest.raises(ValueError, match='campaign_state_incompatible'):
        composition._reconstruct_progress(root, candidates, payload, report=None, persist=persist)
    assert payload == before
    persist.assert_not_called()


@pytest.mark.parametrize('field,value', [('kind', 'dependency_regression'),
                                        ('committed_at', '2026-03-01T00:00:00+00:00')])
def test_candidate_annotation_identity_drift_refuses(tmp_path, field, value):
    root, candidates, _ = completed_progress(tmp_path)
    changed = [replace(candidates[0], **{field: value})]
    payload = build_queue(changed, repo=str(tmp_path), since_days=90)
    with pytest.raises(ValueError, match='campaign_state_incompatible'):
        composition._reconstruct_progress(root, changed, payload, report=None, persist=None)
    assert 'attempt' not in payload['candidates'][0]


def test_reconstruction_preserves_committed_campaign_completion(tmp_path):
    root, candidates, payload = completed_progress(tmp_path)
    composition._reconstruct_progress(root, candidates, payload, report=None, persist=None)
    assert payload['progress']['completed'] is True
