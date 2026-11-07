"""Session scrubbing must recognize tokens without deleting ordinary task prose."""

import pytest

from evolution.core.external_importers import contains_secret


def test_hyphenated_task_prose_is_not_a_credential() -> None:
    assert not contains_secret("Use task-oriented-development-and-regression-testing here")


@pytest.mark.parametrize("text", ["sk-abcdefghijklmnopqrstuvwxyz", 'key="sk-abcdefghijklmnopqrstuvwxyz"',
                                  "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"])
def test_actual_token_still_scrubbed(text: str) -> None:
    assert contains_secret(text)
