"""Nullable usage is absent evidence; malformed usage must abstain safely."""

from __future__ import annotations

import json

import pytest

from evolution.validation.claude_runner import _parse_stream_json


def test_null_token_counts_are_normalized_to_zero() -> None:
    event = {"type": "result", "result": "", "usage": {
        "input_tokens": None, "output_tokens": None,
        "cache_read_input_tokens": None, "cache_creation_input_tokens": None,
    }}
    result = _parse_stream_json(json.dumps(event), duration_seconds=0.1)
    assert result.agent_tokens == {"input_tokens": 0, "output_tokens": 0,
                                   "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert result.error is not None


@pytest.mark.parametrize("usage", [[], "invalid", {"input_tokens": "many"},
                                  {"input_tokens": -1}, {"output_tokens": True}])
def test_malformed_usage_abstains_instead_of_crashing_or_certifying(usage: object) -> None:
    result = _parse_stream_json(json.dumps({"type": "result", "result": "answer",
                                           "usage": usage}), duration_seconds=0.1)
    assert result.error is not None
