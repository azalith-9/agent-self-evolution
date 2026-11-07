"""Invocation-bound evidence distinguishes complete failures from partial output.

The proposed internal schema records each selected item's setup/call/teardown,
collection errors, deselections, session finish, process status, and cleanup.
It does not claim resistance to a deliberately malicious in-process pytest plugin.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest


@pytest.fixture
def complete() -> dict:
    return {"schema_version": "1", "invocation_id": "invocation-a", "collected": 1,
            "deselected": 0, "collection_errors": [], "session_finished": True,
            "exit_code": 0, "items": [{"nodeid": "test_x.py::test_x",
             "setup": "passed", "call": "passed", "teardown": "passed"}]}


def _read(tmp_path: Path, payload: dict, *, exit_code: int | None = 0,
          cleanup_complete: bool = True) -> object:
    from evolution.code.test_evidence import read_test_evidence

    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload))
    return read_test_evidence(path, invocation_id="invocation-a", exit_code=exit_code,
                              cleanup_complete=cleanup_complete)


def test_complete_pass_remains_authoritative(tmp_path: Path, complete: dict) -> None:
    evidence = _read(tmp_path, complete)
    assert evidence.complete
    assert evidence.failures == frozenset()


def test_complete_assertion_failure_is_authoritative(tmp_path: Path, complete: dict) -> None:
    complete["items"][0]["call"] = "failed"
    complete["exit_code"] = 1
    evidence = _read(tmp_path, complete, exit_code=1)
    assert evidence.complete
    assert evidence.failures == frozenset({"test_x.py::test_x"})


@pytest.mark.parametrize("change", [
    {"invocation_id": "stale"}, {"session_finished": False}, {"collected": 2},
    {"collection_errors": ["test_b.py"]}, {"exit_code": 1}, {"items": []},
])
def test_incomplete_or_contradictory_evidence_refuses_success(tmp_path: Path, complete: dict, change: dict) -> None:
    complete.update(change)
    assert not _read(tmp_path, complete).complete


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_missing_item_phase_refuses_success(tmp_path: Path, complete: dict, phase: str) -> None:
    del complete["items"][0][phase]
    assert not _read(tmp_path, complete).complete


def test_duplicate_nodeids_cannot_hide_unexecuted_item(tmp_path: Path, complete: dict) -> None:
    complete["items"].append(copy.deepcopy(complete["items"][0]))
    complete["collected"] = 2
    assert not _read(tmp_path, complete).complete


def test_unverified_process_cleanup_invalidates_evidence(tmp_path: Path, complete: dict) -> None:
    assert not _read(tmp_path, complete, cleanup_complete=False).complete


@pytest.mark.parametrize("exit_code", [None, -9, 2, 3, 4, 5])
def test_abnormal_process_status_invalidates_evidence(tmp_path: Path, complete: dict, exit_code: int | None) -> None:
    complete["exit_code"] = exit_code
    assert not _read(tmp_path, complete, exit_code=exit_code).complete


def test_malformed_evidence_fails_closed(tmp_path: Path) -> None:
    from evolution.code.test_evidence import read_test_evidence

    path = tmp_path / "evidence.json"
    path.write_text('{"invocation_id":')
    assert not read_test_evidence(path, invocation_id="invocation-a", exit_code=0,
                                  cleanup_complete=True).complete
