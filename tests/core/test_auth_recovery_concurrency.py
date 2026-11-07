"""Recovery must preserve another inference's failure, even with the same key."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

import litellm
import pytest

from evolution.core.lm_timing_callback import (
    COST_LEDGER,
    _log_litellm_failure,
    auth_recovery_scope,
    inference_auth_scope,
)


@pytest.fixture(autouse=True)
def isolated_ledger() -> object:
    COST_LEDGER.reset()
    yield
    COST_LEDGER.reset()


def _fail(message: str, key: str = "old") -> None:
    now = datetime.now()
    _log_litellm_failure(
        {"model": "openai/test", "api_key": key},
        litellm.AuthenticationError(message, llm_provider="openai", model="openai/test"),
        now, now,
    )


def test_same_credential_concurrent_failure_survives_recovery() -> None:
    with inference_auth_scope("openai/test", "old") as recovering:
        _fail("recoverable first")
        errors = []

        def fail_elsewhere() -> None:
            try:
                with inference_auth_scope("openai/test", "old"):
                    _fail("concurrent terminal")
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=fail_elsewhere)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive() and not errors
        with auth_recovery_scope(recovering, "openai/test", "new"):
            assert "concurrent terminal" in COST_LEDGER.get_auth_abort_message()
        COST_LEDGER.clear_recovered_auth(recovering)
        assert "concurrent terminal" in COST_LEDGER.get_auth_abort_message()


def test_retry_failure_is_not_cleared_with_failed_previous_generation() -> None:
    with inference_auth_scope("openai/test", "old") as attempt:
        _fail("old generation")
        with auth_recovery_scope(attempt, "openai/test", "new"):
            assert COST_LEDGER.get_auth_abort_message() is None
            _fail("retry terminal", "new")
        COST_LEDGER.clear_recovered_auth(attempt)
    assert "retry terminal" in COST_LEDGER.get_auth_abort_message()


def test_async_recovery_context_does_not_bypass_sibling_abort() -> None:
    async def scenario() -> None:
        first_failed, sibling_failed = asyncio.Event(), asyncio.Event()

        async def recover() -> None:
            with inference_auth_scope("openai/test", "old") as attempt:
                _fail("recoverable first")
                first_failed.set()
                await sibling_failed.wait()
                with auth_recovery_scope(attempt, "openai/test", "new"):
                    assert "sibling terminal" in COST_LEDGER.get_auth_abort_message()
                COST_LEDGER.clear_recovered_auth(attempt)

        async def sibling() -> None:
            await first_failed.wait()
            with inference_auth_scope("openai/test", "old"):
                _fail("sibling terminal")
                sibling_failed.set()

        await asyncio.wait_for(asyncio.gather(recover(), sibling()), timeout=2)

    asyncio.run(scenario())
    assert "sibling terminal" in COST_LEDGER.get_auth_abort_message()


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_litellm_failure_callback_retains_inference_identity(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool,
) -> None:
    from evolution.core.lm_timing_callback import register_litellm_failure_callback

    for name in ("success_callback", "failure_callback", "_async_success_callback",
                 "_async_failure_callback", "callbacks"):
        monkeypatch.setattr(litellm, name, [])
    register_litellm_failure_callback()
    error = litellm.AuthenticationError("synthetic rejection", llm_provider="openai", model="test")
    kwargs = dict(model="openai/test", api_key="synthetic-old", mock_response=error,
                  messages=[{"role": "user", "content": "synthetic"}], num_retries=0)
    # LiteLLM's mock-response adapter logs its fixed synthetic key.
    with inference_auth_scope("openai/test", "mock-key") as attempt:
        with pytest.raises(litellm.AuthenticationError):
            if asynchronous:
                asyncio.run(litellm.acompletion(**kwargs))
            else:
                litellm.completion(**kwargs)
        assert COST_LEDGER.get_auth_abort_message() is not None
        with auth_recovery_scope(attempt, "openai/test", "synthetic-new"):
            assert COST_LEDGER.get_auth_abort_message() is None
        COST_LEDGER.clear_recovered_auth(attempt)
    assert COST_LEDGER.get_auth_abort_message() is None


@pytest.mark.parametrize("asynchronous", [False, True])
def test_nous_recovery_through_real_litellm_mock_adapter(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool,
) -> None:
    import time

    from evolution.core.lm_timing_callback import register_litellm_failure_callback
    from evolution.core.nous_lm import NousLM, _reset_state_for_tests

    for name in ("success_callback", "failure_callback", "_async_success_callback",
                 "_async_failure_callback", "callbacks"):
        monkeypatch.setattr(litellm, name, [])
    _reset_state_for_tests()
    register_litellm_failure_callback()
    rejection = RuntimeError("synthetic rejection")
    rejection.status_code = 401
    lm = NousLM(
        "openai/test", access_token="synthetic-access", refresh_token="synthetic-refresh",
        oauth_expires_at=time.time() + 86400, agent_key="mock-key",
        agent_key_expires_at=time.time() + 1800, cache=False, num_retries=0,
        mock_response=rejection,
    )

    def remint() -> None:
        lm._shared_state.agent_key = "synthetic-new"
        lm._shared_state.agent_key_expires_at = time.time() + 1800
        lm._sync_from_shared_state()
        lm.kwargs["mock_response"] = "ok"

    monkeypatch.setattr(lm, "_force_remint", remint)
    try:
        for _ in range(2):
            result = asyncio.run(lm.acall("synthetic")) if asynchronous else lm("synthetic")
            assert result == ["ok"]
        assert COST_LEDGER.get_auth_abort_message() is None
    finally:
        _reset_state_for_tests()
