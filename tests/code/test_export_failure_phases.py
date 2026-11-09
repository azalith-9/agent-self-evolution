"""Exporter IO after an injected claim, not proof of authorization or containment."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.code import verified_export as api
from evolution.code.verified_snapshot import ProtectedSnapshot
from tests.code.test_verified_snapshot import environment
from tests.code.verification_fixtures import SOURCE, TARGET


@pytest.fixture
def claimed_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    env = environment(tmp_path)
    snapshot = ProtectedSnapshot.capture(env, tool_relpath=TARGET)
    destination = tmp_path / "export"
    (destination / "tools").mkdir(parents=True, mode=0o700)
    (destination / TARGET).write_bytes(b"original")
    authorization = object()
    claim = Mock(return_value={
        "snapshot": snapshot, "audit_id": "a" * 64, "assessment_id": "a" * 64,
        "destination_id": "d" * 64, "destination_root": destination,
    })
    consume = Mock()
    monkeypatch.setattr(api, "claim", claim)
    monkeypatch.setattr(api, "consume", consume)
    try:
        yield authorization, snapshot, destination, claim, consume
    finally:
        snapshot.close()


def test_success_receipt_confirms_exact_retained_bytes_mode_and_durability(
    claimed_payload: tuple,
) -> None:
    authorization, snapshot, destination, claim, consume = claimed_payload
    receipt = api.export_verified(authorization, destination_root=destination, target=TARGET)
    claim.assert_called_once()
    consume.assert_called_once_with(authorization)
    assert (destination / TARGET).read_bytes() == SOURCE
    assert stat.S_IMODE((destination / TARGET).stat().st_mode) == snapshot.mode
    assert (receipt["schema_version"], receipt["status"], receipt["replacement"], receipt["phase"]) == (
        "2", "succeeded", "replaced_durable", "complete"
    )


@pytest.mark.parametrize(
    "failure,expected_replacement,expected_bytes",
    [
        ("file_sync", "not_replaced", b"original"),
        ("replace", "replacement_unknown", b"original"),
        ("directory_sync", "replaced_durability_uncertain", SOURCE),
        ("verify", "replaced_durability_uncertain", SOURCE),
    ],
)
def test_identified_export_failure_reports_replacement_phase_and_consumes_claim(
    claimed_payload: tuple, monkeypatch: pytest.MonkeyPatch,
    failure: str, expected_replacement: str, expected_bytes: bytes,
) -> None:
    authorization, snapshot, destination, claim, consume = claimed_payload
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        if (failure == "directory_sync" and directory) or (failure == "file_sync" and not directory):
            raise OSError("synthetic synchronization failure")
        real_fsync(fd)

    monkeypatch.setattr(api.os, "fsync", fsync)
    if failure == "replace":
        monkeypatch.setattr(api.os, "replace", Mock(side_effect=OSError("rename outcome unknown")))
    if failure == "verify":
        monkeypatch.setattr(api.ProtectedRoot, "read_with_mode", Mock(side_effect=OSError("verification unavailable")))
    with pytest.raises(api.ExportError) as raised:
        api.export_verified(authorization, destination_root=destination, target=TARGET)
    claim.assert_called_once()
    consume.assert_called_once_with(authorization)
    assert (destination / TARGET).read_bytes() == expected_bytes
    assert [p.name for p in (destination / "tools").iterdir()] == ["command.py"]
    receipt = raised.value.receipt
    assert (receipt["schema_version"], receipt["status"], receipt["replacement"], receipt["phase"]) == (
        "2", "failed", expected_replacement, failure
    )
    assert receipt["source_sha256"] == snapshot.source_sha256


def test_cancellation_propagates_after_consuming_identified_claim(
    claimed_payload: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, snapshot, destination, claim, consume = claimed_payload
    monkeypatch.setattr(api.os, "replace", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        api.export_verified(authorization, destination_root=destination, target=TARGET)
    consume.assert_called_once_with(authorization)
    assert (destination / TARGET).read_bytes() == b"original"
    assert [p.name for p in (destination / "tools").iterdir()] == ["command.py"]


def test_export_receipt_retains_assessment_and_destination_bindings(claimed_payload: tuple) -> None:
    authorization, _, destination, _, _ = claimed_payload
    receipt = api.export_verified(authorization, destination_root=destination, target=TARGET)
    assert (receipt.get("assessment_id"), receipt.get("destination_id")) == ("a" * 64, "d" * 64)
