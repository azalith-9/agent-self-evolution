"""Unexpected failures inside a prompt run leave a durable aborted decision."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from dspy.utils import DummyLM

from evolution.prompts import evolve_prompt_section as mod


def test_unexpected_preflight_failure_persists_aborted_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    target = repo / "agent/prompt_builder.py"
    target.parent.mkdir(parents=True)
    target.write_text("MEMORY_GUIDANCE = 'Save durable facts.'\n")
    original = target.read_bytes()
    suite = tmp_path / "suite.jsonl"
    suite.write_text('\n'.join(json.dumps({"task_id": str(i), "user_message": "m"}) for i in range(4)) + '\n')
    monkeypatch.setenv("SKILL_SOURCES_HERMES_REPO", str(repo))
    monkeypatch.setattr(mod, "instantiate_lm", lambda *args, **kwargs: DummyLM([]))
    monkeypatch.setattr(mod, "saturation_preflight", Mock(side_effect=RuntimeError("synthetic preflight failure")))
    out = tmp_path / "out"
    try:
        mod.evolve_prompt_section(section_name="MEMORY_GUIDANCE", hermes_repo=repo,
                                 tasks_path=suite, output_dir=out,
                                 optimizer_model="openai/test", eval_model="openai/test")
    except RuntimeError as exc:
        assert str(exc) == "synthetic preflight failure"
    decision = json.loads((out / "gate_decision.json").read_text())
    assert decision["decision"] == "aborted"
    assert target.read_bytes() == original
