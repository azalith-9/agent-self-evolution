"""Follow-up regressions for invocation identities and strict process observations."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from evolution.core.process import _validate_receipt, run_process
from tests.core.test_execution_contract_amendments import request


def test_separately_constructed_invocation_cannot_replay(tmp_path: Path) -> None:
    assert run_process(request(tmp_path)).exit_code == 0
    assert run_process(request(tmp_path)).error


def test_unresolved_executable_cannot_appear_after_preparation(tmp_path: Path) -> None:
    executable = tmp_path / "late-tool"
    prepared = request(tmp_path, argv=[str(executable)])
    executable.write_text("#!/bin/sh\nprintf late\n")
    executable.chmod(0o700)
    result = run_process(prepared)
    assert result.error and not result.stdout


@pytest.mark.parametrize("via_path", [False, True])
def test_relative_executable_uses_requested_cwd(tmp_path: Path, via_path: bool) -> None:
    executable = tmp_path / "local-tool"
    executable.write_text("#!/bin/sh\nprintf selected\n")
    executable.chmod(0o700)
    prepared = request(tmp_path, argv=["local-tool" if via_path else "./local-tool"], env={"PATH": "."})
    result = run_process(prepared)
    assert result.exit_code == 0 and result.stdout == "selected"


@pytest.mark.parametrize("defect", ["capture", "nested-bool", "cancelled"])
def test_receipt_rejects_incomplete_capture_and_integer_booleans(defect: str) -> None:
    from tests.core.test_supervisor_receipts import receipt

    record = receipt()
    expected = {k: copy.deepcopy(record[k]) for k in (
        "schema_version", "invocation_id", "policy_id", "runtime_id", "snapshot_id", "scope_id", "containment")}
    assert _validate_receipt(record, expected, 0) == record
    if defect == "capture":
        record["capture_complete"] = False
    elif defect == "nested-bool":
        record["containment"]["read_isolated"] = 0
    else:
        record["cancelled"] = True
    with pytest.raises(ValueError):
        _validate_receipt(record, expected, 0)
