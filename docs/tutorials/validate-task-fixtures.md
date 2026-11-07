---
title: Validate a task fixture without an agent
description: Load a temporary task suite offline and understand fixture path and verdict boundaries
doc_type: tutorial
maintenance: Update with TaskSuite parsing and fixture boundary changes
---

# Validate a task fixture without an agent

This exercise loads one real task shape through `TaskSuite.from_jsonl` and checks
how its message is rendered. It runs no agent, provider request, or task command.
Use an installed project environment; `--no-sync` avoids dependency retrieval.

**Scope:** the runnable exercise verifies suite loading and message rendering.
The execution and deployment requirements discussed afterward are
[planned contracts](../reference/execution-contracts.md#implementation-boundary),
not guarantees established by this exercise or the recovered gate.

## Load a suite in temporary storage

From the repository root, run:

```bash
uv run --no-sync python - <<'PY'
import json
import tempfile
from pathlib import Path

from evolution.validation.task import TaskSuite

task = {
    "task_id": "fixture-sum",
    "user_message": "Check solution.py in {fixture_dir} and run its assertion.",
    "fixture_setup": {
        "solution.py": "def total(values):\n    return sum(values)\n",
        "test_solution.py": "from solution import total\nassert total([2, 3]) == 5\n",
    },
    "test_command": "python test_solution.py",
}

with tempfile.TemporaryDirectory(prefix="task-suite-example-") as directory:
    root = Path(directory)
    suite_path = root / "tasks.jsonl"
    suite_path.write_text(json.dumps(task) + "\n", encoding="utf-8")
    suite = TaskSuite.from_jsonl(suite_path)
    loaded = suite.tasks[0]
    assert loaded.task_id == "fixture-sum"
    assert len(suite.sha256) == 64
    assert str(root) in loaded.render_message(root)
    print(f"Loaded {len(suite.tasks)} task: {loaded.task_id}")
    print("Fixture files:", ", ".join(sorted(loaded.fixture_setup)))
    print("Test command:", loaded.test_command)
PY
```

Expected output:

```text
Loaded 1 task: fixture-sum
Fixture files: solution.py, test_solution.py
Test command: python test_solution.py
```

The temporary suite disappears on exit. Loading the JSONL does not materialize
its fixture files or execute `test_command`. The validator performs those steps
in a validation run; the planned contract requires an approved execution scope.

## Understand the boundaries

The following are planned input and filesystem requirements. The exercise above
uses a valid suite and does not test rejection paths or materialization safety.

`fixture_setup` maps relative file paths to string contents. `solution.py` is a
valid key. `/tmp/solution.py` and `../solution.py` must be rejected because a task
cannot choose a destination outside its fixture. A numeric content value must be
rejected rather than converted to text.

Under the planned input contract, task IDs must be unique. Duplicating
`fixture-sum` in the same suite must be an error;
it cannot overwrite a cached task or silently shrink the comparison population.
An empty suite also fails validation, including when constructed programmatically
for saturation scoring.

Parsing is one boundary. Under the planned contract, materialization must check
filesystem containment so an escaping or replaced symlink cannot redirect a write.
`skills_src`, when used, comes from an approved skill source; it is not a way to
copy arbitrary host directories into an agent environment.

## Interpret the later verdict

In a validation run, `test_command` takes precedence over tool-call membership
scoring for this task. The existing scorer treats exit zero as a diagnostic pass.
It does not prove trusted coverage, containment, certified cleanup, or independent
verification. A timeout or unavailable sandbox cannot establish a passing result.

Diagnostic ties and abstentions remain visible in reports. Deployment applies
its separate completeness check before comparing baseline and candidate. Under
the proposed execution contract, cooperative pytest evidence remains deployment
ineligible until the independent verifier and gate integration exist. Continue
with [execution evidence](../reference/execution-contracts.md#test-evidence) to
understand what a gate needs beyond console output.
