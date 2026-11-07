---
title: Deployment evidence for code repairs
description: Internal verification, diagnostic schemas, supervisor receipts, and snapshot export
doc_type: reference
maintenance: Update with verifier, receipt, diagnostic, or export contract changes
---

# [PLANNED - Implementation Pending] Deployment evidence for code repairs

This is the canonical specification for the intended evidence contracts below.
It does not certify source behavior, native containment, or implementation tests.
The schema tables are normative; source adapters must implement and validate them
before these guarantees can be claimed.

Both code gates use `evolution/code/deployment_evidence.py` to decide whether
execution evidence is eligible for deployment. The module is internal. Existing
repair and campaign entry points remain unchanged; there is no attestation
service, public certificate constructor, or CLI override.

## Contents

- [Authority and verifier inputs](#authority-and-verifier-inputs)
- [Verification schema 1](#verification-schema-1)
- [Cooperative diagnostic schema 2](#cooperative-diagnostic-schema-2)
- [Supervisor receipt schema 1](#supervisor-receipt-schema-1)
- [Diagnostic comparison and campaign accounting](#diagnostic-comparison-and-campaign-accounting)
- [Comparable regression evidence](#comparable-regression-evidence)
- [Snapshot and export contract](#snapshot-and-export-contract)
- [Capability limits](#capability-limits)

## Authority and verifier inputs

Protected parent orchestration establishes these expectations before candidate
execution. The candidate, its plugins, imports, builds, and fixtures cannot
modify the expectations, their transport, or the verifier's interpretation.

| Input | Binding checked by the verifier |
|---|---|
| Baseline | Approved repository and commit, original source, and trusted-input identity |
| Required checks | Reviewed exact identities, assertion/input contents, parameters, and configuration established independently of candidate collection |
| Candidate snapshot | Exact source bytes and regular-file modes, with authorized changed paths |
| Request | Private invocation association, selected executable/runtime identity, immutable policy and environment |
| Process observation | Valid supervisor receipt, observed supervisor completion, child exit, deadlines, containment and bounded cleanup |
| Semantic result | Assertions and interpretation independently protected from candidate control |
| Integrity | Scope, public-surface and retain-floor checks against the same snapshot, plus final export verification |

A node ID alone does not identify its assertion: replacing a test body while
retaining the name invalidates its identity. Candidate-reported collection cannot
choose the required population. A separately launched interpreter still offers
no independent proof if candidate code can replace its assertions or outputs.

The verifier rechecks protected associations. Deserializing a record, manually
constructing a `Verified`-style object, setting `TestRun.authoritative`, supplying
a hash or invocation ID, or replaying an earlier accepted result cannot authorize
export. Opaque bindings contain no persisted credential material or hashes
derived from credentials.

When no adapter independently verifies test semantics across this trust boundary,
verification returns `unverifiable` with
`independent_test_verification_unavailable`. Cooperative pytest and supervisor
receipts alone take this path even when every diagnostic test passed. Refusal
preserves diagnostics and does not certify a supported deployment flow.

## Verification schema 1

The code-path `gate_decision.json` includes `deployment_verification`. Its schema
is separate from the enclosing code gate schema and from prompt/skill/tool gates.

| Field | Value |
|---|---|
| `schema_version` | String `"1"` |
| `status` | `"accepted"`, `"rejected"`, or `"unverifiable"` |
| `reason` | Nonempty stable string identifying the verification outcome |

All three fields are required and nonnullable; no additional keys are supported.
Strict JSON decoding rejects duplicate keys and wrong types. The compact persisted
summary contains no authority token. The internal protected
association binds the full evidence listed above; reading this JSON never
recreates that authority. Missing or unsupported versions do not imply acceptance.

| Status | Meaning | Deployment |
|---|---|---|
| `accepted` | Independent proof and all integrity prerequisites satisfy the gate's behavioral rules | Eligible only while the accepted snapshot remains valid |
| `rejected` | A checked violation, such as a required failure, scope change, or payload mismatch, is established | Refused |
| `unverifiable` | Proof is missing, invalid, incomplete, unbound, or the required capability is unavailable | Refused; retain available diagnostics |

A demonstrated failure is not relabeled successful because other proof is
missing. Record established violations and unavailable checks separately; do
not call an infrastructure refusal a proven candidate failure.

The following is a summary of a complete green cooperative run without independent
semantic verification. It is a data example, not a certificate to import:

```json
{
  "deployment_verification": {
    "schema_version": "1",
    "status": "unverifiable",
    "reason": "independent_test_verification_unavailable"
  }
}
```

The enclosing decision refuses deployment. Repair `fixed` and diagnostic
comparison results may still be true. Neither implies deployment eligibility.

## Cooperative diagnostic schema 2

`pytest_evidence_plugin.py` produces schema `"2"`; `test_evidence.py` validates it
against the expected invocation, observed process status, cleanup, and reviewed
check identities. These are cooperative diagnostics throughout.

### Required fields and types

Every field below is required, including nullable fields. All objects use exactly
the listed keys. Decode strict JSON: reject duplicate keys, unknown keys or
versions, nonfinite numbers, and type coercion. Booleans are not integers. Strings
that identify invocations or node IDs are nonempty and NUL-free. Node IDs retain
exact spelling and parameters; readers never normalize or deduplicate them into
a successful record. Arrays contain strings unless another type is specified.

| Field | JSON type | Contract |
|---|---|---|
| `schema_version` | string | Exactly `"2"` |
| `invocation_id` | string | Current harness-generated request identity |
| `collected` | array | All collected node IDs before selection, in collection order; includes selected and deselected items |
| `selected` | array | Node IDs selected for this invocation, in collection order |
| `deselected` | array | Collected node IDs excluded from this invocation |
| `executed` | array | Selected node IDs with at least one observed phase, in selected order |
| `skipped` | array | Selected node IDs with a skipped phase or an expected-failure report, in selected order |
| `failures` | array | Selected node IDs with any failed phase, including teardown failures and strict unexpected passes, in selected order |
| `collection_errors` | array | Collector identities for failed collection reports; empty only when no collection error was observed |
| `collection_finished` | boolean | Collection reached its finish hook, including any reported collection errors |
| `session_finished` | boolean | The session finish hook ran; does not mean the tests passed |
| `exit_code` | integer or null | Raw pytest session status, `0`–`5`; null only when no session finish status was observed |
| `items` | array of item objects | Exactly one lifecycle record per selected node ID, in selected order |

Each item has exactly these fields:

| Field | JSON type | Contract |
|---|---|---|
| `nodeid` | string | Exact selected node ID |
| `setup` | phase object | Setup report or explicit absence |
| `call` | phase object | Call report or explicit absence |
| `teardown` | phase object | Teardown report or explicit absence |

Each phase object has exactly two fields:

| Field | JSON type | Contract |
|---|---|---|
| `outcome` | string | `"passed"`, `"failed"`, `"skipped"`, or `"not_run"` |
| `wasxfail` | boolean | Whether pytest marked this phase as an expected-failure report; false for `"not_run"` |

`not_run` records an unobserved phase, never an inferred pass. There are no
nullable item or phase fields and no optional fields in schema `"2"`.

### Lifecycle and reader invariants

- Collection IDs are unique. Selected and deselected IDs form an exact disjoint
  partition of collection. Duplicate collection or repeated phase reports make
  the record invalid; the producer must not silently overwrite them.
- Items match selection exactly. Executed, skipped, and failure lists equal the
  sets derived from item phases, with no duplicates or unexpected identities.
  Counts are derived from these arrays; no count can substitute for identities.
- Observed phases occur in setup/call/teardown order. A call can run only after
  passed setup. Failed or skipped setup requires `call.outcome="not_run"`.
  A selected item that never starts has all phases `"not_run"`.
- A complete observation requires finished collection with no collection errors,
  a finished session, matching observed child exit `0` or `1`, and verified
  cleanup. Every selected item has observed setup and teardown; passed setup
  also requires an observed call. Exit `1` requires at least one failure identity;
  exit `0` requires no failed phase. Exit `2`–`5`, unfinished collection, missing
  phases, or unknown process completion cannot support comparison success.
- Setup/call skips and expected failures can be completely accounted observations
  without satisfying required passing coverage. A required pass needs an actual
  passing call, passed setup and teardown, and no expected-failure marker.
  Required checks cannot be deselected, replaced, or absent. A reviewed expected
  failing check in a baseline/oracle comparison must actually execute with its
  reviewed outcome; skipping it cannot cancel a candidate failure.

The reader returns `complete: boolean`, `failures: set of node IDs`,
`error: string or null`, plus `missing`, `unexpected`, and `duplicates` identity
sets relative to the independently established required population. Missing
means required checks without qualifying execution; unexpected means observed
identities outside the reviewed collection/selection; duplicates reports repeated
identities or phase records. `error` is null only for a complete, valid record.
Invalid/partial records retain observations for diagnosis but cannot provide
failure sets for successful subtraction. Missing execution cannot be repaired
by changing totals or adding a synthetic passing record.

The reader associates diagnostics with one current invocation and its observed
process result. Reusing a schema `"2"` file in a different invocation, even with
the same test IDs, is invalid. Repeated reads for diagnostic display are allowed;
they cannot create a fresh execution observation or restore consumed deployment
authority. A retry requires fresh process and diagnostic observations.

An explicit capability skip in the framework's mock-only suite supplies no native
containment or deployment certification.

Legacy schema `"1"` is readable as limited diagnostics. Its counts and item
records lack the full identity contract; it is never upgraded to deployment
proof. `TestRun` compatibility fields remain usable by diagnostic consumers.

## Supervisor receipt schema 1

The supervisor reports process facts, not test semantics. Parent validation binds
receipt schema `"1"` to its protected request, supervisor, runtime and execution
scope. The receipt covers invocation binding, executable identity, child launch
and exit, timeout/cancellation, containment observations, cleanup, and errors.
Authority-bearing descriptors are closed before candidate execution. Candidate
read/write grants exclude supervisor transport, receipt storage and parent state.
A private pathname or nonce alone is insufficient protection.

### Required fields and types

Every field is required; only the fields explicitly marked nullable accept null.
The strict JSON decoding rules from [diagnostic schema 2](#required-fields-and-types)
apply recursively. This is a process receipt, separate from `ProcessResult`
(which also carries redacted stdout/stderr); output and secrets are not receipt
fields.

| Field | JSON type | Contract |
|---|---|---|
| `schema_version` | string | Exactly `"1"` |
| `invocation_id` | string | Current request identity |
| `policy_id` | string | Protected parent's immutable policy binding |
| `runtime_id` | string | Protected parent's prepared executable/interpreter identity |
| `snapshot_id` | string | Protected parent's exact input snapshot binding |
| `scope_id` | string | Protected parent's owned execution/cleanup scope binding |
| `launched` | boolean | Whether a child was successfully created |
| `exit_code` | integer or null | Observed child status; negative integers denote signals on POSIX; null when no exit was observed |
| `timed_out` | boolean | The task exceeded its runtime deadline |
| `cancelled` | boolean | Cancellation was observed, including cancellation before launch |
| `duration_seconds` | number | Finite nonnegative elapsed monotonic seconds, including cleanup |
| `capture_complete` | boolean | Both output captures finished without capture errors; says nothing about output contents |
| `containment` | containment object | Backend and separately observed guarantees |
| `cleanup_complete` | boolean or null | True only for certified completion of the entire owned scope; false for known incomplete/failed cleanup; null if unverified |
| `error` | string or null | Nonempty redacted launch, observation, capture, containment, or cleanup error; null when no such error was observed |

Binding strings are nonempty and NUL-free. They contain no credentials or
credential-derived hashes. Their presence alone proves no association; the parent
checks each against protected expectations and transport.

The containment object has exactly these fields:

| Field | JSON type | Contract |
|---|---|---|
| `backend` | string | `"bubblewrap"`, `"sandbox-exec"`, or `"unconfined"` |
| `read_isolated` | boolean or null | Observed enforcement of the approved readable roots |
| `write_confined` | boolean or null | Observed enforcement of the approved writable roots, including native file tools |
| `network_isolated` | boolean or null | Observed network isolation; false may be permitted only by an explicitly network-enabled policy |
| `descendant_cleanup_certified` | boolean or null | Whether this backend's descendant tracking and termination guarantee is certified |

For containment capabilities, true means verified, false means verified absence,
and null means unknown. No backend name implies a capability. Unknown or absent
required capabilities refuse execution or verification. An unconfined receipt
cannot claim read/write/network isolation. No fields are optional.

### Lifecycle and replay consumption

1. Before launch, the protected parent registers one outstanding invocation with
   its policy, runtime, snapshot, owned scope, and supervisor process association.
   Candidate code cannot alter that registration or access authority descriptors.
2. The supervisor observes launch, child status, deadlines, cancellation, capture,
   and bounded cleanup before finalizing one receipt. `launched=false` requires
   `exit_code=null`, `timed_out=false`, and either cancellation or a nonnull error.
   A launched child with unknown exit is incomplete even if another field is green.
3. The parent independently observes that the expected supervisor terminated
   successfully. Supervisor exit status and receipt-transport integrity are
   out-of-band prerequisites; self-reported completion cannot replace them.
4. Strict validation matches every protected binding. A completed execution requires
   `launched=true`, known child exit, `timed_out=false`, `cancelled=false`,
   `capture_complete=true`, `error=null`, required containment capabilities, and
   `cleanup_complete=true`. A nonzero child exit can be a valid completed failing
   test observation; a passing task additionally requires child exit zero. For a
   launched child, certified
   cleanup requires `descendant_cleanup_certified=true`.
5. A receipt is consumed once against its outstanding invocation, whether it
   yields success, failure, or refusal. A replay, second receipt, stale invocation,
   or mismatched association is invalid. Retries use fresh invocation identities
   and fresh observations. Persisted JSON can be inspected diagnostically but
   cannot recreate registration or reopen a consumed invocation. Internal gate
   stages may reference the same validated observation through protected parent
   state; they do not deserialize and consume the receipt again.

Timeout and cancellation may both be observed during a race; either prevents
successful task completion. Cleanup can succeed after either event, and the child
may eventually exit zero, without making the task successful. Cleanup failure or
uncertainty must remain explicit; `cleanup_complete=false` or null requires a
nonnull error. Contradictory claims, a failed supervisor, malformed transport, or
an unavailable protected association invalidate the receipt. Preserve valid
observations separately without trusting an invalid receipt's claims.
`KeyboardInterrupt` and `SystemExit` propagate after bounded cleanup. Neither a
valid receipt nor certified descendant cleanup establishes that assertions ran.

## Diagnostic comparison and campaign accounting

Both code gates preserve a `diagnostic_comparison` object independently of
`deployment_verification`. It has exactly two required nonnullable string fields:
`status` (`"passed"`, `"failed"`, or `"inconclusive"`) and `reason` (nonempty,
redacted explanation). No diagnostic status authorizes export.

| Diagnostic status | Meaning | Campaign seed |
|---|---|---|
| `passed` | Complete comparable execution satisfies the selected behavioral rules, scope, surface freeze, and any configured regression floor | `true` |
| `failed` | A diagnostic behavioral or integrity violation was established | `false` |
| `inconclusive` | Required diagnostic observations are incomplete or unavailable and no violation is established | No Boolean result; retain reason and partial observations |

`repair.fixed` is narrower: it records the repair loop's visible-test outcome,
not the full comparison. Independent semantic verification can be unavailable
while comparison is `passed`. In that case `CodeGateResult.deploy=false` and
`deployment_verification.status="unverifiable"` coexist with a successful
comparison; campaign accounting must not derive seed results from `gate.deploy`.
A proven failure remains recorded even when other checks are unavailable.

For the oracle gate, retain `decision="correct"` for diagnostic `passed` and
`decision="incorrect"` for diagnostic `failed`. Use `decision="inconclusive"`
when comparison cannot be established; do not overload `incorrect` for missing
proof. These oracle decisions remain measurement outcomes. The held-out gate
retains `decision="deploy"` or `"reject"` as deployment decisions and uses the
separate comparison object for its diagnostic result. In either gate,
`CodeGateResult.deploy` is true only when independent verification is accepted
and every deployment prerequisite holds for the current snapshot. Legacy oracle
`correct` records or historical `deploy=true` values contain no new authority.

Campaign `seeds` retains its Boolean-list meaning for fully measured organisms:
each true is a diagnostic comparison pass and each false an established failure.
`deploy_reachable` retains the compatibility rule `n_correct > 0` and
`2 * n_correct >= len(seeds)` (at least half, including an even-seed tie; two of
three for the default). Sentinel `correct_seeds` counts those true values and its
integer `seeds` is their total, not a count of deployment acceptances.

Unavailable independent proof alone neither changes these Booleans nor removes
an organism from the diagnostic denominator. If diagnostic measurement itself
is inconclusive, persist the seed identity, reason, and completed observations
under `run_inconclusive`; do not coerce it to false, shrink the requested seed
count, or finalize a partial Boolean row as a fully measured organism. Resume
only outstanding measurements with new invocation IDs. Reports distinguish
requested, measured, and inconclusive organisms/seeds and never silently drop
inconclusive cases from a reported denominator. Replaying ledger observations
resumes accounting only; it never restores deployment eligibility.

## Comparable regression evidence

Baseline and candidate evaluations have matching reviewed check and trusted-input
identities before failure sets are compared. The candidate snapshot naturally
differs from the baseline snapshot; required assertions and their interpretation
remain protected in both runs.

| Case | Rule |
|---|---|
| Existing-file floor | Complete comparable diagnostics precede candidate-minus-baseline failure subtraction |
| New-file floor | Complete green required execution; a missing baseline does not excuse failures |
| Oracle comparison | Complete required scope precedes subtraction from independently established oracle failures |
| Visible or held-out pass | Required checks actually execute and pass; held-out and visible selections differ |
| Incomplete run | No successful subtraction, even if every observed failure is already known |

A successful comparison is retained as a diagnostic result. Deployment additionally
requires independent verification and all snapshot/integrity prerequisites.

## Snapshot and export contract

Certification uses protected source, tests, configuration, runtime and evidence.
Scratch, cache, temporary files and outputs have separate writable locations.
A writable parent directory cannot shadow or replace protected inputs. Unsupported
protection is refused instead of replaced by pre/post hashes.

The parent captures exact candidate bytes and mode, baseline and trusted-input
identities, required checks, and invocation binding. Scope and surface checks
consume this snapshot; an earlier `RepairResult.final_source` string alone does
not identify the tested payload. Every later candidate-controlled execution,
including a benchmark, requires integrity reassessment. Relevant changes
invalidate prior acceptance and require fresh verification.

Export uses stored accepted snapshot bytes and mode under a protected final
verification/export boundary that prevents concurrent mutation. It rechecks the
destination after atomic replacement. Payload mismatch, mode drift or unavailable
protection refuses export. Export never reopens mutable candidate source and
assumes it still matches prior tests. Local review patches remain inspectable
without being deployment-certified artifacts.

Contained atomic writes preserve mode precedence and executable bits under a
restrictive umask; see [path access](execution-contracts.md#path-access).

## Capability limits

Linux certification depends on demonstrated host/backend capabilities, including
filesystem reads and writes, network and socket isolation, and descendant cleanup.
Bubblewrap is a containment building block; the caller's arguments define its
protection. Its [upstream security guidance](https://github.com/containers/bubblewrap#security)
explains this responsibility. Binary discovery and a no-op launch are insufficient.

macOS containment and cleanup require separate native evidence. Linux PID
namespaces or subreaper observations do not certify macOS descendants. Uncertified
macOS cleanup remains an explicit refusal. A write-only profile supplies no
confidential-read guarantee. Local mocks and capability skips establish neither
native protection nor hosted-CI success.

For runtime selection and refusal handling, use
[contained repairs](../howto/run-contained-repairs.md). For the reasoning behind
these boundaries, read [execution safety](../concepts/execution-safety.md).
