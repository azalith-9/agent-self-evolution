"""Explicit runtime selection cannot be satisfied by candidate configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.code.verification_fixtures import component, protected_json


@pytest.mark.parametrize(
    "mutation",
    [
        "relative_interpreter",
        "digest_mismatch",
        "whole_host",
        "wrong_policy",
        "wrong_backend",
        "numeric_version",
        "symlink_config",
        "missing_runtime",
    ],
)
def test_unsafe_registry_never_falls_back_to_ambient_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    api = component("evolution.code.verification_runtime")
    interpreter = str(Path(sys.executable).resolve())
    registry = {
        "schema_version": "1",
        "runtimes": {
            "independent-python": {
                "interpreter": interpreter,
                "interpreter_sha256": "0" * 64,
                "runtime_roots": [str(tmp_path / "runtime")],
                "runtime_manifest_sha256": "1" * 64,
                "backend": "bubblewrap",
                "policy": "python-json-command-v1",
            }
        },
    }
    entry = registry["runtimes"]["independent-python"]
    if mutation == "relative_interpreter":
        entry["interpreter"] = "python"
    elif mutation == "whole_host":
        entry["runtime_roots"] = ["/"]
    elif mutation == "wrong_policy":
        entry["policy"] = "writable-repair"
    elif mutation == "wrong_backend":
        entry["backend"] = "unconfined"
    elif mutation == "numeric_version":
        registry["schema_version"] = 1
    config = protected_json(tmp_path / "registry.json", registry)
    if mutation == "symlink_config":
        alias = tmp_path / "alias.json"
        alias.symlink_to(config)
        config = alias
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    runtime_id = "missing" if mutation == "missing_runtime" else "independent-python"
    with pytest.raises(ValueError, match="verification_runtime_untrusted"):
        api.resolve_runtime(config, runtime_id=runtime_id)


def test_missing_registry_cannot_be_replaced_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = component("evolution.code.verification_runtime")
    monkeypatch.setenv("VERIFICATION_RUNTIME_CONFIG", str(tmp_path / "candidate.json"))
    with pytest.raises(ValueError, match="verification_runtime_untrusted"):
        api.resolve_runtime(tmp_path / "absent.json", runtime_id="independent-python")
