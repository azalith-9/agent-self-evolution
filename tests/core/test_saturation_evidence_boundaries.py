"""An empty closed-loop suite is an input error, not measured uniform failure."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.core.saturation_check import saturation_preflight


@pytest.mark.parametrize("empty_arm", ["baseline", "compiled-floor"])
def test_preflight_rejects_empty_programmatic_closed_loop_suite(monkeypatch: pytest.MonkeyPatch, empty_arm: str) -> None:
    monkeypatch.setattr("evolution.core.saturation_check._score_baseline_on_holdout",
                        lambda **kwargs: (0.99, [0.99]))
    empty = SimpleNamespace(evolved=SimpleNamespace(tasks=[]))
    scored = SimpleNamespace(evolved=SimpleNamespace(tasks=[SimpleNamespace(passed=True)]))
    cache = SimpleNamespace(force_run=Mock(side_effect=[empty] if empty_arm == "baseline"
                                                        else [scored, empty]))
    with pytest.raises(ValueError, match="empty|no tasks"):
        saturation_preflight(baseline_module=object(), holdout_examples=[object()], metric=Mock(),
                             lm=Mock(), closed_loop_cache=cache, baseline_artifact_text="baseline",
                             floor_text="constraint" if empty_arm == "compiled-floor" else None)
