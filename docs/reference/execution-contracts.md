---
title: Execution and evaluation contracts
description: Internal contracts for policies, environments, process cleanup, paths, and evaluation evidence
doc_type: reference
maintenance: Update with adapter, evidence, or authentication changes
---

# Execution and evaluation contracts

**[PLANNED - Implementation Pending]** This reference specifies the intended
safety and completion contracts for repair, validation, campaign, orchestration,
and monitor execution. Except for the implementation boundary below, statements
in this reference are requirements to build and verify, not claims of enforcement.
Existing tier APIs remain the entry points; execution records are internal
adapter contracts.

## Contents

- [Implementation boundary](#implementation-boundary)
- [Module responsibilities](#module-responsibilities)
- [Requests and policies](#requests-and-policies)
- [Environment configuration](#environment-configuration)
- [Execution results](#execution-results)
- [Path access](#path-access)
- [Git scope inspection](#git-scope-inspection)
- [Test evidence](#test-evidence)
- [Gate acceptance](#gate-acceptance)
- [Independent verification and eligible execution](#independent-verification-and-eligible-execution)
- [Authentication](#authentication)
- [Validation and persistence](#validation-and-persistence)
- [Input and compatibility rules](#input-and-compatibility-rules)
- [PR preparation](#pr-preparation)

## Implementation boundary

The documentation checkout contains the base implementation; recovered execution
changes remain in a separate implementation worktree. Do not infer integration
from a module name in this specification. The following distinctions are based on
source inspection, not fresh native execution or full-suite verification.

| Surface | Recovered implementation | Planned requirement still to verify or implement |
|---|---|---|
| Environment | `prepare_environment` constructs an immutable mapping, filters most inherited values, and restricts extras, but **inherits parent `PATH`** (falling back to `os.defpath`) | Select trusted runtime paths, validate executable identity and interpreter startup; ambient search paths must not select trusted launch components |
| Pytest records | Plugin and `read_test_evidence` check schema `"1"`, invocation ID, collection counts, phase outcomes, exit consistency, and a supplied cleanup flag | Parent-owned exact node selection, payload/test identity binding, sufficient passing coverage, and independent verification |
| `TestRun.authoritative` | Checks cooperative evidence completeness, cleanup, invocation, and exit/failure consistency; code gates consume this property | Separate diagnostic completeness from deployment eligibility; do not promote cooperative records to authority |
| Deployment gate | Existing comparison and scope checks can produce `decision="deploy"` without all requirements below | Require independently verified containment, supervisor completion, certified cleanup, artifact identity, trusted coverage, and scope before behavioral acceptance |
| Independent verifier | No supported adapter or eligible execution path establishes this independence | Implement the verifier boundary described below and its gate consumer |

**Deployment is blocked under this specification for cooperative pytest evidence.**
The recovered code does not yet enforce every prerequisite or this separate block.
A green run or emitted `deploy` value is a diagnostic outcome, not proof that the
proposed deployment contract is satisfied. No current CLI flag enables independent
verification. Mock checks and the offline tutorial do not verify native containment.

## Module responsibilities

**Planned module responsibilities:** this table is not an installed-module inventory.

| Module | Responsibility |
|---|---|
| `evolution/core/execution.py` | Immutable execution requests, policies, environments, and required capabilities |
| `evolution/core/sandbox.py` | Backend selection, behavioral capability checks, and enforceable execution scopes |
| `evolution/core/process.py` | Runtime deadlines, file-backed capture, redaction, cancellation, and bounded cleanup |
| `evolution/core/sandbox_worker.py`, `process_worker.py` | Contained launch and supervision, with authority records outside payload control |
| `evolution/core/paths.py` | Contained reads and writes, including access-time write protection |
| `evolution/core/git_scope.py` | Checked Git commands and complete changed-path inspection |
| `evolution/code/pytest_evidence_plugin.py` | Harness-owned pytest lifecycle reporting |
| `evolution/code/test_evidence.py` | Strict evidence validation and invocation matching |
| `evolution/code/worktree.py` | Disposable repair environment and existing `WorktreeEnv` adapter |
| `evolution/code/gate.py` | Surface, oracle, holdout, regression-floor, and scope decisions |

Neutral execution modules do not import tiers. Core accepts minimal data,
protocols, or callbacks; tier orchestration constructs concrete adapters. Lazy
imports and suppressed annotations do not bypass this boundary. Adapters preserve
their existing result and exception semantics while delegating execution controls.
This contract does not introduce a separate public executor API or CLI.

## Requests and policies

| Request information | Validation |
|---|---|
| Argument vector | Nonempty executable and string arguments; no implicit shell interpretation |
| Working directory | Canonical, approved directory within the execution scope |
| Read and write roots | Explicit canonical roots; write access limited to authorized paths |
| Environment | Fresh string mapping for the execution class; nested collections are frozen |
| Network requirement | Offline, explicitly authorized network access, or an enforceable restricted policy |
| Runtime and cleanup limits | Finite positive values, checked before launch |
| Invocation identity | Harness-generated identifier shared across preparation, execution, evidence, and inspection |
| Capabilities | Required guarantees checked behaviorally before repository code executes |

`ExecutionPolicy` carries read roots, write roots, network policy, and whether
containment is required. `ExecutionRequest` carries `argv`, `cwd`, `env`, `policy`,
`timeout_seconds`, `cleanup_timeout_seconds`, and `invocation_id`.
`prepare_environment` takes an explicit parent mapping, execution kind, private
home/temp paths, an optional selected credential, and permitted overrides.
Constructing these records launches no process and performs no provider discovery.
Backend capability probes belong to the launch phase.

Caller-owned dictionaries and lists are copied and frozen. Mutating them after
request construction cannot alter a launched command's authority. Environment
overrides cannot replace protected roots, inject credentials, or weaken policy.

Preparation resolves the executable through trusted runtime locations, verifies
its identity, and controls interpreter startup settings and inherited descriptors.
Candidate-controlled search paths cannot select the supervisor or interpreter.
Grant validation accounts for protected descendants beneath writable parents:
granting a parent cannot grant writes to trusted tests, harness code, Git metadata,
capture ownership, or supervisor records. Unsupported combinations are refused.

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
| Validation agent | Runtime settings, private task configuration, and only the explicitly selected provider credential | Explicit policy; unsupported restrictions cause refusal |
| Post-agent test command | Repository-execution environment without the agent credential | Offline |
| Parent Git inspection | Controlled Git configuration and checked command behavior | No remote access |

`HOME`, `TMPDIR`, and cache paths point into private run storage. `PATH` names
approved runtime tools. `PYTHONPATH` is constructed from approved dependency and
worktree roots; the parent's value is not appended. Python and pytest settings
that can load external code or suppress evidence are not accepted as ambient
configuration. The harness controls plugin loading.

This is the **target environment contract**. The recovered
`prepare_environment` still copies parent `PATH`; filtering other variables does
not establish trusted executable selection.

The trusted parent prepares provider configuration from supported data fields
and the selected credential. It does not copy complete developer configuration
or authentication stores into the private home. Executable hooks, plugins,
unrelated provider entries, and inherited discovery paths are excluded.
Unsupported configuration or authentication causes an actionable refusal,
never a fallback to host configuration discovery in the child.

`TaskRunContext.extra_env` remains a `dict[str, str]` input. It is validated against
the selected execution class. Protected environment overrides are rejected before
launch. `skills_src` is a trusted, approved source directory, not authority for a
fixture to read an arbitrary host path.

Code execution receives no provider, GitHub, cloud, SSH-agent, or unrelated service
credentials. A validation agent can read its selected credential; its authorization
does not extend to subsequent tests. Host credential directories and control
sockets remain outside the mounted inputs.

## Execution results

Results distinguish launch status, child exit status, timeout or cancellation,
duration, capture status, containment, and cleanup. An unknown state is distinct
from a verified negative or positive state.

Raw stdout/stderr capture is private and transient. Durable diagnostics redact
known secret values in output, exception text, argument displays, URLs, and
headers. Redaction occurs before truncation and persistence. Raw capture is not
promoted on an error path. Cleanup removes transient capture under the same
bounded lifecycle.

Capture has an enforced size limit while the child runs, not merely a display
truncation after exit. Overflow is an execution failure and triggers bounded
cleanup. Capture files and launch resources are owner-restricted; only approved
descriptors cross the launch boundary.

The execution scope is cleaned after success, failure, timeout, cancellation,
and partial launch failure, including
descendants that detach or retain inherited output descriptors. Failed or
unverified cleanup prevents authoritative deployment evidence. Cancellation and
interpreter exit propagate after bounded cleanup rather than becoming ordinary
test failures.

Containment and supervisor evidence bind to the invocation, payload identity,
and actual enforced launch configuration. A requested policy or `sandboxed` boolean
alone is insufficient. The parent validates supervisor completion separately
from the child exit and cleanup certification. Normal exit does not certify
descendant cleanup, including on macOS. Unknown certification keeps the result
deployment-ineligible or causes refusal before launch.

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

`read_contained(root, relative)` returns bytes and
`write_contained(root, relative, data, *, mode=None)` writes bytes atomically.
Both use descriptor-relative access so concurrent symlink replacement cannot
redirect a source read or destination write. Writes preserve the required mode
and remove their own temporary file on failure. Exact relative-path identity is
retained through validation and scope comparison. Resolving a pathname and later
reopening it is insufficient. These checks apply at fixture, artifact, skill,
tool, and durable-state boundaries. Import authority
checks inspect every reported module and namespace-package path using path
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

`inspect_scope(root, *, invocation_id)` returns `ScopeResult` with `ok`, `paths`,
`error`, and `invocation_id`. Its checked, bounded inspection covers both endpoints
of copies as well as renames and consumes complete NUL-delimited records. Actual
worktree and gate callers consume this result; an unused helper supplies no
scope evidence.

## Test evidence

`TestRun` retains `passed`, `output`, `duration_seconds`, and `exit_code`.
Additional completion information is additive and defaults to unknown for legacy
callers. A manually constructed or historical result without evidence cannot
authorize deployment solely because `passed` is true.

Under the proposed contract, `TestRun.authoritative`, retained for compatibility, describes diagnostic
completeness only. Deployment eligibility is assessed separately.
`read_test_evidence` validates lifecycle records against parent-owned expectations;
`TestEvidence.complete`, `failures`, and `error` describe that validation result,
not deployment authorization.

The required evidence contract is below. The recovered plugin and reader only
implement the subset listed in [implementation boundary](#implementation-boundary).

| Evidence | Requirement |
|---|---|
| Format | Supported versioned lifecycle format; missing, legacy, unknown-major, or contradictory authority records cannot authorize deployment |
| Invocation and scope | Match the parent-owned request, payload and trusted-test identities, process result, and inspected worktree |
| Collection | Completed collection, exact expected selected node IDs, accounted deselections, and no collection errors |
| Outcomes | Setup, call, teardown, skips, and failure/error identities without silent omissions |
| Completion | Consistent session-finish record and raw pytest exit status |
| Execution | No timeout, interruption, internal/usage error, or incomplete cleanup |
| Record integrity | Parseable records, unique identities, valid lifecycle transitions, consistent totals, and process/session consistency |

Deselected tests are accounted for but cannot silently remove required oracle or
holdout coverage. A skipped outcome does not prove that a required test passed.
An all-skipped or empty required evaluation cannot authorize deployment. Evidence
validation distinguishes skips and expected-failure outcomes from executed passes.
The parent chooses required coverage before launch and protects its expectations
from candidate writes. A complete session running the wrong tests is incomplete
evidence for the requested evaluation. Partial oracle matches cannot satisfy
selection, and regression floors require the full expected scope.

Console summaries are diagnostic only. Suppressing them cannot turn a failed run
into an empty failure set. Exit 1 needs complete structured failure evidence;
exits 2–5 and missing exits are non-authoritative. Exit 0 still requires complete
evidence and the required coverage. SWE-bench uses its own grading adapter rather
than pretending container output is pytest evidence.

These records are cooperative evidence and can be forged inside the candidate
interpreter. Invocation identifiers and record hashes do not establish independent
attestation. If verification lacks the required independence from that interpreter,
the proposed gate must refuse deployment. That refusal is not fully implemented
in the recovered gate. Diagnostic accounting remains available. See the
[trust boundary](../concepts/execution-safety.md#test-evidence-and-deployment).

## Gate acceptance

**Planned prerequisites:** the recovered gate does not implement every check in
this section. Its comparison result must not be treated as deployment authority.

| Evaluation | Acceptance prerequisite |
|---|---|
| Visible and held-out repair tests | Complete required execution, expected passing outcomes, valid scope and cleanup |
| Regression floor with baseline | Complete baseline and candidate evidence for comparable scope before failure-set subtraction |
| New-file regression floor | Complete green candidate execution; no empty-baseline shortcut for a failed run |
| Oracle comparison | Complete execution before comparing failure identities; partial known failures do not suffice |
| Benchmark command | Confined execution, bounded cleanup, valid completion and Git scope; shell text confers no extra authority |
| Prompt deployment | Complete baseline and evolved reports, including compiled-floor validation |

Existing comparison rules apply after these prerequisites. A threshold, tolerance,
or surface-freeze pass cannot override missing execution evidence. An unsupported
or inconclusive run remains rejected or explicitly non-authoritative.

Deployment checks containment, certified cleanup, valid supervisor evidence,
completed execution, complete trusted test evidence, sufficient evidence
independence, checked scope, artifact integrity, and behavioral acceptance
independently. An unconfined diagnostic run is always ineligible. A complete,
confined evaluation with independently trustworthy verification and all comparison
conditions met is the intended acceptance path. It requires the verifier below;
no eligible deployment path is implemented merely by satisfying pytest accounting.

## Independent verification and eligible execution

**[PLANNED - Implementation Pending]** The supported initial eligible path will be
black-box evaluation of a tool with a bounded, serializable request/response
interface. Tools requiring trusted tests to import candidate Python into the
verifier process are outside this path and remain diagnostic-only. There is no
implemented verifier adapter, selection flag, or deployment-evidence schema for
this path yet. SWE-bench's grading adapter is separate and is not implicitly
certified by this specification.

The mechanism must maintain these boundaries:

1. A trusted parent freezes the candidate payload, approved runtime, baseline,
   trusted test suite, required case identities, and comparison policy before
   launch. It records their content identities outside candidate write access.
2. A trusted verifier runs outside the candidate interpreter and writable scope.
   It owns the tests, expected outcomes, case selection, and result channel. It
   never imports candidate code, loads candidate plugins, or deserializes
   executable candidate objects. Candidate setup cannot change verifier inputs.
3. Candidate code runs only inside the contained worker. The verifier sends
   bounded data requests and validates bounded data responses through a defined
   protocol. Candidate output is observed behavior, never an asserted pass/fail
   result. The verifier computes outcomes against its protected expectations.
4. The trusted supervisor separately reports the actual launch policy, invocation
   and payload identities, exit status, capture status, and cleanup certification.
   Its completion channel and verifier records must be inaccessible to candidate
   writes. Replayed, missing, mismatched, or contradictory records fail validation.
5. The parent validates both channels, rechecks payload integrity and Git scope,
   and requires every selected case to be accounted for. Empty/all-skipped runs,
   missing required passes, timeouts, protocol errors, and unknown cleanup block
   deployment. Baseline, candidate, and oracle comparisons use the same trusted
   cases and policy wherever the comparison requires those arms.

Only after these checks may existing surface-freeze, held-out, oracle, and
regression rules authorize deployment. The implementation must demonstrate a
positive eligible evaluation as well as rejection of forged cooperative records,
wrong selection, replayed evidence, payload drift, and incomplete cleanup.
Moving the same candidate-authored pytest JSON to another process, hashing it,
or signing it does not supply independent verification.

## Authentication

Pending authentication failures are keyed by opaque credential identity and
generation, under a lock. Identities are not secret values. Sync and async
recovery contexts are scoped to the authentication attempt and permit only a
matching retry; successful matching inference
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
Persistence failures do not replace the initiating exception. Cancellation keeps
the original exception identity after bounded cleanup and progress persistence.

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
