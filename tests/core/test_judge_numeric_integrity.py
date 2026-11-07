"""Noisy numeric output must remain neutral; LM reuse is instance-scoped."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.core.fitness import LLMJudge
from evolution.core.hermes_provider import ResolvedLM
from evolution.tools.tool_judge import ToolJudge


@pytest.fixture
def judge_boundary(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    lm = Mock()
    monkeypatch.setattr("dspy.LM", lm)
    prediction = Mock(return_value=SimpleNamespace(correctness="0.8", procedure_following="0.8",
                                                  conciseness="0.8", feedback="feedback"))
    monkeypatch.setattr("dspy.ChainOfThought", lambda *args, **kwargs: prediction)
    return lm, prediction


def _judge(kind: str) -> LLMJudge | ToolJudge:
    config = SimpleNamespace(fitness_profile="balanced", get_lm=lambda role:
                             ResolvedLM("openai/test", {}, "explicit"))
    return LLMJudge(config) if kind == "skill" else ToolJudge(config)


def _score(judge: LLMJudge | ToolJudge) -> object:
    if isinstance(judge, LLMJudge):
        return judge.score("task", "rubric", "answer")
    return judge.score("task", "tool", "tool", "reason")


@pytest.mark.parametrize("kind", ["skill", "tool"])
@pytest.mark.parametrize("value", ["NaN", "inf", "-inf"])
def test_nonfinite_judge_output_is_neutral(judge_boundary: tuple[Mock, Mock], kind: str, value: str) -> None:
    _, prediction = judge_boundary
    prediction.return_value = SimpleNamespace(correctness=value, procedure_following=value,
                                              conciseness=value, feedback="noisy")
    result = _score(_judge(kind))
    assert (result.correctness, result.procedure_following, result.conciseness) == (0.5, 0.5, 0.5)


@pytest.mark.parametrize("kind", ["skill", "tool"])
def test_repeated_scores_reuse_instance_lm(judge_boundary: tuple[Mock, Mock], kind: str) -> None:
    lm, _ = judge_boundary
    judge = _judge(kind)
    _score(judge)
    _score(judge)
    assert lm.call_count == 1
    assert lm.call_args.kwargs["engine"] == "litellm"


@pytest.mark.parametrize("kind", ["skill", "tool"])
def test_separate_judges_do_not_share_lm(judge_boundary: tuple[Mock, Mock], kind: str) -> None:
    lm, _ = judge_boundary
    _score(_judge(kind))
    _score(_judge(kind))
    assert lm.call_count == 2
