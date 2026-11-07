"""Runner subprocesses receive explicit credentials and redacted diagnostics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.validation.process_stub import process_stub

from evolution.core.lm_timing_callback import CostLedger
from evolution.validation.agent_runner import TaskRunContext
from evolution.validation.claude_runner import ClaudeCodeAgentRunner
from evolution.validation.hermes_runner import HermesAgentRunner


@pytest.mark.parametrize("backend", ["claude", "hermes"])
def test_runner_drops_unrelated_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    for key in ("GH_TOKEN", "HF_TOKEN", "AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK", "BASH_ENV"):
        monkeypatch.setenv(key, "synthetic-host-canary")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "synthetic-selected-token")
    launch = Mock(return_value=subprocess.CompletedProcess([], 0,
                  json.dumps({"type": "result", "result": "ok", "total_cost_usd": 0.1}), ""))
    monkeypatch.setattr(f"evolution.validation.{backend}_runner.run_process", process_stub(launch))
    if backend == "claude":
        runner = ClaudeCodeAgentRunner(claude_command="/synthetic/missing-claude", require_sandbox=False,
                                       cost_ledger=CostLedger())
    else:
        runner = HermesAgentRunner(hermes_command="/synthetic/missing-hermes", user_config_path=tmp_path / "no-config",
                                   cost_ledger=CostLedger())
    runner.run(TaskRunContext("message", tmp_path))
    child = launch.call_args.kwargs["env"]
    leaked = sorted(set(child).intersection({"GH_TOKEN", "HF_TOKEN", "AWS_SECRET_ACCESS_KEY",
                                           "SSH_AUTH_SOCK", "BASH_ENV"}))
    assert leaked == []
    if backend == "claude":
        assert child["CLAUDE_CODE_OAUTH_TOKEN"] == "synthetic-selected-token"


def test_claude_does_not_persist_raw_stderr_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "synthetic-oauth-secret-canary"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", secret)
    monkeypatch.setattr("evolution.validation.claude_runner.run_process", process_stub(Mock(return_value=
                        subprocess.CompletedProcess([], 1, "", f"Authorization: Bearer {secret}"))))
    runner = ClaudeCodeAgentRunner(claude_command="/synthetic/missing-claude", require_sandbox=False,
                                   cost_ledger=CostLedger())
    result = runner.run(TaskRunContext("message", tmp_path))
    assert result.error is not None
    assert secret not in result.error


def test_context_cannot_override_private_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launch = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("evolution.validation.claude_runner.run_process", process_stub(launch))
    runner = ClaudeCodeAgentRunner(claude_command="/synthetic/missing-claude", require_sandbox=False,
                                   cost_ledger=CostLedger())
    with pytest.raises(ValueError):
        runner.run(TaskRunContext("message", tmp_path, extra_env={"HOME": "/synthetic-host-home"}))
    launch.assert_not_called()
