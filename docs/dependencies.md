# Dependencies

External packages the framework depends on, what each is used for, and how they're constrained.

The supported Python range is `>=3.10,<3.15`, matching GEPA’s Python constraint.
Use `uv sync` for the versions recorded in `uv.lock`.

## Hard runtime dependencies

### `dspy[litellm]>=3.4.1,<3.5`

The optimization engine. The lock pins DSPy 3.4.1 with its LiteLLM extra. All framework LM constructors explicitly select `engine="litellm"` so OAuth adapters and LiteLLM cost/failure callbacks keep their existing execution path. Used pervasively:

| Module | Usage |
|---|---|
| `dspy.Module` | Base class for `SkillModule` (`evolution/skills/skill_module.py`). |
| `dspy.Signature`, `dspy.InputField`, `dspy.OutputField` | Declarative LM signatures (judge, dataset gen, relevance scoring, budget-aware proposer). |
| `dspy.ChainOfThought`, `dspy.Predict` | Wrapped predictors. |
| `dspy.Example` | Train/val/holdout examples (via `EvalDataset.to_dspy_examples`). |
| `dspy.Prediction` | Metric return type (`score`, `feedback`). |
| `dspy.LM` | All LM calls use the LiteLLM engine. `request_timeout` reaches LiteLLM; DSPy owns bounded retries via `num_retries`. |
| `dspy.configure` | Sets the global LM + callbacks. |
| `dspy.context(lm=...)` | Per-block LM override (used in dataset gen, judge, relevance scoring). |
| `dspy.GEPA` | The reflective optimizer. `track_stats=True` for `detailed_results`; `instruction_proposer=` for `BudgetAwareProposer`. |
| `dspy.MIPROv2` | Fallback optimizer (lazy `optuna` import). |
| `dspy.Evaluate` | Holdout scoring with `num_threads=4`. |
| `dspy.utils.callback.BaseCallback` | Subclassed by `LMTimingCallback`. **Internal-ish API.** |

**Why bounded below 3.5:** the custom Codex and Nous LMs still use the
`forward` / `aforward` subclass interface, which DSPy supports throughout 3.4
and schedules for removal in 3.5. Migrating those adapters to the normalized
engine API is separate work. Authentication handling recognizes DSPy's typed
`LMAuthError` and `LMRateLimitError` as well as LiteLLM errors. Reflection
`request_timeout` and `num_retries` remain explicit at construction.

GEPA's `DspyGEPAResult.val_subscores` contains mappings keyed by validation
example ID. Lineage persistence orders scores by example ID and writes the
existing JSON score-list shape. Custom instruction proposers, sentinel guards,
and the framework's candidate selection and deployment gates remain in use.

### `gepa==0.1.4`

The released optimizer used by DSPy 3.4.1. Both dependencies resolve from PyPI
without a Git dependency or uv override. GEPA 0.1.4 includes the
`acceptance_criterion` API: the framework forwards its `--gepa-acceptance`
selection through `dspy.GEPA(..., gepa_kwargs={...})`, defaulting to
`"improvement_or_equal"`. The optional `miprov2` extra resolves alongside the
same DSPy and GEPA versions.

### `litellm>=1.82.0,<2.0`

The provider-agnostic LLM client used by DSPy, credential preflight, and cost metering. Observability hooks live in `evolution/core/lm_timing_callback.py`:

- `litellm.success_callback` and `litellm.failure_callback` record synchronous costs and failures.
- `litellm._async_success_callback` and `litellm._async_failure_callback` register coroutine equivalents for asynchronous calls; LiteLLM does not invoke synchronous function callbacks for those calls.
- The `BaseLM.__call__` and `BaseLM.acall` guards check the same ledger before each request, enforcing pending cost and authentication aborts in both paths.

Registration is idempotent and lock-guarded. Offline integration tests use real
DSPy/LiteLLM execution with mocked responses to verify token accounting, one
cost record per call, and the next-call cost ceiling in sync and async modes.

**Why bounded below 2.0:** module-level callback lists include private async hooks. Their protocol is covered by integration tests and must be revalidated when upgrading LiteLLM. The lock currently uses 1.82.6.

### `openai>=1.0.0`

The OpenAI SDK that LiteLLM uses for `openai/*` model strings and the Codex
Responses API path. Roles can inherit Hermes provider configuration or use
explicit model flags; see [model_resolution.md](model_resolution.md).

DSPy manages retries and invokes the LiteLLM engine with its own retries disabled. `request_timeout` is a per-attempt timeout, so a retry budget does not imply a hard wall-clock ceiling for an entire optimization.

Models can be swapped to any provider litellm supports (Anthropic, OpenRouter, Together, etc.) via `--optimizer-model anthropic/claude-3-5-sonnet-20241022` etc. — no code changes required.

### `click>=8.0`

Used for the two CLIs:
- `evolution/skills/evolve_skill.py:main` — primary `evolve` CLI.
- `evolution/core/external_importers.py:main` — standalone session importer.

Standard `@click.command()` + `@click.option()` patterns; no plugins or custom types.

### `rich>=13.0`

Terminal UI. Two surfaces:
- `Console` — colored output throughout `evolve_skill.py` (cyan headers, green checks, red rejects).
- `Panel` — fallback banner when GEPA fails.
- `Table` — final results table (baseline / evolved / change).
- `Progress` — progress bars in `external_importers.py` for Copilot session reads + relevance scoring.

### `reportlab>=4.0`

Used only by the two top-level report renderers (not part of `evolution/`). `generate_report.py` renders `reports/phase{1,2,3}_validation_report.pdf` from a `*_prose.yaml` plus the per-run `output/<skill>/<ts>/{gate_decision.json,metrics.json,run.log}` artifacts. `generate_findings_report.py` renders the cross-run synthesis reports (`reports/asymmetry_report.pdf`, `reports/phase{4,5}_validation_report.pdf`) from a self-contained prose YAML, verifying each number against its source JSON before emitting. Neither is exercised by the optimization pipeline.

### `numpy>=1.24`

Used by `evolution/core/stats.py:paired_bootstrap` for the resample matrix and percentile computation (`np.array`, `np.percentile`, `np.random`). Floor 1.24 predates the 2.0 ABI break and stays compatible with both numpy 1.x and 2.x. No upper bound — only stable APIs are touched.

### `pyyaml>=6.0`

Used only by the report renderers (`generate_report.py`, `generate_findings_report.py`) to load `reports/<name>_prose.yaml` (editorial content + the findings reports' provenance blocks). Not exercised by the optimization pipeline. Was previously a transitive dep through dspy/litellm; promoted to a direct dep when the report became data-driven.

## Dev dependency group — `pytest>=7.0`, `pytest-asyncio>=0.21`

Declared under `[dependency-groups].dev` (PEP 735), so it stays out of the published package's extras. `uv sync` installs it by default; `uv sync --no-dev` skips it.

The dev group also installs `setuptools>=68.0` and `wheel` for the synthetic repository's offline editable-build tests. These are explicit test prerequisites: [Python no longer seeds setuptools into new virtual environments](https://docs.python.org/3/library/venv.html) starting with Python 3.12. The repair harness exposes the selected base environment's dependency paths to the isolated build, without downloading build requirements while repository code executes. A real target must have its own build backend prepared in that base environment before the run.

`pytest-asyncio` is declared but not currently exercised by the test suite (no `@pytest.mark.asyncio` tests). Reserved for future async work.

## Optional extras

### `[miprov2]` — `dspy[optuna]>=3.4.1,<3.5`

Required only when GEPA fails and the MIPROv2 fallback fires. The import is lazy inside `_default_mipro_runner()` — install on demand:

```bash
uv pip install "agent-self-evolution[miprov2]"
```

If missing, the fallback raises `ImportError` (re-raised with the GEPA failure preserved as `__cause__` so the user sees both).

> Tier 4 (code repair) is built and needs **no extra engine dependency** — it reuses the DSPy/litellm proposer stack for whole-file rewrites. The population-search `darwinian-evolver` was evaluated and dominated by plain best-of-N at equal budget, so it was not adopted (see `reports/darwinian_evolver_evaluation.md`); the former `[darwinian]` extra has been removed.

## Implicit dependencies (not in pyproject.toml)

### `threading` (stdlib)

`evolution/core/lm_timing_callback.py` uses `threading.Timer` (heartbeats) and `threading.Lock` (in-flight bookkeeping + idempotent litellm hook registration). The `timer_factory` constructor kwarg lets tests inject a `FakeTimer` that doesn't actually sleep.

### `pathlib`, `dataclasses`, `typing` (stdlib)

Used pervasively. `typing.Protocol` + `runtime_checkable` for `SkillSource`.

## External services

### Execution containment backends

Repository-controlled setup, imports, tests, and benchmarks use offline,
capability-tested containment. Linux uses Bubblewrap; macOS uses the OS adapter
only for policies whose required guarantees it can establish. Backend binaries
are host prerequisites rather than Python dependencies. A successful launch or
installed version does not prove denied reads, denied networking, or cleanup.
See [containment capabilities](concepts/execution-safety.md#containment-capabilities).

Dependency retrieval is separately authorized and completes before repository
build execution. Missing offline build prerequisites cause refusal rather than
an unconfined or network-enabled build retry. Restricted destination access needs
an enforceable mechanism; Bubblewrap's network namespace alone is not an allowlist.

Native backend and dependency changes require current primary documentation and
observed compatibility checks. Preserve `engine="litellm"` and the DSPy 3.4 bounds
until custom engine migration is verified; add no speculative dependency ceilings.

### OpenAI API

The default LM provider. Three call patterns with different cost profiles:

| Caller | Model (default) | Volume per run | Notes |
|---|---|---|---|
| Dataset gen | `openai/gpt-4.1` | 1 call (60-example JSON output, 16K max_tokens) | Synthetic mode only |
| GEPA reflection | `openai/gpt-5-mini` | ~iterations × 1-2 calls | Reasoning model; long P99 (103s observed max) |
| GEPA per-iteration scoring | `openai/gpt-4.1-mini` | ~iterations × |trainset| × judge calls | Bulk |
| Holdout eval | `openai/gpt-4.1-mini` | 2 × |holdout| judge calls | Done twice (baseline + evolved) |
| Knee-point per-candidate static | none | 0 LM calls | Pure-Python validation |

Typical run cost (light budget on a small skill): **$0.50 - $2.00**. Heavy budget on a large skill: **$5 - $15**.

### Agent subprocesses (closed-loop validation)

Closed-loop validation and prompt-section evolution shell out to a real agent CLI per task; these are runtime dependencies, not Python packages.

| Tool | Used by | Auth | Notes |
|---|---|---|---|
| `hermes` CLI (`hermes -z`) | Hermes backend / closed-loop tool+skill suites | selected provider credential only | Private `HERMES_HOME`/`HOME` plus the execution policy; a home override alone is not containment. |
| `claude` CLI (`claude -p`) | Claude Code backend (`--target claude`) | `CLAUDE_CODE_OAUTH_TOKEN` env (from `claude setup-token`; subscription billing) — **not** `--bare`, which ignores the token | stream-json parsed for tool calls + cost. |
| OS containment backend | Repository execution and validation agents | n/a | Linux Bubblewrap or the capable macOS adapter. Required capability failures raise a containment refusal; agent Write/Edit tools are inside the same boundary. |

`litellm.cost_per_token` is used as a cost fallback in the Claude runner: subscription/OAuth runs report `total_cost_usd == 0`, so the runner prices the reported token usage via litellm to meter spend against `--max-cost-usd` (recorded as `computed`; a no-token run stays `uncaptured`).

### Local filesystem reads (sessiondb path)

| Source | Path | Format |
|---|---|---|
| Claude Code | `~/.claude/history.jsonl` | JSONL, one user message per line |
| Copilot CLI | `~/.copilot/session-state/<id>/{events.jsonl, workspace.yaml}` | JSONL events + YAML metadata |
| Hermes Agent | `~/.hermes/sessions/*.json` | OpenAI-format message list |

All reads are best-effort — missing files / dirs result in empty message lists, not errors.

### Skill source filesystem reads

| Source | Path | Layout |
|---|---|---|
| Hermes | `$SKILL_SOURCES_HERMES_REPO` or `~/.hermes/hermes-agent` | `<root>/skills/<category>/<name>/SKILL.md` |
| Claude Code | `~/.claude/plugins/cache` | `<vendor>/<plugin>/<version>/skills/<name>/SKILL.md` |
| LocalDir | passed via `--skill-source-dir` | `<root>/<name>/SKILL.md` |

Discovery walks all roots that exist; sources with missing roots are silently skipped.

## Build + tooling

### `setuptools>=68`, `wheel`

Build backend declared in `pyproject.toml`. Standard PEP 517 build.

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["evolution*"]
```

### `pytest` config

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

No third-party pytest reporting plugin is required. Repair execution uses the
harness-owned evidence plugin and strict reader described in the
[test evidence contract](reference/execution-contracts.md#test-evidence).
The framework's tests isolate provider configuration and authentication loading
centrally, alongside synthetic discovery roots. They require no live credentials
or global `Path.home()` workaround.

## What this codebase does NOT depend on

Worth noting because they often appear in similar projects:

- **No PyTorch / TensorFlow / JAX.** No GPU training; everything is API calls. `BootstrapFinetune` (the only DSPy component that trains weights) is explicitly excluded by the project plan.
- **No Pydantic.** Pure stdlib `dataclasses` + `typing.Protocol`. DSPy uses Pydantic internally but no Pydantic models are exposed by this codebase.
- **No FastAPI / Flask / web framework.** CLI-only.
- **No database.** All state is files (`output/`, `datasets/`, `~/.claude/history.jsonl`, etc.).
- **No additional async runtime dependency.** Evaluation uses threads; provider adapters also support async calls through Python's `asyncio`.
- **No Docker / container scaffolding.** Plain `uv sync` workflow.
- **CI uses GitHub Actions.** [.github/workflows/tests.yml](../.github/workflows/tests.yml) runs Ruff and pytest with mocked provider/agent calls.
