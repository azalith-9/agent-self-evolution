"""Score recording and validator transitions must share synchronization."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from evolution.core.closed_loop_feedback import ClosedLoopFeedbackCache
from evolution.validation.task import Task, TaskSuite


def test_judge_history_serializes_with_inflight_validation(tmp_path: Path) -> None:
    validating, release, recording, recorded = (threading.Event() for _ in range(4))
    errors = []

    def validate(inputs: object) -> object:
        validating.set()
        if not release.wait(2):
            raise AssertionError("test failed to release validation")
        return SimpleNamespace()

    cache = ClosedLoopFeedbackCache(
        validator=SimpleNamespace(validate=validate),
        suite=TaskSuite(tmp_path / "suite.jsonl", "sha", (Task("t", "m"),)),
        artifact_name="tool", baseline_artifact_text="baseline", gate_mode="always",
    )

    def run_validation() -> None:
        try:
            cache.get_or_run("candidate")
        except BaseException as exc:
            errors.append(exc)

    def record() -> None:
        recording.set()
        cache.record_judge_score(1.0)
        recorded.set()

    validator = threading.Thread(target=run_validation, daemon=True)
    recorder = threading.Thread(target=record, daemon=True)
    try:
        validator.start()
        assert validating.wait(1)
        recorder.start()
        assert recording.wait(1)
        assert not recorded.wait(0.1), "score history changed during the validator's locked transition"
    finally:
        release.set()
        validator.join(timeout=1)
        if recorder.ident is not None:
            recorder.join(timeout=1)
        cache._cleanup_finalizer()
    assert recorded.is_set()
    assert not validator.is_alive() and not recorder.is_alive()
    assert errors == []
