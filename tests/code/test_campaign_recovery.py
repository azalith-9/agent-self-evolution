"""Unversioned legacy ledgers cannot establish compatible seed identities.

Versioned torn-tail recovery is exercised by test_campaign_journal_recovery.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from evolution.code.campaign import run_campaign


@pytest.mark.parametrize('payload', [
    b'{"status":"organism","tool":"tools/x.py","fix_sha":"done","seeds":[true]}\n{',
    b'{"fix_sha":"unfinished', b'{"tool":"tools/x.py",',
    b'{"status":"not_valid","fix_sha":"done"}',
    b'not-json\n{"status":"not_valid","fix_sha":"done"}\n',
    b'{"status":"not_valid","fix_sha":"done"}{"fix_sha":"partial', b'[]\n',
])
def test_legacy_resume_requires_demonstrable_original_identities(tmp_path: Path, payload: bytes) -> None:
    ledger = tmp_path / 'campaign_ledger.jsonl'
    ledger.write_bytes(payload)
    with pytest.raises(ValueError, match='campaign_state_incompatible'):
        run_campaign(tmp_path, output_dir=tmp_path, stages=(), candidates=[], organism_runner=lambda c: None)
    assert ledger.read_bytes() == payload
    assert not (tmp_path / 'campaign_progress.jsonl').exists()
