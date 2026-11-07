"""Identity-level diagnostics distinguish complete observations from required passes."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evolution.code.test_evidence import read_test_evidence


NODE = "test_sample.py::test_required"


def phase(outcome: str = "passed", *, wasxfail: bool = False) -> dict:
    return {"outcome": outcome, "wasxfail": wasxfail}


@pytest.fixture
def record() -> dict:
    return dict(
        schema_version="2", invocation_id="diagnostic-request", collected=[NODE],
        selected=[NODE], deselected=[], executed=[NODE], skipped=[], failures=[],
        collection_errors=[], collection_finished=True, session_finished=True, exit_code=0,
        items=[dict(nodeid=NODE, setup=phase(), call=phase(), teardown=phase())],
    )


def read(tmp_path: Path, record: dict, *, required: tuple[str, ...] = ()) -> object:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(record))
    kwargs = {"required_nodeids": required} if required else {}
    return read_test_evidence(path, invocation_id="diagnostic-request",
                              exit_code=record["exit_code"], cleanup_complete=True, **kwargs)


@pytest.mark.parametrize("failed", [False, True])
def test_schema_two_preserves_complete_pass_and_failure_observations(
    tmp_path: Path, record: dict, failed: bool,
) -> None:
    if failed:
        record.update(exit_code=1, failures=[NODE])
        record["items"][0]["call"] = phase("failed")
    evidence = read(tmp_path, record)
    assert evidence.complete and evidence.error is None
    assert evidence.failures == (frozenset({NODE}) if failed else frozenset())


@pytest.mark.parametrize("omission", ["setup-skip", "call-skip", "xfail", "deselected", "absent"])
def test_accounted_omission_is_visible_without_becoming_required_execution(
    tmp_path: Path, record: dict, omission: str,
) -> None:
    if omission in {"deselected", "absent"}:
        record.update(selected=[], executed=[], items=[])
        record["deselected"] = [NODE] if omission == "deselected" else []
        record["collected"] = [NODE] if omission == "deselected" else []
    else:
        record["skipped"] = [NODE]
        if omission == "setup-skip":
            record["items"][0].update(setup=phase("skipped"), call=phase("not_run"))
        else:
            record["items"][0]["call"] = phase("skipped", wasxfail=omission == "xfail")
    evidence = read(tmp_path, record, required=(NODE,))
    assert evidence.missing == frozenset({NODE})
    assert evidence.failures == frozenset()


@pytest.mark.parametrize("defect", [
    "duplicate-item", "selected-deselected-overlap", "missing-teardown", "call-after-skip",
    "invented-execution", "invented-failure", "boolean-exit", "unknown-field",
])
def test_schema_two_rejects_contradictory_lifecycle(
    tmp_path: Path, record: dict, defect: str,
) -> None:
    assert read(tmp_path, record).complete, "valid schema-two control must be supported"
    if defect == "duplicate-item":
        record["items"].append(copy.deepcopy(record["items"][0]))
    elif defect == "selected-deselected-overlap":
        record["deselected"] = [NODE]
    elif defect == "missing-teardown":
        record["items"][0]["teardown"] = phase("not_run")
    elif defect == "call-after-skip":
        record["items"][0]["setup"] = phase("skipped")
        record["skipped"] = [NODE]
    elif defect == "invented-execution":
        record["executed"] = ["test_sample.py::test_other"]
    elif defect == "invented-failure":
        record.update(failures=[NODE], exit_code=1)
    elif defect == "boolean-exit":
        record["exit_code"] = False
    elif defect == "unknown-field":
        record["independently_verified"] = True
    assert not read(tmp_path, record).complete


def test_unexpected_and_duplicate_identities_are_retained(tmp_path: Path, record: dict) -> None:
    record["items"].append(copy.deepcopy(record["items"][0]))
    evidence = read(tmp_path, record, required=("test_reviewed.py::test_expected",))
    assert (evidence.missing, evidence.unexpected, evidence.duplicates) == (
        frozenset({"test_reviewed.py::test_expected"}), frozenset({NODE}), frozenset({NODE}),
    )


@pytest.mark.parametrize("defect", ["duplicate-key", "boolean-exit", "unknown-field"])
def test_legacy_diagnostics_do_not_bypass_strict_decoding(tmp_path: Path, defect: str) -> None:
    payload = dict(schema_version="1", invocation_id="diagnostic-request", collected=1,
                   deselected=0, collection_errors=[], session_finished=True, exit_code=0,
                   items=[dict(nodeid=NODE, setup="passed", call="passed", teardown="passed")])
    if defect == "boolean-exit":
        payload["exit_code"] = False
    elif defect == "unknown-field":
        payload["deployment_authorized"] = True
    raw = json.dumps(payload)
    if defect == "duplicate-key":
        raw = raw[:-1] + ', "exit_code": 0}'
    path = tmp_path / "legacy.json"
    path.write_text(raw)
    assert not read_test_evidence(path, invocation_id="diagnostic-request", exit_code=0,
                                  cleanup_complete=True).complete


@pytest.mark.parametrize("extra,skipped,deselected", [
    ([], ["test_sample.py::test_omitted"], []),
    (["--deselect=test_sample.py::test_omitted"], [], ["test_sample.py::test_omitted"]),
    (["-k", "omitted"], ["test_sample.py::test_omitted"], [NODE]),
])
def test_real_plugin_records_exact_selected_skipped_and_deselected_ids(
    tmp_path: Path, extra: list[str], skipped: list[str], deselected: list[str],
) -> None:
    (tmp_path / "test_sample.py").write_text(
        "import pytest\ndef test_required(): pass\n"
        "@pytest.mark.skip(reason='synthetic capability unavailable')\ndef test_omitted(): pass\n"
    )
    path = tmp_path / "evidence.json"
    child_env = dict(PATH=os.defpath, HOME=str(tmp_path), TMPDIR=str(tmp_path),
                     PYTHONPATH=str(Path(__file__).resolve().parents[2]),
                     PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p",
        "evolution.code.pytest_evidence_plugin", "--evidence-path", str(path),
        "--evidence-invocation-id", "plugin-identities", *extra, "test_sample.py",
    ], cwd=tmp_path, env=child_env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "2"
    assert payload["collected"] == [NODE, "test_sample.py::test_omitted"]
    assert payload["deselected"] == deselected
    assert payload["skipped"] == skipped
    assert read_test_evidence(path, invocation_id="plugin-identities", exit_code=0,
                              cleanup_complete=True).complete
