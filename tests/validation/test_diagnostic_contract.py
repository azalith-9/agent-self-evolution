"""Diagnostic ties remain separate from the evidence required for deployment."""

from io import StringIO

import pytest
from rich.console import Console

from evolution.validation.report import (
    IncompleteValidationError,
    TaskResult,
    ValidationReport,
    compute_win_loss,
    decide,
    require_complete_validation,
    summarize_phase,
)


@pytest.mark.parametrize("abstained", [False, True], ids=["empty", "abstained"])
def test_missing_evidence_is_safe_to_render_but_cannot_deploy(abstained: bool) -> None:
    tasks = [TaskResult("task", False, True, [], 0.1)] if abstained else []
    phase = summarize_phase(tasks)
    delta = compute_win_loss(phase, phase)
    decision, reasons = decide(phase, phase, delta)
    assert (decision, delta.n_wins, delta.n_losses) == ("pass", 0, 0)
    report = ValidationReport("1", "tool", "suite.jsonl", "sha", phase, phase,
                              delta, decision, reasons)
    output = StringIO()
    report.render_console(Console(file=output, force_terminal=False))
    assert "Decision:" in output.getvalue()
    with pytest.raises(IncompleteValidationError):
        require_complete_validation(report)
