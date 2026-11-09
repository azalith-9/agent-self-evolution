"""Public propose-only attempt API, composed lazily with the repair tier."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from evolution.monitor.sentinel import RepairCandidate


def attempt_candidates(repo: Path, candidates: list[RepairCandidate], payload: dict, *,
                       max_cost_usd: float | None = None, proposer_model: str | None = None,
                       base_python: str | None = None, seeds: int = 3, max_rounds: int = 5,
                       console: object = None, organism_runner: object = None,
                       cost_summary: Callable = dict, require_sandbox: bool = True,
                       persist: Callable[[dict], None] | None = None,
                       progress_root: Path | None = None) -> None:
    """Annotate attempts, optionally deriving committed results from a journal."""
    from evolution.composition.monitor_code import attempt_candidates as attempt
    attempt(repo, candidates, payload, max_cost_usd=max_cost_usd, proposer_model=proposer_model,
            base_python=base_python, seeds=seeds, max_rounds=max_rounds, console=console,
            organism_runner=organism_runner, cost_summary=cost_summary,
            require_sandbox=require_sandbox, persist=persist, progress_root=progress_root)
