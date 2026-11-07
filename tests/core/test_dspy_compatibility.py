"""Exercise provider routing and callbacks through real DSPy execution."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, Mock

import litellm
import pytest
from dspy.utils.exceptions import LMTimeoutError

from evolution.core.codex_lm import CodexLM
from evolution.core.hermes_provider import HermesProviderError, ResolvedLM, instantiate_lm
from evolution.core.lm_timing_callback import (
    COST_LEDGER,
    CostCeilingExceeded,
    _alog_litellm_cost,
    register_litellm_cost_callback,
    register_litellm_failure_callback,
)
from evolution.core.nous_lm import NousLM, _reset_state_for_tests


@pytest.fixture(autouse=True)
def _isolate_callbacks(monkeypatch: pytest.MonkeyPatch) -> Any:
    COST_LEDGER.reset()
    _reset_state_for_tests()
    for name in (
        "success_callback", "failure_callback", "_async_success_callback",
        "_async_failure_callback", "callbacks",
    ):
        monkeypatch.setattr(litellm, name, [])
    yield
    COST_LEDGER.reset()
    _reset_state_for_tests()


def _nous_lm() -> NousLM:
    return NousLM(
        "openai/gpt-4.1-mini", access_token="oauth-test", refresh_token="refresh-test",
        oauth_expires_at=time.time() + 86400, agent_key="initial-key",
        agent_key_expires_at=time.time() + 1800,
        cache=False, num_retries=0, request_timeout=2,
    )


def _response() -> litellm.ModelResponse:
    return litellm.ModelResponse(
        model="gpt-4.1-mini",
        choices=[{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("rejected_again", [False, True])
def test_nous_remints_after_dspy_wraps_litellm_auth_error(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, rejected_again: bool,
) -> None:
    lm = _nous_lm()
    error = litellm.AuthenticationError("rejected", llm_provider="openai", model=lm.model)
    completion = (AsyncMock if asynchronous else Mock)(
        side_effect=[error, error if rejected_again else _response()],
    )
    monkeypatch.setattr(litellm, "acompletion" if asynchronous else "completion", completion)
    mint = Mock()

    def remint(*, allow_oauth_retry: bool) -> None:
        mint(allow_oauth_retry=allow_oauth_retry)
        lm._shared_state.agent_key = "reminted-key"

    monkeypatch.setattr(lm, "_mint_agent_key", remint)

    def invoke() -> Any:
        if asynchronous:
            return asyncio.run(asyncio.wait_for(lm.acall("hi"), timeout=3))
        return lm("hi")

    if rejected_again:
        with pytest.raises(HermesProviderError, match="freshly-minted"):
            invoke()
    else:
        assert invoke() == ["ok"]
    mint.assert_called_once_with(allow_oauth_retry=True)
    assert [call.kwargs["api_key"] for call in completion.call_args_list] == [
        "initial-key", "reminted-key",
    ]


def test_custom_and_copied_lms_keep_litellm_engine() -> None:
    nous = _nous_lm()
    codex = CodexLM("gpt-5-codex", access_token="test-token")
    for lm in (nous, codex):
        copied = lm.copy(request_timeout=60, num_retries=2)
        assert copied.engine == "litellm"
        assert copied._shared_state is lm._shared_state
        assert copied.kwargs["request_timeout"] == 60
        assert copied.num_retries == 2


@pytest.mark.parametrize("asynchronous", [False, True])
def test_timeout_propagates_from_litellm_with_bounded_retries(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool,
) -> None:
    lm = instantiate_lm(
        ResolvedLM("openai/gpt-4.1-mini", {"api_key": "test"}, "test"),
        cache=False, request_timeout=2, num_retries=0,
    )
    error = litellm.Timeout("timed out", model=lm.model, llm_provider="openai")
    completion = (AsyncMock if asynchronous else Mock)(side_effect=error)
    monkeypatch.setattr(litellm, "acompletion" if asynchronous else "completion", completion)
    with pytest.raises(LMTimeoutError):
        if asynchronous:
            asyncio.run(asyncio.wait_for(lm.acall("hi"), timeout=3))
        else:
            lm("hi")
    completion.assert_called_once()
    assert completion.call_args.kwargs["request_timeout"] == 2
    assert completion.call_args.kwargs["num_retries"] == 0


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_litellm_callback_records_cost_and_blocks_next_call(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool,
) -> None:
    recorded = threading.Event()
    original_record = COST_LEDGER.record

    def record(**kwargs: Any) -> None:
        original_record(**kwargs)
        recorded.set()

    monkeypatch.setattr(COST_LEDGER, "record", record)
    monkeypatch.setattr(litellm, "completion_cost", lambda **kwargs: 0.25)
    register_litellm_cost_callback()
    register_litellm_cost_callback()
    COST_LEDGER.set_ceiling(0.1)
    lm = instantiate_lm(
        ResolvedLM("openai/gpt-4.1-mini", {"api_key": "test"}, "test"),
        cache=False, num_retries=0, request_timeout=2,
    )

    async def run_async() -> None:
        assert await asyncio.wait_for(lm.acall("hi", mock_response=_response()), 3) == ["ok"]
        assert await asyncio.to_thread(recorded.wait, 3)
        with pytest.raises(CostCeilingExceeded):
            await lm.acall("blocked", mock_response=_response())

    if asynchronous:
        asyncio.run(run_async())
    else:
        assert lm("hi", mock_response=_response()) == ["ok"]
        assert recorded.wait(3)
        with pytest.raises(CostCeilingExceeded):
            lm("blocked", mock_response=_response())
    rows = COST_LEDGER.summary()["by_model"]
    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert row["cost_usd"] == 0.25
    assert row["calls"] == 1
    assert row["tokens_in_uncached"] == 10
    assert row["tokens_out"] == 2
    assert litellm._async_success_callback.count(_alog_litellm_cost) == 1


def test_async_call_honors_auth_abort_before_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lm = _nous_lm()
    completion = AsyncMock()
    monkeypatch.setattr(litellm, "acompletion", completion)
    COST_LEDGER._set_auth_abort("credential rejected")
    with pytest.raises(HermesProviderError, match="credential rejected"):
        asyncio.run(lm.acall("hi"))
    completion.assert_not_called()


def test_async_failure_callback_handles_typed_auth_error() -> None:
    from datetime import datetime

    from dspy.utils.exceptions import LMAuthError

    register_litellm_failure_callback()
    register_litellm_failure_callback()
    callbacks = litellm._async_failure_callback
    assert len(callbacks) == 1
    now = datetime.now()
    asyncio.run(callbacks[0](
        {"model": "openai/test"}, LMAuthError("rejected", status=401), now, now,
    ))
    assert "openai/test" in COST_LEDGER.get_auth_abort_message()
