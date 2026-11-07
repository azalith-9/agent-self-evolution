"""Hermes receives the selected provider arrangement without ambient credentials."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.core.lm_timing_callback import CostLedger
from evolution.core.process import ProcessResult
from evolution.validation.agent_runner import TaskRunContext
from evolution.validation.hermes_runner import HermesAgentRunner


@pytest.mark.parametrize("provider,supplied,expected", [
    ("openai", {"OPENAI_API_KEY": "synthetic-openai"}, {"OPENAI_API_KEY"}),
    ("anthropic", {"ANTHROPIC_API_KEY": "synthetic-anthropic"}, {"ANTHROPIC_API_KEY"}),
    ("gemini", {"GOOGLE_API_KEY": "synthetic-google-alias"}, {"GOOGLE_API_KEY"}),
    ("gemini", {"GEMINI_API_KEY": "synthetic-first", "GOOGLE_API_KEY": "synthetic-second"},
     {"GEMINI_API_KEY"}),
    ("zai", {"GLM_API_KEY": "synthetic-glm-alias"}, {"GLM_API_KEY"}),
    ("bedrock", {"AWS_ACCESS_KEY_ID": "synthetic-access", "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
                 "AWS_SESSION_TOKEN": "synthetic-session", "AWS_REGION": "us-east-1"},
     {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION"}),
    ("ollama", {}, set()),
])
def test_selected_provider_authentication_is_deliberate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str,
    supplied: dict[str, str], expected: set[str],
) -> None:
    sensitive = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                 "GLM_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "AWS_REGION", "GH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"}
    for key in sensitive:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GH_TOKEN", "synthetic-unrelated-github")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "synthetic-unrelated-claude")
    if provider != "openai":
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unrelated-openai")
    for key, value in supplied.items():
        monkeypatch.setenv(key, value)
    config = tmp_path / "config.yaml"
    config.write_text(f"model:\n  provider: {provider}\n  default: synthetic-model\n")
    launch = Mock(return_value=ProcessResult(
        exit_code=0, stdout="", stderr="", timed_out=False, cleanup_complete=True,
        invocation_id="synthetic-agent", sandboxed=False,
    ))
    monkeypatch.setattr("evolution.validation.hermes_runner.run_process", launch)
    runner = HermesAgentRunner(hermes_command=sys.executable, user_config_path=config,
                               require_sandbox=False, cost_ledger=CostLedger())
    runner.run(TaskRunContext("synthetic task", tmp_path))
    child = launch.call_args.args[0].env
    assert {key: child[key] for key in sensitive if key in child} == {
        key: supplied[key] for key in expected
    }
