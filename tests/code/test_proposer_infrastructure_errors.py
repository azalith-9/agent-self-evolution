"""Malformed model output is recoverable; infrastructure failure is not output."""

from __future__ import annotations

from unittest.mock import Mock

import litellm
import pytest

from evolution.code.repair import build_dspy_proposer


@pytest.mark.parametrize("error", [
    litellm.AuthenticationError("rejected", llm_provider="openai", model="test"),
    litellm.RateLimitError("limited", llm_provider="openai", model="test"),
    TimeoutError("transport timeout"),
])
def test_proposer_propagates_infrastructure_failure(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr("dspy.ChainOfThought", lambda *args, **kwargs: Mock(side_effect=error))
    propose = build_dspy_proposer(Mock())
    with pytest.raises(type(error)):
        propose("tools/x.py", "def x(): return 1\n", "failure")


def test_proposer_rejects_malformed_output_without_retrying_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dspy.ChainOfThought", lambda *args, **kwargs:
                        Mock(return_value=type("Prediction", (), {"fixed_source": "def broken("})()))
    assert build_dspy_proposer(Mock())("tools/x.py", "def x(): return 1\n", "failure") is None
