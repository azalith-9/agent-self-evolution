"""Persisted or copied descriptions never reconstruct live export authority."""

from __future__ import annotations

import copy
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.code.verification_fixtures import TARGET, component


@pytest.mark.parametrize("kind", ["none", "audit", "lookalike", "copied", "unpickled"])
def test_forged_or_reconstructed_authority_cannot_touch_destination(
    tmp_path: Path, kind: str
) -> None:
    api = component("evolution.code.verified_export")
    (tmp_path / "tools").mkdir()
    target = tmp_path / TARGET
    target.write_bytes(b"original")
    summary = {
        "schema_version": "1",
        "status": "accepted",
        "snapshot_id": "a" * 64,
        "target": TARGET,
        "source_sha256": "b" * 64,
        "mode": 0o750,
    }
    handle = {
        "none": None,
        "audit": summary,
        "lookalike": SimpleNamespace(**summary),
        "copied": copy.deepcopy(summary),
        "unpickled": pickle.loads(pickle.dumps(summary)),
    }[kind]
    with pytest.raises(ValueError, match="export_authorization_invalid"):
        api.export_verified(handle, destination_root=tmp_path, target=TARGET)
    assert target.read_bytes() == b"original"
    assert list((tmp_path / "tools").iterdir()) == [target]
