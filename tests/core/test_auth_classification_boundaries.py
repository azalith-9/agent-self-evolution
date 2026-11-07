"""Status classification must distinguish protocol evidence from incidental digits."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import litellm
import pytest

from evolution.core.auth_check import is_auth_error, is_rate_limit_error, preflight
from evolution.core.hermes_provider import ResolvedLM


@pytest.mark.parametrize("message", ["request used 4012 tokens", "request id=14030", "size 94010 bytes"])
def test_incidental_digits_do_not_abort_auth(message: str) -> None:
    assert not is_auth_error(RuntimeError(message))


def test_incidental_digits_do_not_abort_rate_limit() -> None:
    assert not is_rate_limit_error(RuntimeError("processed 4290 tokens"))


@pytest.mark.parametrize("code,classifier", [(401, is_auth_error), (403, is_auth_error),
                                              (429, is_rate_limit_error)])
def test_structural_http_status_is_authoritative(code: int, classifier: object) -> None:
    error = RuntimeError("provider rejected request")
    error.status_code = code
    assert classifier(error)


@pytest.mark.parametrize("error", [KeyboardInterrupt("401"), SystemExit("429")])
def test_preflight_preserves_interruption(error: BaseException) -> None:
    with pytest.raises(type(error)) as caught:
        preflight([ResolvedLM("openai/test", {}, "explicit")],
                  completion_fn=Mock(side_effect=error))
    assert caught.value is error


def test_suppressed_bad_request_has_actionable_warning(caplog: pytest.LogCaptureFixture) -> None:
    from evolution.core.auth_check import _translate_or_reraise

    error = litellm.BadRequestError("unsupported max_tokens", "openai", "test-model")
    with caplog.at_level(logging.WARNING):
        _translate_or_reraise(error, model="openai/test-model")
    assert any("test-model" in record.message and "max_tokens" in record.message
               for record in caplog.records)
