"""Recover only incomplete final syntax, without sacrificing committed results."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.code.test_campaign_state import open_journal
from tests.code.verification_fixtures import campaign_identity, component, seed_result, start_attempt


def committed(root: Path) -> tuple[dict, bytes]:
    identity = campaign_identity()
    with open_journal(root, identity) as journal:
        start_attempt(journal.seed_progress(identity["organisms"][0]["organism_id"]), 0, "complete")
        journal.seed_progress(identity["organisms"][0]["organism_id"]).commit(
            0, attempt_id="complete", result=seed_result()
        )
    return identity, (root / "campaign_progress.jsonl").read_bytes()


@pytest.mark.parametrize("tail", [b"{", b'{"kind":"seed_completed",', b'{"payload":{"reason":"par'])
def test_torn_tail_is_preserved_before_truncation(tmp_path: Path, tail: bytes) -> None:
    identity, prefix = committed(tmp_path)
    journal_path = tmp_path / "campaign_progress.jsonl"
    journal_path.write_bytes(prefix + tail)
    with open_journal(tmp_path, identity) as journal:
        assert dict(journal.seed_progress(identity["organisms"][0]["organism_id"]).completed) == {
            0: seed_result()
        }
    assert journal_path.read_bytes() == prefix
    preserved = tmp_path / ("campaign_progress.torn." + hashlib.sha256(tail).hexdigest() + ".bin")
    assert preserved.read_bytes() == tail
    assert preserved.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "tail",
    [
        b"{}",
        b"[]",
        b'{"schema_version":"2"}',
        b'{"x":1,"x":2}',
        b"{}{}",
        b'"\xff"',
        b'{"cost":NaN}',
        b'{"x":oops}',
    ],
)
def test_complete_bad_final_record_is_not_treated_as_torn(tmp_path: Path, tail: bytes) -> None:
    identity, prefix = committed(tmp_path)
    path = tmp_path / "campaign_progress.jsonl"
    path.write_bytes(prefix + tail)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="campaign_state_corrupt"):
        with open_journal(tmp_path, identity):
            pytest.fail("complete malformed record was recovered")
    assert path.read_bytes() == before


def test_valid_record_missing_only_newline_is_retained(tmp_path: Path) -> None:
    identity, complete = committed(tmp_path)
    path = tmp_path / "campaign_progress.jsonl"
    path.write_bytes(complete[:-1])
    with open_journal(tmp_path, identity) as journal:
        assert list(journal.seed_progress(identity["organisms"][0]["organism_id"]).completed) == [0]
    assert path.read_bytes() == complete


@pytest.mark.parametrize("mutation", ["interior", "digest", "duplicate", "reorder"])
def test_broken_chain_and_interior_corruption_leave_progress_intact(
    tmp_path: Path, mutation: str
) -> None:
    identity, complete = committed(tmp_path)
    lines = complete.splitlines(keepends=True)
    if mutation == "interior":
        payload = lines[0] + b"invalid\n" + lines[1]
    elif mutation == "digest":
        payload = complete.replace(b"fixture_comparison", b"forged_comparison")
    elif mutation == "duplicate":
        payload = complete + lines[1]
    else:
        payload = lines[1] + lines[0]
    path = tmp_path / "campaign_progress.jsonl"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="campaign_state_corrupt"):
        with open_journal(tmp_path, identity):
            pytest.fail("invalid chain accepted")
    assert path.read_bytes() == payload


def test_reopen_requires_a_successful_durability_barrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    identity, complete = committed(tmp_path)
    inode = (tmp_path / "campaign_progress.jsonl").stat().st_ino
    real_fsync = os.fsync

    def fail_barrier(fd: int) -> None:
        if os.fstat(fd).st_ino == inode:
            raise OSError("synthetic unavailable durability")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_barrier)
    with pytest.raises(ValueError, match="campaign_persistence_uncertain"):
        with open_journal(tmp_path, identity):
            pytest.fail("unsynchronized progress acknowledged")
    assert (tmp_path / "campaign_progress.jsonl").read_bytes() == complete


def test_valid_hash_does_not_make_malformed_completion_resumable(tmp_path: Path) -> None:
    identity, complete = committed(tmp_path)
    lines = complete.splitlines(keepends=True)
    parser = component("evolution.code.strict_json")
    edited = lines[-1].replace(b"passed", b"inconclusive")
    document = parser.loads(edited)
    previous_digest = document.pop("record_hash")
    digest = parser.identity("journal-record", document)
    edited = edited.replace(previous_digest.encode(), digest.encode())
    path = tmp_path / "campaign_progress.jsonl"
    path.write_bytes(b"".join(lines[:-1]) + edited)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="campaign_state_corrupt"):
        with open_journal(tmp_path, identity):
            pytest.fail("malformed but correctly hashed completion accepted")
    assert path.read_bytes() == before
