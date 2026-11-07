"""Offline GEPA integration with scripted evaluation and reflection LMs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import dspy
import pytest
from dspy.utils import DummyLM

from evolution.core.lineage import build_lineage
from evolution.prompts.prompt_module import PromptModule, _render_instructions
from evolution.prompts.prompt_proposer import PromptSectionProposer
from evolution.skills.budget_aware_proposer import BudgetAwareProposer
from evolution.skills.knee_point import select_knee_point
from evolution.skills.skill_module import SkillModule
from evolution.tools.tool_module import ToolModule, _render_manifest_for_prompt
from evolution.tools.tool_proposer import BudgetAwareToolProposer
from evolution.tools.tool_source import ToolManifest


def _case(kind: str) -> tuple[dspy.Module, Any, str, dict[str, str], dict[str, str], Callable]:
    seed = "Follow the documented procedure carefully."
    revised = "Follow the procedure."
    if kind == "skill":
        return (
            SkillModule(seed), BudgetAwareProposer(len(seed)), revised,
            {"task_input": "check the project"}, {"reasoning": "check", "output": "ok"},
            lambda candidate: candidate.skill_text,
        )
    if kind == "prompt":
        return (
            PromptModule("GUIDANCE", seed),
            PromptSectionProposer(section_name="GUIDANCE", baseline_chars=len(seed)),
            _render_instructions("GUIDANCE", revised),
            {"task": "check the project"}, {"reasoning": "check", "response": "ok"},
            lambda candidate: candidate.section_text,
        )
    manifest = ToolManifest.from_json_file(
        Path(__file__).parents[1] / "fixtures/tool_manifests/multiple_tools.json",
    )
    return (
        ToolModule("search_files", manifest, seed),
        BudgetAwareToolProposer(
            target_tool_name="search_files", manifest=manifest,
            target_description=seed, baseline_chars=len(seed),
        ),
        _render_manifest_for_prompt(manifest, "search_files", revised),
        {"task": "find the project"}, {"reasoning": "search", "chosen_tool": "search_files"},
        lambda candidate: candidate.description_text,
    )


@pytest.mark.parametrize("kind", ["skill", "tool", "prompt"])
@pytest.mark.parametrize("acceptance", ["improvement_or_equal", "strict_improvement"])
def test_real_gepa_preserves_proposers_acceptance_selection_and_lineage(
    kind: str, acceptance: str,
) -> None:
    module, proposer, mutation, inputs, answer, extract = _case(kind)
    examples = [dspy.Example(**inputs).with_inputs(*inputs) for _ in range(2)]
    evaluation_lm = DummyLM([answer] * 40)
    reflection_lm = DummyLM([{"improved_instruction": mutation}] * 10)

    def metric(gold: Any, pred: Any, trace: Any = None,
               pred_name: Any = None, pred_trace: Any = None) -> dspy.Prediction:
        return dspy.Prediction(score=0.5, feedback="Keep the procedure concise.")

    with dspy.context(lm=evaluation_lm):
        optimized = dspy.GEPA(
            metric=metric, max_metric_calls=6, reflection_minibatch_size=1,
            reflection_lm=reflection_lm, instruction_proposer=proposer,
            track_stats=True, use_merge=False, num_threads=1,
            gepa_kwargs={"acceptance_criterion": acceptance},
        ).compile(module, trainset=examples, valset=examples)

    details = optimized.detailed_results
    assert len(reflection_lm.history) >= 1
    assert all(isinstance(scores, dict) for scores in details.val_subscores)
    if acceptance == "strict_improvement":
        assert len(details.candidates) == 1
    else:
        assert len(details.candidates) >= 2
        assert extract(details.candidates[1]) == "Follow the procedure."
        assert details.parents[1] == [0]
    pick = select_knee_point(
        details.candidates, details.val_aggregate_scores, len(examples),
        static_validator=lambda text: [], gepa_default_idx=details.best_idx,
        text_extractor=extract, strategy="smallest",
    )
    assert pick.picked_idx == (0 if acceptance == "strict_improvement" else 1)
    lineage = build_lineage(
        details, extract_text=extract, deployed_idx=pick.picked_idx,
        selection={"strategy": "smallest"}, seed_text=extract(module),
        live_baseline_text=extract(module),
    )
    assert lineage["candidates"][pick.picked_idx]["val_subscores"] == [0.5, 0.5]
    assert lineage["candidates"][pick.picked_idx]["is_deployed"]
