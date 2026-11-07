"""Requests validate boundaries without exposing credential-bearing inputs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from evolution.core.execution import ExecutionPolicy, ExecutionRequest


def request(tmp_path: Path, **changes: object) -> ExecutionRequest:
    arguments = dict(
        argv=[sys.executable, "-c", "pass"], cwd=tmp_path, env={},
        policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path], required=False),
        timeout_seconds=1, cleanup_timeout_seconds=1, invocation_id="boundary-request",
    )
    arguments.update(changes)
    return ExecutionRequest(**arguments)


def test_empty_argument_after_executable_reaches_child_unchanged(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    result = run_process(request(tmp_path, argv=[sys.executable, "-c",
                         "import sys; print(repr(sys.argv[1:]))", ""]))
    assert (result.exit_code, result.stdout.strip()) == (0, "['']")


@pytest.mark.parametrize("field", ["timeout_seconds", "cleanup_timeout_seconds"])
def test_boolean_is_not_a_deadline(tmp_path: Path, field: str) -> None:
    with pytest.raises(ValueError):
        request(tmp_path, **{field: True})


@pytest.mark.parametrize("identity", ["request\0suffix", " \t "])
def test_invalid_invocation_identity_fails_at_construction(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ValueError):
        request(tmp_path, invocation_id=identity)


@pytest.mark.parametrize("location", ["argv", "env"])
def test_request_repr_excludes_sensitive_inputs(tmp_path: Path, location: str) -> None:
    secret = "synthetic-request-secret-canary"
    change = {"argv": [sys.executable, "--token", secret]} if location == "argv" else {
        "env": {"OPENAI_API_KEY": secret, "CUSTOM_CREDENTIAL": secret},
    }
    assert secret not in repr(request(tmp_path, **change))


def test_invalid_environment_name_is_not_echoed_in_error(tmp_path: Path) -> None:
    from evolution.core.execution import prepare_environment

    secret = "synthetic-key-name-secret-canary"
    with pytest.raises(ValueError) as caught:
        prepare_environment(kind="candidate", parent={}, home=tmp_path, tmpdir=tmp_path,
                            extra_env={secret: "ignored"})
    assert secret not in str(caught.value)


def test_reusing_consumed_invocation_does_not_execute_again(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    marker = tmp_path / "runs"
    prepared = request(tmp_path, argv=[sys.executable, "-c",
                       "from pathlib import Path; "
                       f"p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x')"])
    first = run_process(prepared)
    assert first.exit_code == 0 and first.cleanup_complete
    second = run_process(prepared)
    assert second.error and marker.read_text() == "x"


def test_runtime_replacement_invalidates_prepared_request(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    executable = tmp_path / "selected-tool"
    executable.write_text("#!/bin/sh\nprintf original\n")
    executable.chmod(0o700)
    prepared = request(tmp_path, argv=[str(executable)])
    executable.write_text("#!/bin/sh\nprintf replaced\n")
    result = run_process(prepared)
    assert result.error and "replaced" not in result.stdout


def test_selected_environment_credentials_are_redacted_automatically(tmp_path: Path) -> None:
    from evolution.core.process import run_process

    secret = "synthetic-automatic-redaction-canary"
    prepared = request(tmp_path, argv=[sys.executable, "-c",
                       "import os; print(os.environ['OPENAI_API_KEY'])"],
                       env={"OPENAI_API_KEY": secret})
    result = run_process(prepared)
    assert result.exit_code == 0
    assert secret not in repr(result)
