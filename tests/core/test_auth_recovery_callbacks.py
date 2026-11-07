"""Recovered inference auth must clear only its own abort condition."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from unittest.mock import Mock

import litellm
import pytest

from evolution.core.hermes_provider import HermesProviderError
from evolution.core.lm_timing_callback import (
    COST_LEDGER,
    CostCeilingExceeded,
    register_litellm_failure_callback,
)
from evolution.core.nous_lm import NousLM, _reset_state_for_tests


@pytest.fixture(autouse=True)
def isolated_callbacks(monkeypatch: pytest.MonkeyPatch) -> Any:
    COST_LEDGER.reset()
    _reset_state_for_tests()
    for name in ("success_callback", "failure_callback", "_async_success_callback",
                 "_async_failure_callback", "callbacks"):
        monkeypatch.setattr(litellm, name, [])
    yield
    COST_LEDGER.reset()
    _reset_state_for_tests()


def _lm() -> NousLM:
    return NousLM("openai/gpt-4.1-mini", access_token="synthetic-oauth",
                  refresh_token="synthetic-refresh", oauth_expires_at=time.time() + 86400,
                  agent_key="synthetic-old-key", agent_key_expires_at=time.time() + 1800,
                  cache=False, num_retries=0)


def _failure(kwargs: dict, *, model: str | None = None) -> litellm.AuthenticationError:
    copied = dict(kwargs)
    if model is not None:
        copied["model"] = model
        copied["api_key"] = "synthetic-other-identity"
    error = litellm.AuthenticationError("rejected", llm_provider="openai", model=copied["model"])
    now = datetime.now()
    for callback in litellm.failure_callback:
        callback(copied, error, now, now)
    return error


def _response() -> litellm.ModelResponse:
    return litellm.ModelResponse(model="gpt-4.1-mini", choices=[{
        "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3})


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("remaining_abort", [None, "other-auth", "cost"],
                         ids=["recovered", "unrelated-auth", "cost-ceiling"])
def test_recovery_with_registered_callbacks_allows_only_matching_success(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, remaining_abort: str | None,
) -> None:
    lm = _lm()
    register_litellm_failure_callback()
    attempts = []

    def completion(**kwargs: Any) -> litellm.ModelResponse:
        attempts.append(kwargs["api_key"])
        if len(attempts) == 1:
            raise _failure(kwargs)
        if len(attempts) == 2:
            if remaining_abort == "other-auth":
                _failure(kwargs, model="openai/unrelated-model")
            if remaining_abort == "cost":
                COST_LEDGER.set_ceiling(0.1)
                COST_LEDGER.record_agent_cost(0.2)
        return _response()

    async def acompletion(**kwargs: Any) -> litellm.ModelResponse:
        return completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "acompletion", acompletion)

    def remint(**kwargs: Any) -> None:
        lm._shared_state.agent_key = "synthetic-refreshed-key"
        lm._shared_state.agent_key_expires_at = time.time() + 1800

    monkeypatch.setattr(lm, "_mint_agent_key", remint)

    def invoke() -> object:
        return asyncio.run(lm.acall("hi")) if asynchronous else lm("hi")

    assert invoke() == ["ok"]
    if remaining_abort == "other-auth":
        with pytest.raises(HermesProviderError, match="unrelated-model"):
            invoke()
    elif remaining_abort == "cost":
        with pytest.raises(CostCeilingExceeded):
            invoke()
    else:
        assert COST_LEDGER.get_auth_abort_message() is None
        assert invoke() == ["ok"]
        assert attempts == ["synthetic-old-key", "synthetic-refreshed-key", "synthetic-refreshed-key"]


def test_terminal_second_rejection_remains_an_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    lm = _lm()
    register_litellm_failure_callback()

    def reject(**kwargs: Any) -> None:
        raise _failure(kwargs)

    monkeypatch.setattr(litellm, "completion", reject)
    monkeypatch.setattr(lm, "_mint_agent_key", Mock())
    with pytest.raises(HermesProviderError):
        lm("hi")
    assert COST_LEDGER.get_auth_abort_message() is not None
