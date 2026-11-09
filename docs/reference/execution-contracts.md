---
title: Execution and evaluation contracts
description: Internal contracts for policies, environments, process cleanup, paths, and evaluation evidence
doc_type: reference
maintenance: Update with adapter, evidence, or authentication changes
---

# Execution and evaluation contracts

This reference defines the safety and completion contracts shared by repair,
validation, campaign, orchestration, and monitor execution. Existing tier APIs
remain the entry points; the execution records are internal adapter contracts.
The [deployment evidence reference](deployment-evidence.md) is canonical for
diagnostic/receipt field types, lifecycle and replay consumption. The
[semantic path](../protected_verification.md) specifies strict JSON-command
verification, trusted runtime configuration and single-use snapshot export.
Native guarantees require actual capability and lifecycle evidence in addition
to implementation conformance. The [evidence boundary](../protected_verification.md#evidence-boundary)
separates supported behavior, refusal, mock checks and native proof; the
[recovery boundary](../campaign_recovery.md#recovery-boundary) separates journal
reuse from live authority.

The protected semantic/export and production recovery requirements in this
reference are **[PLANNED — Implementation Pending]**. Protected setup and
retained-byte prerequisite replay still refuse. Complete billing coverage,
SWE-bench residual budgets and actual immutable identity verification remain
unresolved. Host provisioning alone cannot resolve these implementation gaps.
See the linked verification/recovery blockers before treating a requirement as
available behavior.

## Contents

- [Module responsibilities](#module-responsibilities)
- [Requests and policies](#requests-and-policies)
- [Environment configuration](#environment-configuration)
- [Execution results](#execution-results)
- [Path access](#path-access)
- [Git scope inspection](#git-scope-inspection)
- [Test evidence](#test-evidence)
- [Gate acceptance](#gate-acceptance)
- [Authentication](#authentication)
- [Validation and persistence](#validation-and-persistence)
- [Input and compatibility rules](#input-and-compatibility-rules)
- [PR preparation](#pr-preparation)

## Module responsibilities

| Module | Responsibility |
|---|---|
| `evolution/core/execution.py` | Immutable execution requests, policies, environments, and required capabilities |
| `evolution/core/sandbox.py` | Backend selection, behavioral capability checks, and enforceable execution scopes |
| `evolution/core/process_worker.py` | Protected supervisor receipts and bounded process observations |
| `evolution/core/process.py` | Runtime deadlines, file-backed capture, redaction, cancellation, and bounded cleanup |
| `evolution/core/paths.py` | Contained reads and writes, including access-time write protection |
| `evolution/core/git_scope.py` | Checked Git commands and complete changed-path inspection |
| `evolution/code/pytest_evidence_plugin.py` | Cooperative pytest lifecycle diagnostics |
| `evolution/code/test_evidence.py` | Strict diagnostic validation and invocation matching |
| `evolution/code/deployment_evidence.py` | Refusal-only compatibility helper and schema 1 summaries |
| `evolution/code/semantic_verifier.py` | Owned prepared context and authority-free semantic assessment |
| `evolution/core/protected_execution.py`, `verification_worker.py` | Dedicated single-process policy, bounded transport and trusted execution facts |
| `evolution/code/campaign_state.py` | Exclusive durable attempt/result journal and replay |
| `evolution/composition/monitor_code.py` | Lazy harvesting and attempt wiring between monitor and code |
| `evolution/code/worktree.py` | Disposable repair environment, protected snapshots, and existing `WorktreeEnv` adapter |
| `evolution/code/gate.py` | Shared verification plus surface, oracle, holdout, regression-floor, and scope decisions |
| `evolution/code/repair.py`, `evolve_code.py` | Diagnostic repair loop and export of accepted snapshot bytes and modes |
| `evolution/validation/runner_environment.py` | Selected provider credentials and roots from the selected executable |

Neutral execution modules do not import tiers. Core receives minimal data,
protocols, or callbacks; tier orchestration supplies concrete adapters. Lazy
imports do not exempt code from this boundary. Tier-specific adapters preserve
their existing result and exception semantics while delegating execution controls.
This contract does not introduce a separate public executor API or CLI.

## Requests and policies

| Request information | Validation |
|---|---|
| Argument vector | Nonempty sequence of NUL-free strings; `argv[0]` is nonempty; later arguments may be empty; no implicit shell interpretation |
| Working directory | Canonical, approved directory within the execution scope |
| Read and write roots | Explicit canonical roots; write access limited to authorized paths |
| Environment | Fresh string mapping for the execution class; nested collections are frozen |
| Network requirement | Offline, explicitly authorized network access, or an enforceable restricted policy |
| Runtime and cleanup limits | Finite positive numbers, excluding Booleans; checked before launch |
| Invocation identity | Harness-generated identifier shared across preparation, execution, evidence, and inspection |
| Capabilities | Required guarantees checked behaviorally before repository code executes |

`ExecutionPolicy` carries `read_roots`, `write_roots`, `network`, and `required`.
`ExecutionRequest` carries `argv`, `cwd`, `env`, `policy`, `timeout_seconds`,
`cleanup_timeout_seconds`, and `invocation_id`. Construction launches no process.
`prepare_environment` accepts an explicit parent mapping, execution kind, private
home/temp paths, selected credentials, and allowlisted overrides.

Caller-owned dictionaries and lists are copied and frozen. Mutating them after
request construction cannot alter a launched command's authority. Environment
overrides cannot replace protected roots, inject credentials, or weaken policy.

Preparation selects the executable once from approved runtime locations. The
same identity supplies launch and runtime read roots; ambient `PATH` or a second
lookup cannot select a different tool. Interpreter startup and inherited
descriptors are controlled. A private parent association binds the request to
its prepared runtime and policy; a public invocation string is not that binding.
Protected associations contain no credential-derived identifiers in diagnostics.

Policy failure is reported before repository code runs. Capability absence raises
a containment refusal such as `SandboxUnavailableError`. A failed capability probe
is a containment failure, not a pytest outcome or a skipped repair candidate.

## Environment configuration

Environments are constructed per invocation, never captured from `os.environ` at
module import. An environment variable being present in the parent grants no
permission to forward it.

| Execution class | Permitted environment and resources | Network |
|---|---|---|
| Dependency retrieval | Approved package-source settings and private download cache; no repository build execution | Explicitly authorized retrieval only |
| Setup/build, authority import, tests, benchmarks | Selected executable search path, private home/temp/cache, locale, harness-owned Python paths and execution settings | Offline |
| Validation agent | Runtime settings, private task configuration, and only the selected provider credential arrangement | Explicit policy; unsupported restrictions cause refusal |
| Post-agent test command | Repository-execution environment without the agent credential | Offline |
| Parent Git inspection | Controlled Git configuration and checked command behavior | No remote access |

`HOME`, `TMPDIR`, and cache paths point into private run storage. `PATH` names
approved runtime tools. `PYTHONPATH` is constructed from approved dependency and
worktree roots; the parent's value is not appended. Python and pytest settings
that can load external code or suppress evidence are not accepted as ambient
configuration. The harness controls plugin loading.

`TaskRunContext.extra_env` remains a `dict[str, str]` input. It is validated against
the selected execution class. Protected environment overrides are rejected before
launch. `skills_src` is a trusted, approved source directory, not authority for a
fixture to read an arbitrary host path.

Provider selection is deliberate and uses the existing resolver's aliases and
precedence. Explicit model selection precedes configured provider selection;
automatic selection resolves once before launch. For a chosen provider,
inline credentials precede its supported environment aliases, then its auth-store
entry. The child receives the selected arrangement in private configuration or
explicit supported variables; it never receives the entire developer auth store.

| Selected provider arrangement | Child configuration |
|---|---|
| Claude Code OAuth | `CLAUDE_CODE_OAUTH_TOKEN` for that invocation |
| OpenAI, Anthropic, OpenRouter API key | Selected provider's `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY` |
| Gemini | First supported selected alias, `GEMINI_API_KEY` then `GOOGLE_API_KEY` |
| Other Hermes providers | Existing canonical provider and supported aliases from `hermes_provider.py`; no fallback to an unrelated provider's key |
| Multi-field or refreshed credentials | Complete explicitly mapped arrangement for that adapter; partial or unsupported arrangements refuse before launch |
| Explicit supported no-auth provider | No credential fields; absence is deliberate, not failed discovery |

A single-key-only forwarding rule does not support every provider. Bedrock,
OAuth, and other multi-field adapters require an explicit mapping of their
necessary fields and resources; ambient credential chains are not forwarded.
An unsupported mapping is an actionable preparation refusal. Environment-only
Hermes authentication remains usable for supported mappings. Candidate tests
never inherit those agent credentials.

Code execution receives no provider, GitHub, cloud, SSH-agent, or unrelated service
credentials. A validation agent can read its selected credential; its authorization
does not extend to subsequent tests. Host credential directories and control
sockets remain outside the mounted inputs.

## Execution results

Results distinguish launch status, child exit status, timeout or cancellation,
duration, capture status, containment, and cleanup. An unknown state is distinct
from a verified negative or positive state.

The parent strictly validates supervisor receipt schema `"1"` against protected
expectations and successful supervisor completion. Duplicate keys, unknown
fields/schemas, wrong types, replay, stale or unbound receipts, and contradictory
states invalidate the observation. Child exit zero cannot repair a failed
supervisor. Receipt storage and authority-bearing descriptors remain inaccessible
to candidate code. See [supervisor receipts](deployment-evidence.md#supervisor-receipt-schema-1).

Raw stdout/stderr capture is private and transient. Durable diagnostics redact
known secret values in output, exception text, argument displays, URLs, and
headers. Request/environment representations, exceptions, traces, and durable
summaries omit raw arguments, credentials, and credential-derived hashes.
Only allowlisted structural metadata is retained. Redaction occurs before
truncation and persistence. Raw capture is not promoted on an error path. Cleanup removes transient capture under the same
bounded lifecycle.

The execution scope is cleaned after both success and failure, including
descendants that detach or retain inherited output descriptors. Failed or
unverified cleanup prevents authoritative deployment evidence. Cancellation and
interpreter exit propagate after bounded cleanup rather than becoming ordinary
test failures.

## Path access

| Boundary | Accepted | Rejected |
|---|---|---|
| Fixture keys | Nonempty relative file paths and string contents | Absolute paths, traversal, malformed mappings, escaping symlinks |
| Tool paths and test selectors | Valid contained paths, with supported node selectors parsed separately | Parent traversal, sibling-prefix aliases, unauthorized absolute paths |
| Skill/tool sources | Reads under explicitly approved discovery roots | Symlinks escaping the selected root or fixture-selected host directories |
| Worktree writes | Authorized relative source paths | Changes to tests, shared Git metadata, or paths outside the run scope |
| PR artifact destination | Contained relative destination in the disposable PR worktree | Absolute paths, traversal, symlink escapes |

Explicitly selected source roots may themselves be absolute. That does not permit
an artifact-relative path or fixture key to be absolute. Parsing validates syntax
and data types; filesystem access independently validates actual containment.
Only a single supported `./` prefix is normalized. Leading dots are not stripped
as an arbitrary character set.

Write operations protect against symlink replacement at access time, using
descriptor-relative operations or directories exclusively owned by the harness.
Resolving a pathname and later reopening it is insufficient.

`read_contained(root, relative)` returns regular-file bytes.
`write_contained(root, relative, data, mode=...)` atomically replaces a regular
file. Mode selection is explicit validated mode, otherwise existing destination
mode, otherwise private `0600` for a new file. Booleans, nonintegers, out-of-range
modes, and special privilege bits are rejected; ordinary `0000`–`0777` permission
bits are supported. The temporary file starts private, receives exact bytes and
its selected mode through `fchmod`, then is flushed, synced, and replaced through
the pinned parent. Restrictive umask cannot strip an intended executable bit.
No global umask change is required; failure cleans temporary files. The Python
[descriptor mode API](https://docs.python.org/3.10/library/os.html#os.fchmod)
provides the operation; atomic replacement alone does not preserve mode.

Import authority checks inspect every reported module and namespace-package path using path
containment, never string-prefix matching.

## Git scope inspection

The internal Git result has typed command status and diagnostics. Changed paths
come from checked, NUL-delimited inspection of staged, unstaged, and untracked
changes relative to the approved baseline. Rename source and destination paths
both participate in scope validation; spaces, newlines, and quoting remain part
of filenames.

A nonzero status, timeout, malformed output, or failed diff/status inspection
rejects scope evidence. Empty stdout on command failure never means a clean tree.
Scope is rechecked after every repository-controlled evaluation before its results
are used. Shared Git metadata stays outside candidate-writable mounts.

## Test evidence

`TestRun` retains `passed`, `output`, `duration_seconds`, and `exit_code`.
Unknown completion fields remain unknown for legacy callers. Its compatibility
properties, including `authoritative`, never grant deployment eligibility.
A manually constructed green `TestRun` cannot certify an execution.

Cooperative pytest schema `"2"` records identities for collection, selection,
execution, skips, deselections, failures, and full setup/call/teardown lifecycle.
The reader compares them with independently established required identities and
reports missing, unexpected, and duplicate identities. Schema `"1"` remains
limited legacy diagnostics; counts alone cannot prove required coverage.

Console summaries are diagnostic. Exit 1 requires complete failure identities
before any regression subtraction; exits 2–5, timeout, interruption, unfinished
collection, missing exit, or unverified cleanup cannot qualify. Exit 0 still
requires complete required coverage. Skipped, xfailed, deselected, replaced, or
unexecuted required tests cannot satisfy a passing check. Pytest reports these
outcomes separately; see its [skip and xfail reference](https://docs.pytest.org/en/stable/how-to/skipping.html).

The plugin runs with candidate code and can be forged. Its output, process
receipts, and typed verification constructors supply no independent semantic
proof. Exact schemas and trust requirements are in the
[deployment evidence reference](deployment-evidence.md).
SWE-bench retains its grading adapter; container text is not pytest evidence.

## Gate acceptance

Both `run_code_gate` and `run_code_oracle_gate` use
`gate.finalize_verification` as the accepting boundary. The compatibility
`verify_deployment` helper remains refusal-only, including its inert
`verification` keyword. Finalization checks protected evidence associations
rather than trusting supplied Booleans. Verification returns `accepted`, `rejected`, or `unverifiable`.
Missing independent semantic proof yields
`independent_test_verification_unavailable`, with deployment refused and
available diagnostic results retained. Explicit semantic/runtime configuration
selects the JSON-command verifier; no CLI switch turns cooperative
diagnostics into independent proof.

| Evaluation | Acceptance prerequisite in addition to independent verification |
|---|---|
| Visible and held-out repair tests | Complete required execution, expected passing outcomes, valid containment, scope, snapshot and cleanup |
| Regression floor with baseline | Complete comparable diagnostics with matching reviewed check and trusted-input identities before failure-set subtraction |
| New-file regression floor | Complete green required execution; no empty-baseline shortcut for a failed run |
| Oracle comparison | Complete required execution before failure comparison; partial known failures do not suffice |
| Benchmark command | Confined execution, bounded cleanup, valid completion, scope, and final snapshot recheck |
| Prompt deployment | Nonempty baseline and evolved reports without abstentions, including compiled-floor validation |

Scope, surface, diagnostics, regression/oracle, configured benchmarks, semantic
evidence and export all bind retained bytes, canonical target and ordinary mode.
Prerequisites run read-only before sealing. Every later candidate dispatch
revokes authority before execution, even if launch subsequently fails.
Export consumes stored accepted bytes, verifies the destination, and prevents
concurrent mutation throughout final verification and export.
The live gate result owns the snapshot lease and supplies the CLI's
opaque export handle separately from persisted decisions. The CLI must close
the result even if export is omitted or fails; see
[ownership and disposal](../protected_verification.md#gate-to-export-ownership).

Thresholds, tolerances, green cooperative reports, and successful surface checks
cannot override missing proof. Safe refusal does not establish a functioning
certified deployment flow; diagnostics and campaign accounting remain useful
without such certification. Campaign and sentinel seed results consume
`diagnostic_comparison`, never `gate.deploy`. The oracle gate preserves diagnostic
`correct`/`incorrect` meanings and records unavailable comparison as `inconclusive`;
missing independent proof alone does not change a measured pass. See
[comparison and denominator rules](deployment-evidence.md#diagnostic-comparison-and-campaign-accounting).

Per-seed campaign durability uses the protected [progress journal](../campaign_recovery.md).
Derived compatibility ledgers never substitute for committed seed state or live
export authority.

The dedicated semantic policy prevents additional processes and threads through
architecture-aware enforcement. It requires full bounded stdin delivery, both
output EOFs, no overflow, valid UTF-8, exit zero, effective limits and confirmed
scope termination/reaping. Address-space/CPU limits are per-process; demonstrated
creation denial limits the candidate workload to one process. `RLIMIT_AS` is not
a total kernel-memory or RSS guarantee. Aggregate scratch and descriptor/metadata
caps remain independently enforced. Process-group termination does not establish
scope-wide cleanup; generic detached-descendant probes remain separate from
semantic creation-denial probes. Missing evidence refuses execution/authority.

Production adapters durably attribute callbacks and reconcile registered
billable dispatches before declaring complete coverage. Callback prices alone
cannot establish completeness. Both Hermes and SWE-bench restore cumulative
known spend before dispatch; unknown cost or residual liability blocks finite
budgets. Read-only `CampaignJournal.inspect` validates pinned records without
writer initialization, repair or session append. Monitor annotations require
complete ordered queue identity; secondary reconstruction failures preserve the
original exception. See [campaign recovery](../campaign_recovery.md).

The planned version `"3"` progress contract requires durable starts before execution,
actual attempt-bound costs once and
terminals before aggregation. Resume rebuilds due stages, futility/limit decisions
and completion before scheduling. Interrupted starts retain uncertain work/spend;
exclusive validated durable reopen resolves persistence uncertainty. Monitor
progress is explicit through `progress_root`; its queue is a derived view. Total cost ceiling
increases require a durable [session audit](../campaign_recovery.md#budget-ceilings-and-session-audits);
other experiment limits remain identity-bound. Version `"3"` uses canonical
decimal-string money and durable dispatch/reconciliation records. Existing
version `"2"` numeric history retains its original interpretation and is not
automatically migrated.

## Authentication

Pending authentication failures are keyed by opaque credential identity and
generation, under a lock. Identities are not secret values. Sync and async
recovery contexts permit only a matching retry; successful matching inference
clears that condition. Re-minting a token or receiving an unrelated success does
not clear failures.

Terminal authentication failures, concurrent failures for other identities, newer
generations, and cost ceilings continue to abort. The recovered credential can
make its next call with callbacks still registered.

Error classification uses exception type and structured HTTP status before
bounded textual matching. A token count such as `4012` is not HTTP 401. Repair
proposer fallback handles malformed model output; authentication, rate limits,
infrastructure failures, cancellation, and interpreter exit propagate. Bad-request
configuration failures retain actionable redacted diagnostics.

## Validation and persistence

`require_complete_validation(report)` enforces deployment completeness. Empty or
abstained baseline/evolved reports abort prompt deployment with
`cl_eval_incomplete`, including compiled-floor evaluation. Diagnostic `decide()`
retains the established aggregate and win/loss rule and intentional abstention
ties. Empty console phases render safely without division by zero; a diagnostic
tie is not a deploy decision.

Artifact checksums are checked before every task, including cache hits and
consecutive tasks sharing a candidate. Prompt parsing and splicing use one byte
snapshot. Backups are inspected under the lock before recovery guidance is emitted.
Restoration preserves original bytes and modes.

Judge-score history and verdict-cache state are synchronized without recursive
lock deadlocks. Once a run directory exists, aborts persist an aborted decision
and available partial progress before exceptions propagate; storage failures are
reported explicitly. Monitor queues persist before attempts and after each
outcome. Campaign resume recovers only an identifiable incomplete final JSONL
record, retaining valid prior records; malformed interior records remain errors.

## Input and compatibility rules

| Surface | Contract |
|---|---|
| Task suites | Unique nonempty task IDs; string fixture paths/content; nonempty suites at parsing and programmatic scoring boundaries |
| Dataset ratios | Finite nonnegative ratios with a positive total; normalize consistently; a zero ratio produces an empty split; reject infeasible required minima |
| Judge scores | Finite numeric scores clamp to `[0, 1]`; malformed and non-finite scores use the neutral `0.5` fallback |
| Claude usage | Missing or null numeric usage becomes zero; malformed nonnumeric structures remain invalid rather than silently free |
| Skill discovery | Exact frontmatter name matches; unrelated undecodable files do not abort discovery |
| Plugin versions | Numeric version components order numerically; supported prereleases sort before the corresponding stable release; non-version directories use deterministic fallback ordering below valid versions |
| Session scrubbing | Credential-token boundaries avoid matching legitimate embedded hyphenated text |
| Lineage | Existing per-example score lists remain compatible; identity fields are additive only when justified by a consumer |
| Bootstrap | Two-sided percentile intervals of resampled mean paired deltas; no reverse-percentile or BCa claim |
| LM engine | Keep `engine="litellm"` so provider adapters and cost/failure callbacks remain active |
| DSPy | Preserve the documented 3.4 compatibility range until custom engine migration is validated |
| Judge reuse | Reuse model state within its owning judge configuration without a process-global credential cache |
| Container reads | Failed commands are errors, never file contents; temporary files are created securely |

Dependency bounds, lockfile changes, native CI coverage, and provenance changes
need their own evidence. Local mock results do not establish native containment
or hosted CI success. Package attribution derives from repository history and
retains the README's MIT attribution chain.

## PR preparation

PR artifact preparation uses a disposable worktree. The caller's active branch,
index, and unrelated files survive copy, hook, commit, and external-command
failures. Temporary copies are removed on failed writes or replacements. Cleanup
targets only the owned worktree; it does not prune another active run.

Preparation does not authorize publication. Push and PR creation remain separate
explicitly authorized operations. Hooks and signing remain enabled. Repair trace
data is reused in memory for descriptions rather than reread merely to build the
same body. See [local remediation delivery](../howto/review-local-remediation.md).
