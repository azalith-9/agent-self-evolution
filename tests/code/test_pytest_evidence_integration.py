"""Exercise the harness-owned plugin with real synthetic pytest sessions."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("source,extra,exit_code,failures,complete", [
    ("def test_ok(): pass\ndef test_bad(): assert False\n", ["--no-summary"], 1,
     {"test_sample.py::test_bad"}, True),
    ("def test_broken(:\n", [], 2, set(), False),
    ("import pytest\n@pytest.fixture\ndef resource():\n yield\n assert False\n"
     "def test_teardown(resource): pass\n", [], 1, {"test_sample.py::test_teardown"}, True),
    ("import pytest\n@pytest.fixture\ndef resource(): pytest.skip('unavailable')\n"
     "def test_setup_skip(resource): pass\n", [], 0, set(), True),
    ("def test_a(): pass\ndef test_b(): pass\n", ["--deselect=test_sample.py::test_b"],
     0, set(), True),
])
def test_plugin_reports_completion_independently_of_stdout(
    tmp_path: Path, source: str, extra: list[str], exit_code: int,
    failures: set[str], complete: bool,
) -> None:
    importlib.import_module("evolution.code.pytest_evidence_plugin")
    from evolution.code.test_evidence import read_test_evidence

    root = Path(__file__).resolve().parents[2]
    (tmp_path / "test_sample.py").write_text(source)
    evidence_path = tmp_path / "evidence.json"
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
           "PYTHONPATH": str(root), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-p", "evolution.code.pytest_evidence_plugin", "--evidence-path", str(evidence_path),
        "--evidence-invocation-id", "plugin-a", *extra, "test_sample.py",
    ], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == exit_code, result.stdout + result.stderr
    payload = json.loads(evidence_path.read_text())
    assert payload["invocation_id"] == "plugin-a"
    evidence = read_test_evidence(evidence_path, invocation_id="plugin-a",
                                  exit_code=result.returncode, cleanup_complete=True)
    assert evidence.complete is complete
    if complete:
        assert set(evidence.failures) == failures
