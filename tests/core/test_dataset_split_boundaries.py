"""Explicit zero ratios and invalid allocation inputs must be respected."""

from __future__ import annotations

import pytest

from evolution.core.dataset_builder import EvalExample, split_examples


def _examples() -> list[EvalExample]:
    return [EvalExample(task_input=str(i), expected_behavior="ok") for i in range(12)]


@pytest.mark.parametrize("ratios,empty", [((1, 0, 1), "val"), ((0, 1, 1), "train"),
                                         ((1, 1, 0), "holdout")])
def test_zero_ratio_has_no_examples(ratios: tuple[float, ...], empty: str) -> None:
    data = split_examples(_examples(), seed=7, train_ratio=ratios[0],
                          val_ratio=ratios[1], holdout_ratio=ratios[2])
    assert getattr(data, empty) == []
    assert sorted(ex.task_input for split in (data.train, data.val, data.holdout)
                  for ex in split) == sorted(str(i) for i in range(12))


@pytest.mark.parametrize("ratios", [(0, 0, 0), (-1, 1, 1), (1, float("nan"), 1),
                                    (1, 1, float("inf"))])
def test_invalid_ratios_fail_at_boundary(ratios: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        split_examples(_examples(), seed=7, train_ratio=ratios[0],
                       val_ratio=ratios[1], holdout_ratio=ratios[2])
