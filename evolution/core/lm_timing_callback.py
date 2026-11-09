"""LM-call observability: timing + heartbeat warnings + per-attempt failures
plus cache-aware token + cost accounting.

Surfaces LM-call latency, mid-call heartbeats on stalls, and per-attempt
failures (which DSPy's BaseCallback hides behind tenacity retries).
Required for diagnosing OpenAI capacity degradation, GEPA reflection-LM
stalls, and silent retry behavior — without this, hung calls are
indistinguishable from "still optimizing" until hours pass.

Three surfaces:

1. `LMTimingCallback` — DSPy `BaseCallback` registered globally via
   `dspy.configure(callbacks=[...])`. Logs every LM call's start/end
   with model + duration. Heartbeat warnings fire at 60s/180s/300s/600s
   for any call that hasn't returned (60s = DEBUG since cold-cache calls
   commonly cross it; 180s+ = WARNING).
2. `register_litellm_failure_callback()` — installs `_log_litellm_failure`
   into `litellm.failure_callback` so each retry attempt is logged
   (BaseCallback only fires once per logical call, hiding retries).
   An async counterpart handles LiteLLM's separate async failure hook.
   Idempotent + lock-guarded against TOCTOU on concurrent imports.
3. `CostLedger` + `register_litellm_cost_callback()` — installs a
   success-callback into `litellm.success_callback` that captures
   `usage.prompt_tokens_details.cached_tokens` and aggregates per-model
   token + cost totals. Cost dollars come from
   `litellm.completion_cost(completion_response=...)`, which honors
   OpenAI's cache_read_input_token_cost. The DSPy `on_lm_end` callback
   can NOT see the raw response (DSPy parses it to a list of strings
   before the callback fires), so this hooks litellm directly instead.
   Sync and async callbacks feed the same ledger and next-call abort guards.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import math
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

import litellm
from dspy.utils.callback import BaseCallback

logger = logging.getLogger(__name__)

# 60s tier intentionally DEBUG: cold-cache calls (e.g., gpt-5-mini reasoning
# on first call of a run) commonly cross 60s legitimately. WARNING here
# would train the user to ignore heartbeats. 180s+ are real-stall territory.
_HEARTBEAT_TIERS: tuple[tuple[int, int], ...] = (
    (60, logging.DEBUG),
    (180, logging.WARNING),
    (300, logging.WARNING),
    (600, logging.WARNING),
)


_OBSERVATION_LOCK = threading.RLock()
_OBSERVATION_SINK: CostObservationCapture | None = None
_COST_SCOPE: ContextVar[str | None] = ContextVar("durable_cost_scope", default=None)


class CostObservationCapture:
    """Collect explicit callback deliveries without assuming complete billing coverage.

    LiteLLM may deliver callbacks on background threads. A process may have only
    one active capture; deliveries after close cannot prove that attempt's cost.
    """
    def __init__(self) -> None:
        self.scope_id = uuid4().hex
        self.rows: dict[str, dict] = {}
        self.error: ValueError | None = None

    def record(self, *, call_id: object, model: str, amount: Decimal | None, source: str) -> None:
        with _OBSERVATION_LOCK:
            if type(call_id) is not str or not call_id:
                self.error = ValueError('cost observation lacks an explicit call identity')
                return
            key = hashlib.sha256((call_id + ':' + source).encode()).hexdigest()
            row = {'observation_id': key, 'amount_usd': amount, 'source': source,
                   'model': str(model), 'call_id': call_id}
            if key in self.rows and self.rows[key] != row:
                self.error = ValueError('conflicting cost observation delivery')
                return
            self.rows[key] = row


@contextmanager
def capture_cost_observations() -> Iterator[CostObservationCapture]:
    """Capture observed prices; missing/late callbacks retain unknown coverage."""
    global _OBSERVATION_SINK
    capture = CostObservationCapture()
    with _OBSERVATION_LOCK:
        if _OBSERVATION_SINK is not None:
            raise ValueError('cost observation capture already active')
        _OBSERVATION_SINK = capture
    token = _COST_SCOPE.set(capture.scope_id)
    try:
        yield capture
    finally:
        with _OBSERVATION_LOCK:
            _OBSERVATION_SINK = None
        _COST_SCOPE.reset(token)


def _observe_callback_cost(kwargs: dict, response: object, *, amount: Decimal | None,
                           source: str) -> None:
    with _OBSERVATION_LOCK:
        metadata = kwargs.get('litellm_params', {}).get('metadata') or kwargs.get('metadata') or {}
        scope_id = metadata.get('ase_cost_scope', _COST_SCOPE.get())
        if _OBSERVATION_SINK is not None and scope_id == _OBSERVATION_SINK.scope_id:
            _OBSERVATION_SINK.record(call_id=kwargs.get('litellm_call_id'),
                model=kwargs.get('model', getattr(response, 'model', '<unknown>')),
                amount=amount, source=source)


def _bind_cost_scope(kwargs: dict) -> dict:
    scope = _COST_SCOPE.get()
    if scope is None:
        return kwargs
    metadata = dict(kwargs.get('metadata') or {}, ase_cost_scope=scope)
    return dict(kwargs, metadata=metadata)


def _clear_cost_capture_after_fork() -> None:
    global _OBSERVATION_LOCK, _OBSERVATION_SINK
    _OBSERVATION_LOCK = threading.RLock()
    _OBSERVATION_SINK = None
    _COST_SCOPE.set(None)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_clear_cost_capture_after_fork)


@dataclass(frozen=True)
class _AuthAttempt:
    invocation_id: str
    credential_id: str
    generation: int = 0
    recovering: bool = False


def _credential_identity(model: str, api_key: str) -> str:
    return hashlib.sha256((model.removeprefix("openai/") + "\0" + api_key).encode()).hexdigest()


_AUTH_ATTEMPT: ContextVar[_AuthAttempt | None] = ContextVar("lm_auth_attempt", default=None)


@contextmanager
def inference_auth_scope(model: str, api_key: str) -> Iterator[_AuthAttempt]:
    """Attribute callback failures to one inference without retaining credentials."""
    attempt = _AuthAttempt(uuid4().hex, _credential_identity(model, api_key))
    token = _AUTH_ATTEMPT.set(attempt)
    try:
        yield attempt
    finally:
        _AUTH_ATTEMPT.reset(token)


@contextmanager
def auth_recovery_scope(attempt: _AuthAttempt, model: str, api_key: str) -> Iterator[None]:
    """Permit one retry through its own failure; preserve concurrent aborts."""
    retry = replace(attempt, credential_id=_credential_identity(model, api_key),
                    generation=attempt.generation + 1, recovering=True)
    token = _AUTH_ATTEMPT.set(retry)
    try:
        yield
    finally:
        _AUTH_ATTEMPT.reset(token)


class CostCeilingExceeded(BaseException):
    """Cumulative LM cost exceeded ``--max-total-cost-usd``.

    Inherits from ``BaseException`` so routine ``except Exception:`` in
    litellm callbacks, DSPy callbacks, and ``dspy.Evaluate``'s per-call
    error swallower can't absorb the abort.
    """

    def __init__(self, total_usd: float, ceiling_usd: float):
        self.total_usd = total_usd
        self.ceiling_usd = ceiling_usd
        super().__init__(
            f"cost ${total_usd:.4f} exceeded ceiling ${ceiling_usd:.4f} — aborting"
        )


class LMTimingCallback(BaseCallback):
    """Log every dspy.LM call with timing + tiered heartbeat warnings."""

    def __init__(
        self,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
    ) -> None:
        # Injectable so tests can use a FakeTimer.advance(seconds) double
        # instead of monkeypatching intervals + time.sleep (flaky on slow CI).
        self._timer_factory = timer_factory
        self._inflight: dict[str, tuple[float, str, list[Any]]] = {}
        self._lock = threading.Lock()
        self._call_seq = 0

    def on_lm_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        model = getattr(instance, "model", "<unknown>")
        with self._lock:
            self._call_seq += 1
            seq = self._call_seq
        prompt_chars = sum(
            len(str(m.get("content", ""))) for m in (inputs.get("messages") or [])
        )
        logger.info(
            "[LM #%d start] model=%s call_id=%s prompt_chars=%d",
            seq, model, call_id[:8], prompt_chars,
        )
        timers: list[Any] = []
        for interval, level in _HEARTBEAT_TIERS:
            t = self._timer_factory(
                interval,
                self._emit_heartbeat,
                args=(call_id, seq, model, interval, level),
            )
            t.daemon = True
            t.start()
            timers.append(t)
        with self._lock:
            self._inflight[call_id] = (time.time(), model, timers)

    def on_lm_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: Exception | None = None,
    ) -> None:
        with self._lock:
            entry = self._inflight.pop(call_id, None)
        if entry is None:
            return
        start, model, timers = entry
        for t in timers:
            t.cancel()
        duration = time.time() - start
        if exception is not None:
            logger.warning(
                "[LM end EXC] model=%s call_id=%s duration=%.1fs exception=%s",
                model, call_id[:8], duration, type(exception).__name__,
            )
        else:
            level = logging.WARNING if duration > 30 else logging.INFO
            logger.log(
                level,
                "[LM end] model=%s call_id=%s duration=%.1fs",
                model, call_id[:8], duration,
            )

    def _emit_heartbeat(
        self,
        call_id: str,
        seq: int,
        model: str,
        elapsed: int,
        level: int,
    ) -> None:
        with self._lock:
            still_inflight = call_id in self._inflight
        if still_inflight:
            logger.log(
                level,
                "[LM #%d HEARTBEAT] model=%s call_id=%s still running after %ds",
                seq, model, call_id[:8], elapsed,
            )


def _log_litellm_failure(kwargs, exception, start_time, end_time) -> None:
    """litellm failure_callback fires once per failed *attempt* (not per
    logical call), exposing intermediate retries that BaseCallback hides
    behind a single `on_lm_end`. Without this, a 5×60s retry loop on a
    flaky API looks like a single 5-minute LM call.

    Also sets the mid-run auth-abort sentinel on the cost ledger when the
    exception is auth-shaped, so the next BaseLM.__call__ raises
    HermesProviderError. Defense-in-depth for credentials that go bad
    after preflight passed.
    """
    _observe_callback_cost(kwargs, exception, amount=None, source="litellm-failure-unknown-v1")
    if not isinstance(exception, BaseException):
        exception = kwargs.get("exception", exception)
    model = kwargs.get("model", "<unknown>")
    duration = (end_time - start_time).total_seconds() if end_time else -1.0
    logger.warning(
        "[litellm RETRY/FAIL] model=%s duration=%.1fs exception=%s: %s",
        model, duration, type(exception).__name__, str(exception)[:200],
    )

    # Local import — auth_check pulls in litellm + hermes_provider which
    # are heavy; only worth the cost when we actually hit a failure.
    from evolution.core.auth_check import is_auth_error

    if is_auth_error(exception):
        COST_LEDGER._set_auth_abort(
            f"Authentication failed mid-run for model '{model}': "
            f"{type(exception).__name__}: {str(exception)[:200]}\n"
            "The credential may have expired during the run. Run "
            "`hermes auth` (or set the appropriate provider env var) and "
            "re-run.",
            attempt=_matching_auth_attempt(kwargs),
        )


def _matching_auth_attempt(kwargs: dict[str, Any]) -> _AuthAttempt | None:
    attempt = _AUTH_ATTEMPT.get()
    key = kwargs.get("api_key")
    model = kwargs.get("model")
    if attempt is not None and isinstance(key, str) and isinstance(model, str):
        if attempt.credential_id == _credential_identity(model, key):
            return attempt
    return None


_register_lock = threading.Lock()


async def _alog_litellm_failure(
    kwargs: dict[str, Any], exception: Any, start_time: Any, end_time: Any,
) -> None:
    _log_litellm_failure(kwargs, exception, start_time, end_time)


def register_litellm_failure_callback() -> None:
    """Install sync and async LiteLLM failure callbacks,
    idempotently. Lock-guarded against TOCTOU on concurrent first-call
    (the dedup check + append must be atomic).

    Call this once per `evolve()` invocation rather than at import time
    so test isolation isn't compromised by module-level mutation of a
    third-party global.
    """
    with _register_lock:
        callbacks = litellm.failure_callback or []
        if _log_litellm_failure not in callbacks:
            litellm.failure_callback = callbacks + [_log_litellm_failure]
        async_callbacks = litellm._async_failure_callback or []
        if _alog_litellm_failure not in async_callbacks:
            litellm._async_failure_callback = async_callbacks + [_alog_litellm_failure]


@dataclass
class _ModelCostRow:
    tokens_in_uncached: int = 0
    tokens_in_cached: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        prompt_total = self.tokens_in_uncached + self.tokens_in_cached
        return {
            "tokens_in_uncached": self.tokens_in_uncached,
            "tokens_in_cached": self.tokens_in_cached,
            "tokens_out": self.tokens_out,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
            "cache_hit_rate": (
                self.tokens_in_cached / prompt_total if prompt_total > 0 else 0.0
            ),
        }


class CostLedger:
    """Per-model token + cost aggregator, fed by the litellm success callback.

    Cost dollars come from `litellm.completion_cost(...)` — that helper
    honors `cache_read_input_token_cost` for OpenAI, so we don't maintain
    a parallel price table that would drift with each litellm release.
    Token counts are captured separately so we can report cache-hit rate
    as a diagnostic; a hit-rate that drops near zero mid-campaign signals
    that a prompt change has busted the cache.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_model: dict[str, _ModelCostRow] = {}
        self._ceiling_usd: Optional[float] = None
        self._abort_requested: bool = False
        # Mid-run auth-abort sentinel: when a litellm.failure_callback
        # observes an auth-shaped exception, it sets this. The patched
        # BaseLM.__call__ checks it and raises HermesProviderError so the
        # next worker abort propagates past dspy.Evaluate's `except
        # Exception` swallower (HermesProviderError is BaseException-derived).
        self._auth_failures: dict[str, tuple[str, _AuthAttempt | None]] = {}
        self._agent_cost_usd: float = 0.0
        self._n_agent_runs: int = 0
        self._n_cost_uncaptured: int = 0

    def reset(self) -> None:
        # Must also clear the abort flags — the cost + failure callbacks
        # are registered process-globally, so a stale flag from a prior
        # run would abort the next run's first LM call.
        with self._lock:
            self._by_model.clear()
            self._ceiling_usd = None
            self._abort_requested = False
            self._auth_failures.clear()
            self._agent_cost_usd = 0.0
            self._n_agent_runs = 0
            self._n_cost_uncaptured = 0

    def _set_auth_abort(self, message: str, *, attempt: _AuthAttempt | None = None) -> None:
        """Retain each failure independently until its exact attempt recovers."""
        with self._lock:
            self._auth_failures[uuid4().hex] = (message, attempt)

    def clear_recovered_auth(self, attempt: _AuthAttempt) -> None:
        """Clear only the failed credential generation of a successful retry."""
        with self._lock:
            self._auth_failures = {
                key: value for key, value in self._auth_failures.items()
                if value[1] != attempt
            }

    def get_auth_abort_message(self) -> Optional[str]:
        """Return the earliest unresolved failure applicable to this context."""
        current = _AUTH_ATTEMPT.get()
        with self._lock:
            for message, failed in self._auth_failures.values():
                if (current is not None and current.recovering and failed is not None
                        and failed.invocation_id == current.invocation_id
                        and failed.generation < current.generation):
                    continue
                return message
        return None

    def set_ceiling(self, usd: Optional[float]) -> None:
        """Set the total-cost ceiling in USD. ``None`` disables. After the
        ceiling is exceeded, the next LM call will raise
        ``CostCeilingExceeded`` from ``LMTimingCallback.on_lm_start``.
        """
        with self._lock:
            self._ceiling_usd = usd

    def _combined_total(self) -> float:
        """In-process LM cost + agent-side cost. Must be called under _lock."""
        return sum(r.cost_usd for r in self._by_model.values()) + self._agent_cost_usd

    def record(
        self,
        *,
        model: str,
        prompt_tokens: int,
        cached_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int,
        cost_usd: float,
    ) -> None:
        # Single critical section over the dict insert + the ceiling check
        # so concurrent dspy.Evaluate threads can't observe a half-updated
        # row or read a stale total when setting the abort flag.
        with self._lock:
            row = self._by_model.setdefault(model, _ModelCostRow())
            row.tokens_in_uncached += max(0, prompt_tokens - cached_tokens)
            row.tokens_in_cached += cached_tokens
            row.tokens_out += completion_tokens
            row.reasoning_tokens += reasoning_tokens
            row.cost_usd += cost_usd
            row.calls += 1
            if self._ceiling_usd is not None and not self._abort_requested:
                if self._combined_total() > self._ceiling_usd:
                    self._abort_requested = True

    def record_agent_cost(self, usd: Optional[float]) -> None:
        """Record cost from an agent run captured out-of-process (state.db).

        ``usd is None`` means the run completed but its cost is uncaptured: the
        run is counted and the uncaptured counter is incremented, but $0 is added
        toward the ceiling (the recorded total becomes a lower bound). A non-None
        ``usd`` — including a genuine ``0.0`` — is added to the agent total.

        The producer guarantees ``usd is None`` ⟺ the cost is uncaptured, so the
        sentinel never appears in control flow. After recording, the combined
        ceiling (in-process LM cost + agent cost) is re-checked and the abort flag
        set if exceeded.
        """
        with self._lock:
            self._n_agent_runs += 1
            if usd is None:
                self._n_cost_uncaptured += 1
            else:
                self._agent_cost_usd += usd
            if self._ceiling_usd is not None and not self._abort_requested:
                if self._combined_total() > self._ceiling_usd:
                    self._abort_requested = True

    def get_abort_state(self) -> Optional[tuple[float, float]]:
        """If a cost-ceiling abort is pending, return ``(total_usd,
        ceiling_usd)`` for the exception payload. Returns ``None``
        otherwise. The flag is not cleared by reading — every LM call
        after the ceiling trip will keep aborting until ``reset()``.
        """
        with self._lock:
            if not self._abort_requested:
                return None
            # _ceiling_usd is non-None when _abort_requested is True (set
            # together inside the lock in record()), so the cast is safe.
            return self._combined_total(), float(self._ceiling_usd)  # type: ignore[arg-type]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            by_model = {model: row.to_dict() for model, row in self._by_model.items()}
            agent_cost_usd = self._agent_cost_usd
            n_agent_runs = self._n_agent_runs
            n_cost_uncaptured = self._n_cost_uncaptured
        inprocess_total = sum(row["cost_usd"] for row in by_model.values())
        total_usd = round(inprocess_total, 6)
        total_cost_usd = round(inprocess_total + agent_cost_usd, 6)
        return {
            "total_usd": total_usd,
            "by_model": by_model,
            "agent_cost_usd": round(agent_cost_usd, 6),
            "n_agent_runs": n_agent_runs,
            "n_cost_uncaptured": n_cost_uncaptured,
            "total_cost_usd": total_cost_usd,
        }


# Module-level singleton so the litellm success callback (a free function,
# not a method) can find the ledger. `evolve()` calls reset() at the start
# of each run; tests can construct their own CostLedger and bypass this.
COST_LEDGER = CostLedger()


def _extract_usage_fields(
    completion_response: Any,
) -> tuple[int, int, int, int]:
    """Extract (prompt, cached, completion, reasoning) tokens defensively.

    litellm normalizes `usage` to a Pydantic-ish object but fields are
    `None` on streaming aggregates and on non-supporting providers.
    Returns zeros for any missing field so the caller never sees None.
    """
    usage = getattr(completion_response, "usage", None)
    if usage is None:
        return 0, 0, 0, 0
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    pdt = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = (getattr(pdt, "cached_tokens", 0) or 0) if pdt else 0
    cdt = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = (getattr(cdt, "reasoning_tokens", 0) or 0) if cdt else 0
    return int(prompt_tokens), int(cached_tokens), int(completion_tokens), int(reasoning_tokens)


def _log_litellm_cost(
    kwargs: dict[str, Any],
    completion_response: Any,
    start_time: Any,
    end_time: Any,
    ledger: Optional[CostLedger] = None,
) -> None:
    """litellm success_callback: capture per-call usage + cost into the
    ledger. The DSPy `on_lm_end` hook can't reach this layer because DSPy
    has already parsed `completion_response` to text by the time it fires.
    """
    target_ledger = ledger if ledger is not None else COST_LEDGER
    model = kwargs.get("model") or getattr(completion_response, "model", "<unknown>")
    prompt_t, cached_t, completion_t, reasoning_t = _extract_usage_fields(
        completion_response
    )
    try:
        cost = float(litellm.completion_cost(completion_response=completion_response))
        if not math.isfinite(cost) or cost < 0:
            raise ValueError("invalid observed cost")
        observed = Decimal(str(cost))
    except Exception as exc:  # noqa: BLE001 — litellm raises a wide range
        logger.debug(
            "litellm.completion_cost failed for model=%s: %s — cost remains unknown",
            model, exc,
        )
        cost = 0.0
        observed = None
    _observe_callback_cost(kwargs, completion_response, amount=observed, source="litellm-completion-cost-v1")
    target_ledger.record(
        model=model,
        prompt_tokens=prompt_t,
        cached_tokens=cached_t,
        completion_tokens=completion_t,
        reasoning_tokens=reasoning_t,
        cost_usd=cost,
    )
    logger.info(
        "[LM cost] model=%s tokens=%d+%d(cached=%d)→%d cost=$%.6f",
        model, prompt_t - cached_t, cached_t, cached_t, completion_t, cost,
    )


async def _alog_litellm_cost(
    kwargs: dict[str, Any], completion_response: Any, start_time: Any, end_time: Any,
) -> None:
    _log_litellm_cost(kwargs, completion_response, start_time, end_time)


def register_litellm_cost_callback() -> None:
    """Install sync and async LiteLLM cost callbacks,
    idempotently. Lock-guarded against TOCTOU on concurrent first-call.

    Call this once per `evolve()` invocation alongside
    `register_litellm_failure_callback`. Both are scoped via the same
    module-level lock since they mutate sibling globals on the same
    library.
    """
    with _register_lock:
        callbacks = litellm.success_callback or []
        if _log_litellm_cost not in callbacks:
            litellm.success_callback = callbacks + [_log_litellm_cost]
        async_callbacks = litellm._async_success_callback or []
        if _alog_litellm_cost not in async_callbacks:
            litellm._async_success_callback = async_callbacks + [_alog_litellm_cost]


def _raise_if_lm_aborted() -> None:
    state = COST_LEDGER.get_abort_state()
    if state is not None:
        raise CostCeilingExceeded(*state)
    auth_msg = COST_LEDGER.get_auth_abort_message()
    if auth_msg is not None:
        from evolution.core.hermes_provider import HermesProviderError
        raise HermesProviderError(auth_msg)


def _install_cost_ceiling_lm_guard() -> None:
    """Guard ``BaseLM.__call__`` and ``acall`` against pending ledger aborts.

    Callbacks can't raise — DSPy and litellm
    both swallow callback exceptions — so the check has to live in the
    call path itself. Idempotent.
    """
    from dspy.clients.base_lm import BaseLM

    if not getattr(BaseLM.__call__, "_cost_ceiling_guarded", False):
        original_call = BaseLM.__call__

        @functools.wraps(original_call)
        def call_with_cost_ceiling_check(self: Any, *args: Any, **kwargs: Any) -> Any:
            _raise_if_lm_aborted()
            return original_call(self, *args, **_bind_cost_scope(kwargs))

        call_with_cost_ceiling_check._cost_ceiling_guarded = True  # type: ignore[attr-defined]
        BaseLM.__call__ = call_with_cost_ceiling_check

    if not getattr(BaseLM.acall, "_cost_ceiling_guarded", False):
        original_acall = BaseLM.acall

        @functools.wraps(original_acall)
        async def acall_with_cost_ceiling_check(self: Any, *args: Any, **kwargs: Any) -> Any:
            _raise_if_lm_aborted()
            return await original_acall(self, *args, **_bind_cost_scope(kwargs))

        acall_with_cost_ceiling_check._cost_ceiling_guarded = True  # type: ignore[attr-defined]
        BaseLM.acall = acall_with_cost_ceiling_check


_install_cost_ceiling_lm_guard()
