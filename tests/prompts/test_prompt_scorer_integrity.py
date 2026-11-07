"""Install memoization must not memoize the integrity of the installed file."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.prompts.prompt_judge import make_memoizing_splice_scorer
from evolution.validation.validator import ChecksumDriftError, _verify_no_drift


def test_reused_candidate_is_verified_before_every_task(tmp_path: Path) -> None:
    target = tmp_path / "prompt.txt"
    expected = []

    def install(text: str) -> None:
        target.write_text(text)
        expected[:] = [hashlib.sha256(text.encode()).hexdigest()]

    score = Mock(return_value=1.0)
    scorer = make_memoizing_splice_scorer(install_fn=install, score_fn=score,
                                         verify_fn=lambda: _verify_no_drift(target, expected[0]))
    assert scorer("first", "candidate").score == 1.0
    target.write_text("drift")
    with pytest.raises(ChecksumDriftError):
        scorer("second", "candidate")
    score.assert_called_once_with("first")
