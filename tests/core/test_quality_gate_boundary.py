"""Non-inferiority requires a strict lower-bound improvement over its margin."""

from pathlib import Path

import pytest

from evolution.core.config import EvolutionConfig
from evolution.core.constraints import ConstraintValidator


@pytest.fixture(autouse=True)
def _skill_source_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILL_SOURCES_HERMES_REPO", str(tmp_path))


@pytest.mark.parametrize("lower,expected", [(-0.020001, False), (-0.02, False), (-0.019999, True)])
def test_non_inferiority_lower_bound_is_strict(lower: float, expected: bool) -> None:
    validator = ConstraintValidator(EvolutionConfig(gate_mode="non_inferiority", inferiority_tolerance=0.02))
    bootstrap = {"mean": 0.0, "lower_bound": lower, "upper_bound": 0.02,
                 "n_examples": 30, "confidence": 0.95, "n_resamples": 2000}
    result = validator._check_growth_with_quality_gate("short", "long baseline", bootstrap)
    assert result.passed is expected
