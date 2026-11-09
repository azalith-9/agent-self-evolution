"""Callback delivery identities preserve owner, price and uncertainty."""
from __future__ import annotations

import threading
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.core import lm_timing_callback as timing


def deliver(monkeypatch: pytest.MonkeyPatch, amount: object, **kwargs: object) -> None:
    monkeypatch.setattr(timing.litellm, 'completion_cost', Mock(return_value=amount))
    timing._log_litellm_cost(dict(model='fixture', litellm_call_id='delivery', **kwargs),
        SimpleNamespace(usage=None), None, None, ledger=timing.CostLedger())


@pytest.mark.parametrize('amount,expected', [(0, Decimal('0')), (.125, Decimal('.125')),
                                            (-1, None), (float('nan'), None)])
def test_observed_prices_preserve_zero_and_unknown(monkeypatch, amount, expected):
    with timing.capture_cost_observations() as capture:
        deliver(monkeypatch, amount)
    assert len(capture.rows) == 1
    assert next(iter(capture.rows.values()))['amount_usd'] == expected


def test_duplicate_delivery_is_idempotent_but_changed_price_is_not(monkeypatch):
    with timing.capture_cost_observations() as capture:
        deliver(monkeypatch, .125)
        deliver(monkeypatch, .125)
        assert len(capture.rows) == 1 and capture.error is None
        deliver(monkeypatch, .25)
    assert capture.error is not None
    assert next(iter(capture.rows.values()))['amount_usd'] == Decimal('.125')


def test_late_background_callback_cannot_be_assigned_to_next_attempt(monkeypatch):
    with timing.capture_cost_observations() as first:
        old_metadata = timing._bind_cost_scope({})['metadata']
    with timing.capture_cost_observations() as second:
        thread = threading.Thread(target=lambda: deliver(monkeypatch, .125,
                                  litellm_params={'metadata': old_metadata}))
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert first.rows == second.rows == {}


def test_background_callback_uses_explicit_dispatch_owner(monkeypatch):
    with timing.capture_cost_observations() as capture:
        metadata = timing._bind_cost_scope({})['metadata']
        thread = threading.Thread(target=lambda: deliver(monkeypatch, .125,
                                  litellm_params={'metadata': metadata}))
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert len(capture.rows) == 1
