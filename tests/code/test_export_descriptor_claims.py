"""Descriptor IO with synthetic registered authority, not native acceptance proof."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from evolution.code import semantic_verifier as verifier
from evolution.code import verified_export as exporter
from evolution.code.verified_snapshot import ProtectedSnapshot
from evolution.core.secure_paths import ProtectedRoot
from tests.code.test_verified_snapshot import environment
from tests.code.verification_fixtures import SOURCE, TARGET


@pytest.fixture
def registered_claim(tmp_path: Path) -> tuple:
    snapshot = ProtectedSnapshot.capture(environment(tmp_path), tool_relpath=TARGET)
    destination = tmp_path / 'export'
    (destination / 'tools').mkdir(parents=True, mode=0o700)
    pinned = ProtectedRoot.open(destination)
    parent_fd, leaf = pinned.parent(TARGET)
    context = SimpleNamespace(export_root=destination, current=lambda: True, _destination=pinned,
                              _parent_fd=parent_fd, _leaf=leaf)
    handle = verifier._Authorization()
    verifier._AUTHORIZATIONS[handle] = {
        'snapshot': snapshot, 'context': context, 'state': 'issued', 'pid': os.getpid(),
        'audit_id': 'a' * 64, 'destination_id': 'd' * 64,
    }
    try:
        yield handle, snapshot, destination
    finally:
        verifier.consume(handle)
        os.close(parent_fd)
        pinned.close()
        snapshot.close()


@pytest.mark.parametrize('component', ['root', 'parent'])
def test_claimed_export_stays_on_pinned_destination_after_substitution(
    registered_claim: tuple, monkeypatch: pytest.MonkeyPatch, component: str,
) -> None:
    handle, _, destination = registered_claim
    real_claim = exporter.claim
    retained = destination.with_name('retained') if component == 'root' else destination / 'retained'

    def substitute(*args: object, **kwargs: object) -> dict:
        claim = real_claim(*args, **kwargs)
        selected = destination if component == 'root' else destination / 'tools'
        selected.rename(retained)
        selected.mkdir(mode=0o700)
        if component == 'root':
            (selected / 'tools').mkdir(mode=0o700)
        return claim

    monkeypatch.setattr(exporter, 'claim', substitute)
    receipt = exporter.export_verified(handle, destination_root=destination, target=TARGET)
    installed = retained / TARGET if component == 'root' else retained / 'command.py'
    assert installed.read_bytes() == SOURCE
    assert not (destination / TARGET).exists()
    assert receipt['replacement'] == 'replaced_durable'
    assert receipt['destination_id'] == 'd' * 64
    with pytest.raises(ValueError, match='export_authorization_invalid'):
        exporter.export_verified(handle, destination_root=destination, target=TARGET)


def test_failed_claim_payload_transfer_closes_owned_parent_descriptor(
    registered_claim: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle, snapshot, destination = registered_claim
    real_parent = ProtectedRoot.parent
    owned = []

    def track_parent(self: ProtectedRoot, target: str) -> tuple[int, str]:
        parent, leaf = real_parent(self, target)
        owned.append(parent)
        return parent, leaf

    monkeypatch.setattr(ProtectedRoot, 'parent', track_parent)
    real_current = snapshot.current
    monkeypatch.setattr(snapshot, 'current', lambda: real_current())

    def unavailable() -> bytes:
        raise ValueError('synthetic payload transfer failure')

    monkeypatch.setattr(snapshot, 'read_bytes', unavailable)
    with pytest.raises(ValueError, match='synthetic payload transfer failure'):
        verifier.claim(handle, target=TARGET, destination_root=destination)
    assert owned
    for descriptor in owned:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    with pytest.raises(ValueError, match='export_authorization_invalid'):
        verifier.claim(handle, target=TARGET, destination_root=destination)
