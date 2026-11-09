---
title: Campaign progress and recovery
description: Durable attempts, committed seed reuse, identity checks, and uncertain cost accounting
doc_type: reference
contract_version: "3"
implementation_status: planned; production accounting and identity integration incomplete
maintenance: Update with journal, adapter, identity, or reporting changes
---

# Campaign progress and recovery

**[PLANNED — Implementation Pending]** This reference defines the intended
version `"3"` recovery contract for Hermes, SWE-bench and configured monitor
attempts. Present-tense requirements below specify the feature to build, not
current implementation conformance. The existing implementation writes version
`"2"`; version `"3"` decimal strings and dispatch/reconciliation records are
planned wire changes, not an available resume format.

Durable callback attribution and scoped recovery corrections exist, but complete
production billing coverage, paid-preparation reconciliation and SWE-bench
residual-ledger integration remain unresolved. Production unknown coverage
blocks subsequent finite-budget dispatch. Production identity declarations are
shape-checked; actual immutable provider/runtime/harness/dataset/image identity
verification and dispatch of verified material remain unfinished. Host
provisioning cannot resolve these implementation gaps. Protected setup and
prerequisite replay also still refuse; see
[verification blockers](protected_verification.md).

Under the intended contract, committed measurements survive a restart; unknown
spend and unresolved execution identities refuse finite-budget dispatch.

A protected journal commits each seed result before dependent work. Resume reuses
committed measurements and reconstructs organism, stage and campaign decisions
before scheduling execution. Exactly-once reuse applies to committed results;
a crash between execution and durable commit leaves an inconclusive attempt,
with possible spend, rather than proof that execution never occurred.

This contract covers code campaigns, SWE-bench and configured monitor attempts.
Use the [resume guide](howto/resume-code-campaign.md) for operation. Diagnostic
success is separate from [export authority](protected_verification.md).

## Contents

- [Recovery boundary](#recovery-boundary)
- [Storage and writer ownership](#storage-and-writer-ownership)
- [Identities and compatibility](#identities-and-compatibility)
- [Resolved identity checks](#resolved-identity-checks)
- [Budget ceilings and session audits](#budget-ceilings-and-session-audits)
- [Monetary encoding and version compatibility](#monetary-encoding-and-version-compatibility)
- [Journal envelope](#journal-envelope)
- [Record payloads and transitions](#record-payloads-and-transitions)
- [Cost observations](#cost-observations)
- [Seed and aggregate accounting](#seed-and-aggregate-accounting)
- [Interruption and durable recovery](#interruption-and-durable-recovery)
- [Adapter interfaces](#adapter-interfaces)
- [Errors and historical records](#errors-and-historical-records)

## Recovery boundary

The [partial findings synthesis](../.review/implementation-20261109/FINDINGS.md)
records surviving evidence and open obligations, not final acceptance. Its
[location amendment](index.md#findings-artifact-location) reconciles the design's
proposed root artifact with the retained review location.

The journal records measurements and accounting, not live export authority.
Resume reuses complete compatible records, retains uncertainty and refuses
incompatible state. A version string alone cannot supply missing identities,
sessions, attempt ownership or cost coverage. Legacy injected runners provide
whole-organism durability; progress-aware runners provide per-seed durability.
Neither promises exactly-once execution across a crash before durable commit.

## Storage and writer ownership

`campaign_progress.jsonl` is authoritative. `campaign_ledger.jsonl`, queue
annotations and `campaign_report.json` are derived outputs, never replacements
for committed progress or live export authority.

The framework pins a protected output root outside candidate-accessible mounts.
It rejects traversal, substituted ancestors, symlinks, devices, FIFOs and unsafe
modes. Journals and `campaign_progress.lock` use `0600`; private directories use
`0700`. A session-long exclusive OS lock covers replay, recovery and append.
A second writer gets `campaign_writer_busy`. The lock file stays after release;
its existence is not a held OS lock. Deleting it can split writer ownership.

One validator governs both append and replay. Append validates the record and
transition, writes the complete bounded record and newline, flushes and fsyncs
before acknowledging. Initial creation also synchronizes the directory.
Short writes, failed synchronization or lost acknowledgments poison the session:
no dependent execution proceeds until an exclusive validated durable reopen.
Derived outputs use file/directory synchronization; failure to replace a report
does not erase authoritative progress.

## Identities and compatibility

Identities use the type-sensitive, domain-separated
[canonical encoding](protected_verification.md#strict-json-and-identities).
Initialization stores the full nonsecret identity manifest for mismatch diagnosis.
Credentials and credential-derived hashes are excluded.

| Identity | Required applicable inputs |
|---|---|
| Campaign | Repository, full ordered requested population, stages, seeds, method, configured limits/stops, reporting algorithm and journal version |
| Organism | Raw source/test blob hashes, full baseline/fix/oracle commits, tool/test paths, repository identity and adapter kind |
| Seed | Organism, index and explicit seed value, resolved repair/gate/proposer configuration and prepared runtime identities |
| Configuration | Resolved nonsecret provider/model/generation options, dependencies/tool versions, source limits, policy/backend and framework implementation |
| SWE-bench | Instance, test/dataset identities, immutable image digest, architecture, harness and build inputs |

Diagnostic and semantic runtimes have distinct identities. A pathname, mutable
image tag, unresolved default or placeholder cannot satisfy a required identity.
Resolve these identities before journal initialization and dispatch, then freeze
them for the campaign. Provider/model identity includes an immutable model
revision where applicable; a mutable alias cannot establish it. Runtime identity
covers the interpreter, complete dependencies, harness and policy. Dataset rows
and candidate identities are hashed in their declared order. SWE-bench production
entry points require explicit resolved image content/platform, harness and
dataset identities before execution. Unknown required inputs refuse compatible
resume. A callable adapter is not
implicitly synthetic. Seed values do not promise deterministic provider sampling.

Changing a result-affecting input, requested population/order, seed count,
stage schedule, runtime, containment policy or configured organism limit requires
a different campaign directory. `max_organisms` bounds valid measured organisms;
it does not truncate the requested population. The campaign-wide cost ceiling
may increase for outstanding work under the
[session audit contract](#budget-ceilings-and-session-audits); it cannot rewrite
committed observations. This is the only mutable budget setting.
Ephemeral invocation IDs and temporary paths are not experiment identities.

## Resolved identity checks

Declarations describe expected execution. Verification establishes what actually
executes and retains that material for dispatch. Neither a mutable mapping nor a
successful generic subprocess establishes identity.

| Material | Verification before dispatch and compatible resume |
|---|---|
| Provider/model | Resolve the actual provider, endpoint and immutable model revision through supported adapter evidence; compare the actual request configuration. An alias or operator-written revision alone is insufficient. |
| Runtime | Retain the interpreter, dependencies, loader and framework implementation identities; reject substitution and dispatch the verified material. |
| Harness | Bind the actual harness source, configuration, build inputs and execution adapter rather than a declared version string. |
| Dataset | Hash exact selected rows, source/test blobs and full ordered population; preserve that order when dispatching and reconstructing results. |
| Container | Resolve immutable image content and platform/architecture, verify applicable build inputs and run that image rather than resolving its tag again. |

Production entry points and supplied `progress_runner` paths share this boundary.
Supplying a callable does not classify work as synthetic or exempt it from
billing or identity checks. A provider without a verifiable required immutable
revision refuses dispatch. A changed required identity refuses resume with
`campaign_state_incompatible` before spend; completed results stay committed and
are never rerun to manufacture compatibility. This does not require a paid
verification call or an arbitrary package installer.

## Budget ceilings and session audits

The total ceiling controls scheduling against cumulative campaign cost across all sessions; it is never a
fresh allowance per invocation. `--max-cost-usd` (and the Python `max_cost_usd`
argument) requests this total ceiling. A process-local cost ledger must be
seeded from replayed measured and estimated observations before dispatch; a
restart cannot reset spent cost to zero. In-flight calls may finish after a
ceiling is reached, so this is a dispatch guard, not a provider billing cap.

### Immutable inputs and permitted changes

`campaign_initialized.configuration.budget_policy` contains exactly `currency`
(`"USD"`), `scope` (`"campaign_total"`), `initial_ceiling_usd` (null or a finite
nonnegative canonical decimal string) and `change_rule` (`"increase_only"`).
This original policy participates in campaign identity and is never rewritten.
The effective ceiling is session state, excluded from campaign, organism, seed
and result-affecting configuration identities. On resume, compare immutable
inputs against the stored initialization; do not substitute the newly requested
ceiling into the initialization to recompute its identity.

Only a finite total USD ceiling can increase. A finite ceiling cannot decrease
or become null; null denotes an explicitly uncapped initial policy and can only
remain null in that campaign. Equal ceilings are unchanged. An omitted ceiling
on resume inherits the last committed value; omission never removes a cap. Invalid
changes raise `campaign_state_incompatible` without dispatch or audit append.

All other limits remain identity-bound: organism count, population/order, seeds,
stages/futility rules, repair rounds, per-call tokens/generation settings, source
and transport bounds, per-case CPU/wall/memory/process/scratch limits and runtime
or containment policy. Changing any of these requires a new campaign directory,
even when described as a budget increase. Seed identities bind these immutable
limits, not the session ceiling. No session record changes a committed stop,
completed measurement or its cost.

### Durable session record

Store the audit as a `session_started` record in `campaign_progress.jsonl`, under
the same exclusive lock, strict JSON bounds, hash chain and fsync/reopen barriers.
A separate log or report is not authoritative. Its payload contains exactly:

| Field | Type and rule |
|---|---|
| `session_id` | Unique NUL-free string, 1–128 UTF-8 bytes; retained across identical append retries, new after a process restart |
| `previous_session_record_hash` | Null for the first session; otherwise the digest of the immediately preceding `session_started` record |
| `previous_ceiling_usd` | Initial ceiling for the first session; otherwise the last committed session ceiling |
| `ceiling_usd` | Null or canonical nonnegative decimal string, subject to the change rules above |
| `reason` | `initial`, `resume` or `ceiling_increase` |

The first session follows initialization before any candidate execution or
provider spend, including paid preparation. It uses `reason="initial"` and both
ceilings equal the initial policy. Every writing process, including a writable reopen or forked child, establishes
its own current durable session. Replayed session state does not authorize that
process to dispatch. Every subsequent writable invocation that
will dispatch work commits a new session after validated replay and recovery,
before execution or spend. Its reason is `resume` for an unchanged ceiling or
`ceiling_increase` for a strictly larger finite ceiling. Work records belong to
the nearest preceding session record; no extra field is inferred or added to
their exact payload schemas. A recovered cost observation still belongs to its
original attempt, irrespective of which session persists it.

### Replay and failure rules

Append and replay use the same validator: require initialization first, validate
session ID uniqueness, link to the last session record, require exact previous
ceiling equality and verify the reason/change relation. A work start, cost
observation or paid preparation cannot precede the first durable session.
Recovery can close prior outstanding attempts and reconstruct aggregates without
spending; the next dispatch requires a new durable session. Read-only inspection
and reuse of an already-completed campaign need no new session record. A writer
appending recovered accounting after completion does require a new unchanged-ceiling
`resume` session. Only session/accounting records may follow committed campaign
completion; no new starts, diagnostic outcomes or stage decisions are allowed.
Committed completion or stop cannot be reopened by raising a ceiling.

Replay reconstructs the effective ceiling solely from valid session records.
An identical live API retry returns the existing record hash; conflicting ID
reuse fails. A duplicate session record already in the stream is corruption.
Unknown fields, impossible decreases, wrong predecessor/value or invalid reason
refuse replay with `campaign_state_corrupt`; invalid live transitions use
`campaign_transition_invalid`. An uncertain append poisons the session: no work
uses the requested ceiling until an exclusive durable reopen confirms its record.
If no valid record survived, the previous ceiling still applies.

Known measured plus estimated spend is counted once against the effective
ceiling; scheduling stops when that subtotal reaches or exceeds it. Unknown
amounts or remainders still cause `campaign_accounting_incomplete` when further
spending needs a provable remaining budget. This guard covers preparation,
completed and inconclusive seeds, outstanding attempts, and completed legacy
organisms. A completed legacy organism without cost evidence remains unknown;
a Boolean result is not a billing observation. A ceiling increase never resolves
unknown accounting, resets spend, reruns committed seeds or authorizes export.
Derived reports show the initial and effective ceilings and their session record
hashes; they cannot override the journal.

## Monetary encoding and version compatibility

Version `"3"` serializes every monetary value as a canonical nonnegative decimal
**JSON string**, or null where explicitly permitted. This includes
`initial_ceiling_usd`, `previous_ceiling_usd`, `ceiling_usd`, `amount_usd` and
version-3-derived monetary subtotals, totals and remaining capacity. Arithmetic
uses exact decimals; persistence never converts amounts through binary floating
point.

Reports derived from version `"3"` declare `journal_schema_version="3"` and use
this monetary encoding. Historical reports without that declaration retain
their original interpretation; copying a report cannot upgrade its source history.

The canonical grammar is `(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?`, within the
128-character numeric bound. Zero is `"0"`; canonical values include `"0.25"`,
`"5"` and `"12.34"`. No sign, leading integer zeros, exponent, whitespace or
trailing fractional zeros are allowed. Thus `"5.00"`, `"1e1"`, `"-0"`, JSON
number `5`, Booleans and nonfinite spellings reject on replay. Unknown amounts
are null, never `"0"`. An exhausted ceiling blocks dispatch; remaining capacity
is reported as `"0"` with any overspend reported separately.

API compatibility inputs such as finite floats are converted from their decimal
spelling once at the boundary, validated and canonicalized before hashing or
writing. A reader must not normalize noncanonical wire values into acceptance.
The string encoding participates in type-sensitive identities and record hashes.
It does not change numeric comparison for semantic JSON command responses.

This is an explicit revision of the earlier version `"2"` numeric-money design.
Version `"2"` monetary JSON numbers retain their original exact-decimal meaning
and original bytes/hashes; they are not reinterpreted as strings or version
`"3"` records. Versions cannot mix within a journal. The new dispatch and
reconciliation payloads below also require version `"3"`. No automatic migration,
version-label edit, missing-history backfill or in-place rehash is permitted.
Historical version `"2"` journals remain diagnostic evidence and cannot authorize
version `"3"` resume. A new experiment uses a new directory and identity.

## Journal envelope

Every strict UTF-8 JSONL object has exactly these fields. Objects including the
newline are at most 1 MiB. Read incrementally; never load an unbounded stream.

| Field | Contract |
|---|---|
| `schema_version` | String `"3"` |
| `sequence` | Nonnegative integer starting at 0, incrementing exactly once; Boolean excluded |
| `campaign_id` | Validated campaign digest |
| `kind` | One of the kinds below |
| `previous_hash` | Previous record digest; 64 zeros for sequence 0 |
| `payload` | Exact kind-specific object |
| `record_hash` | `journal-record` identity over the envelope excluding itself |

The chain detects drift within protected storage; hashes do not establish
independent ownership. Duplicate keys, foreign IDs, sequence gaps, bad hashes,
unknown fields/versions and invalid transitions refuse replay. A complete final
object without newline is valid.

Identical API retries return the existing record hash and append nothing.
Conflicting retries fail. An identical duplicate terminal already persisted in
the stream is corruption, not an idempotent retry.

## Record payloads and transitions

All listed fields are required. `nullable` explicitly permits null. Digests are
validated lowercase SHA-256 values. Attempt/observation/dispatch IDs are unique bounded
nonempty strings. Counts/indexes are nonnegative integers, never Booleans.

| Kind | Exact payload fields |
|---|---|
| `campaign_initialized` | `identity_manifest`, `configuration`, `organisms`, `stages` |
| `session_started` | `session_id`, nullable `previous_session_record_hash`, nullable `previous_ceiling_usd`, nullable `ceiling_usd`, `reason` |
| `seed_started` | `organism_id`, `seed_id`, `seed_index`, `attempt_id`, nullable `retry_of`, `input_identity`, `configuration_id` |
| `seed_completed` | `organism_id`, `seed_id`, `seed_index`, `attempt_id`, `start_record_hash`, `result` |
| `seed_inconclusive` | `organism_id`, `seed_id`, `seed_index`, `attempt_id`, `start_record_hash`, `reason`, nullable `observation_digest`, `cost_observation_ids`, `cost_coverage` |
| `dispatch_registered` | `dispatch_id`, `owner`, nullable `attempt_id`, `adapter_id`, `operation`, `operation_id`, nullable `retry_of` |
| `cost_observed` | `observation_id`, `dispatch_id`, `owner`, nullable `attempt_id`, `status`, nullable `amount_usd`, `coverage`, `source`, `observation_digest` |
| `dispatch_reconciled` | `dispatch_id`, `registration_record_hash`, nullable `previous_reconciliation_record_hash`, `cost_observation_ids`, `status`, `evidence_digest`, `reason` |
| `billing_reconciled` | `owner`, nullable `attempt_id`, `through_sequence`, `dispatch_record_hashes`, nullable `previous_reconciliation_record_hash`, `cost_observation_ids`, `cost_coverage`, `evidence_digest`, `reason` |
| `organism_started` | `organism_id`, `attempt_id`, nullable `retry_of`, `input_identity`, `configuration_id` |
| `organism_inconclusive` | `organism_id`, `attempt_id`, `start_record_hash`, `reason`, nullable `observation_digest`, `cost_observation_ids`, `cost_coverage` |
| `organism_completed` | `organism_id`, `durability`, `seed_record_hashes`, nullable `attempt_id`, nullable `start_record_hash`, `seeds`, `deploy_reachable`, `observation_digest`, `cost_observation_ids`, `cost_coverage` |
| `organism_skipped` | `organism_id`, `reason`, `characterization_reason` |
| `stage_decided` | `stage_index`, `organism_record_hashes`, `aggregate`, `decision` |
| `campaign_completed` | `stage_record_hashes`, `organism_record_hashes`, `stop_reason`, `unexecuted_organism_ids` |

Initialization is first and unique. `organisms` is the full ordered population;
each entry has `organism_id`, adapter-validated `candidate_identity` and ordered
`seeds`. Each seed has `seed_id`, `seed_index`, integer `seed_value`. `stages` is
the increasing schedule of organism boundaries, including the final requested
population. Configuration binds `durability` (`seed` or `organism`).

An attempt start is durably acknowledged before its candidate execution or
spend begins. Earlier paid preparation requires campaign-owned dispatch
registration under the current session instead of an invented seed attempt.
Each terminal references its matching start, with one terminal per attempt and
one measured completion per seed. A recovered outstanding start is first closed
as inconclusive with unknown possible spend. A retry gets a distinct attempt ID and explicitly names the prior inconclusive
attempt ID in `retry_of`; it never overwrites uncertain history. An omitted link
cannot hide prior attempts. Recovery closes the old start but does not itself
authorize a retry.

A measured seed `result` has exactly `diagnostic_status` (`passed` or `failed`),
`reason`, nullable `candidate_snapshot_id`, `observation_digest`, ordered unique
`cost_observation_ids`, and `cost_coverage` (`complete` or `unknown_remainder`).
Inconclusive work has no fabricated Boolean outcome. Cancellation propagates
after cleanup and recording; it is not a measured failed seed.

With seed durability, organism completion references every seed completion in
order and has null legacy attempt/start fields. With organism durability, those
references are empty, attempt/start are required and the full Boolean seed vector
is committed atomically. No fabricated seed-granularity records describe a legacy
runner's internal execution.

Eligibility skips precede any start and retain exact characterization alongside
normalized reason `source_missing`, `too_large`, `worktree_failed` or `not_valid`.
They cannot discard attempted or committed work. A systemic containment failure
stops the session instead of skipping the population.

The validator enforces declared member/seed order, matching references, complete
populations, no bypass of partial work and no execution after a committed stop.
Due stage decisions precede further execution or completion. `decision` is
`continue` or `stop` under the identity-bound reporting rule.

## Cost observations

Persist observed cost before a dependent terminal/decision. `owner` is `campaign`,
`seed_attempt` or `organism_attempt`; campaign preparation has null `attempt_id`.
Terminals reference already persisted observations owned by their attempt. The
same observation ID/content is a no-op; conflicting reuse fails.

Every observation references a previously committed `dispatch_registered` by
`dispatch_id` and must match its `owner`/`attempt_id`. Terminal references are a
snapshot of accounting at commit time; replay also includes later observations
for that owner, even after its terminal. Terminal records cannot hide late cost.

`status` is `measured`, `estimated` or `unknown`; `coverage` is `complete` or
`partial`. Known `amount_usd` is a canonical nonnegative decimal JSON string;
unknown amount is null. See [monetary encoding](#monetary-encoding-and-version-compatibility)
for API normalization, exact arithmetic and version compatibility. Measured zero needs an actual
observation or explicitly identified mock diagnostic. Absence is not zero.

### Production callback attribution

The tier-neutral observation sink in `core.lm_timing_callback` binds observed
calls to the owning durable attempt and records explicit call/attempt identities,
pricing provenance, scope and completeness for synchronous, asynchronous, failed
and retried calls. Callback redelivery deduplicates the same observation; an
actual retry is a distinct execution and can carry additional cost. A success
callback cannot erase a failed attempt's unknown remainder.

Hermes and SWE-bench attach this sink before production dispatch and flush
observations durably before a terminal result and on exceptional exit. They
never infer an attempt's cost by subtracting unrelated global ledger totals.
The callbacks cover the supported installed LiteLLM synchronous and asynchronous
interfaces, including custom LM implementations using `engine="litellm"`. Missing callback/pricing evidence remains
unknown, including after a larger ceiling is requested. Synthetic zero-cost observations are explicitly identified and cannot become
production billing evidence.

### Dispatch coverage and reconciliation

The following version `"3"` records are planned additions. The framework journal
owns validation and durable append; the production adapter owns registration,
callback attribution and evidence of billing completion. A callback supplies an
observation, not authority to declare coverage complete.

#### Registration and ownership

`dispatch_registered` is synchronized before entering any billable operation.
`owner` is `campaign`, `seed_attempt` or `organism_attempt`. Campaign preparation
uses null `attempt_id` after initialization/current-session commit, before any
seed start if necessary. Attempt ownership requires a matching durable start.
`adapter_id` identifies the verified adapter implementation; `operation_id`
identifies its nonsecret operation configuration. Both are SHA-256 identities.
`operation` is `preparation`, `inference` or `background`. Each actual retry gets
a new `dispatch_id`; nullable `retry_of` names a prior dispatch of the same owner
and operation. It does not authorize a retry or replace seed-attempt linkage.

The registration fixes ownership and its originating session permanently.
Observations delivered in a later session still reference that registration and
original owner. IDs cannot be reused for a new invocation; identical API retries
return the original registration, while duplicate persisted registrations or
conflicting reuse reject. Nested preparation calls and background work register
every independently billable dispatch; an outer operation must not count the
same charge again. Unsupported paths leave coverage unknown.

#### Per-dispatch reconciliation

`dispatch_reconciled.registration_record_hash` names the original registration.
`previous_reconciliation_record_hash` is null on first reconciliation, otherwise
the last reconciliation for that dispatch. `cost_observation_ids` lists all its
persisted observations in journal order, without duplicates. `evidence_digest`
binds retained nonsecret adapter/provider completion evidence; `reason` is a
bounded nonempty diagnostic string. `status` is:

| Status | Required evidence |
|---|---|
| `settled` | Final charge observations and an adapter-supported boundary proving no further charge or callback liability |
| `not_dispatched` | Independent evidence that execution never crossed the billable boundary; an empty callback queue is insufficient |
| `unknown_remainder` | Missing pricing, completion, possible late charge or unsupported billing path |

`not_dispatched` requires no charge observations. `settled` requires known
measured/estimated observations with complete coverage; zero needs an explicit
zero-cost observation. Registration starts unresolved. Reconciliation can leave
it unresolved or settle it with affirmative evidence. A later observation makes
earlier reconciliation stale until a new linked reconciliation includes it.
Evidence conflicts retain uncertainty and refuse finite-budget scheduling.
Append never rewrites old observations or claims that a timeout was free.

#### Owner coverage barrier

`billing_reconciled` records completeness for one owner/attempt, including the
campaign-owned preparation scope. `through_sequence` equals the immediately
preceding journal sequence at append. `dispatch_record_hashes` lists every registration for that
owner through that sequence in journal order; `cost_observation_ids` lists every
corresponding observation once. The nullable previous hash links the last billing
barrier for that owner. `evidence_digest` binds adapter reconciliation evidence;
`reason` is a bounded nonempty string. `cost_coverage` is `complete` or
`unknown_remainder`.

Complete coverage requires current `settled`/`not_dispatched` reconciliation for
every listed dispatch and affirmative adapter evidence that all billable paths
in this scope were registered and no background/late liability remains. The
validator checks references, ownership, order, cutoff and freshness; arbitrary
caller strings/digests cannot establish adapter provenance. An empty list proves
zero work only with explicit supported no-billable-work evidence. New dispatches
or observations invalidate the earlier barrier for scheduling until a new one
is committed. An attempt terminal can claim complete cost coverage only by
matching the latest complete barrier and its observation list. No barrier
changes the diagnostic outcome of an already committed terminal.

#### Crash recovery and late callbacks

The three new registration/reconciliation kinds use the same exclusive writer,
hash chain and fsync barriers as seed records. Registration failure or uncertain
acknowledgment prevents dispatch.
After a crash, a registered dispatch without current reconciliation represents
possible spend, even if no callback survived. Recovery queries supported retained
adapter/provider evidence by original dispatch identity; it never redispatches
that identity to discover whether it ran. Without conclusive evidence, append
`unknown_remainder` and block further finite-budget work. Paid preparation follows
the same rule even when no seed was ever started.

Late callbacks append `cost_observed` under their original registered ownership,
then new linked dispatch/owner reconciliation. Only the exclusive current writer
can append; an in-memory callback queue is not durable recovery evidence. If a
callback cannot be recovered and persisted, coverage stays unknown. Recovered
observations and reconciliation may append after an attempt terminal, stage stop
or campaign completion to correct accounting and regenerate reports. They cannot
reopen diagnostic outcomes, authorize new execution or erase a committed stop.
Replay counts all observations, not just terminal references. A hard budget is
rearmed only after replay and current complete reconciliation of prior liability.

Registration covers synchronous/asynchronous calls, custom LM paths, retries,
preparation and supported background work. A returned result or empty callback
queue does not prove coverage. Unsupported paths, missing terminal observations,
pricing failures and possible late charges retain `unknown_remainder`.

Persist amounts and unresolved liability before dependent work and on exceptional
exit. If persistence also fails, preserve the original execution exception or
cancellation and attach the accounting failure as secondary diagnostic context.

Hermes and SWE-bench use the same recovery boundary, including supplied progress
runners. Before new spend, replay all durable observations and count each ID
once. For a finite ceiling, derive:

```text
known_spend = measured_subtotal + estimated_subtotal
remaining_capacity = max(0, effective_total_ceiling - known_spend)
```

Do not dispatch when the ceiling is reached or prior liability is unresolved.
Otherwise, an adapter either initializes the ledger with `known_spend` under the total
ceiling or arms a fresh ledger with `remaining_capacity`; it never subtracts
history twice. Unknown amounts or residual liability block finite-budget
dispatch with `campaign_accounting_incomplete`, even when known spend is zero.
Legacy completed work remains unknown even if some attributed callbacks exist.
Uncapped operation retains uncertainty in reports rather than relabeling it zero.

Reconstruction counts each observation ID once across sessions, with separate
measured/estimated subtotals and explicit unknown counts/remainders. An attempt
can have a measured diagnostic result and unknown cost coverage. Uncertain
interrupted spend remains possible spend; a hard remaining budget cannot be
claimed from the known subtotal. Required spending stops with
`campaign_accounting_incomplete` until accounting is resolved.

## Seed and aggregate accounting

A fully measured organism has its full nonempty ordered Boolean seed vector:
true means diagnostic comparison passed; false means an established diagnostic
failure. Neither semantic refusal nor `CodeGateResult.deploy` determines it.
The compatibility rule is:

```text
deploy_reachable = (n_correct > 0) and (2 * n_correct >= requested_seeds)
```

One of two seeds qualifies; two of three qualify. Apply this only after every
requested seed is measured. The name records diagnostic repair reachability,
not permission to export code. Partial organisms have no reachability verdict.

Stage `aggregate` has exactly `requested_organisms`, `measured_organisms`,
`skipped_organisms`, `requested_seeds`, `measured_seeds`, `outstanding_seeds`,
`inconclusive_seeds`, `correct_organisms`, `wilson_lower`, `wilson_upper` and
`kill_line`. Recompute from referenced records under the bound reporting algorithm.
An inconclusive seed is still outstanding until measured; counts refer to distinct
outstanding seed IDs, while attempt history survives later completion. Partial
work and unexecuted population remain visible. Fully measured organisms enter
organism-level estimates once; pooled seed rates remain contrast-only.

Completion reasons are `population_complete`, `configured_limit_reached` or
`futility_stop`. Limit/futility completion lists all unexecuted organism IDs.
A due stage stop takes precedence; otherwise full population completion precedes
a simultaneously reached configured limit. Unexecuted members are not failed
repairs and never disappear from requested denominators. Cost exhaustion,
cancellation, infrastructure failure and unresolved attempts leave resumable
state, not a fabricated campaign completion.

## Interruption and durable recovery

| Interrupted boundary | Required resume behavior |
|---|---|
| Durable start, no terminal | Retain uncertain attempt and possible spend; close inconclusive before a distinguishable retry |
| Registered dispatch, no settled reconciliation | Recover original ownership and possible liability, including preparation; do not assume no execution or cost |
| Observation committed, reconciliation absent or stale | Count amount once, retain unknown remainder, reconstruct reconciliation from supported evidence before further finite-budget work |
| Late callback after terminal or completion | Append under original dispatch, refresh reconciliation and reports; preserve measured outcomes and committed stop |
| Complete terminal survives lost acknowledgment | Exclusive validated durable reopen, then reuse; no duplicate execution or charge |
| Seed committed, organism aggregate absent | Reuse committed seeds and reconstruct aggregate without calling adapter when population is complete |
| Organism committed, stage decision absent | Reconstruct and persist due decision before more work |
| Stage stop or configured limit reached | Reconstruct stop/completion and unexecuted population before scheduling |
| Derived report/queue replacement fails | Regenerate from authoritative journal |
| Append/fsync acknowledgment uncertain | Poison session; stop dependent work until exclusive validated reopen |

Reopen validates records/transitions and successfully synchronizes the complete
prefix before acknowledging durable reuse. It never assumes a failed fsync means
nothing survived.

Recover only a demonstrably extendable incomplete final JSON prefix. Preserve
exact discarded bytes in a private exclusive `campaign_progress.torn.<digest>.bin`
file and synchronize it before truncating to the valid prefix. Preservation
failure refuses truncation. Missing final newline alone is not corruption:
retain a complete valid record and synchronize its newline.

Complete malformed JSON, wrong-shaped objects, invalid UTF-8, duplicate keys,
extra documents, bad hashes/references, invalid terminals and interior corruption
refuse replay without silently skipping or renumbering records. No automatic
migration or speculative identity import rewrites historical progress. Hash-chain
validation detects inconsistent records, not rollback of a complete valid prefix;
rollback resistance requires a separately protected committed-head anchor.

## Adapter interfaces

| API | Contract |
|---|---|
| `CampaignJournal.open(root, *, identity)` | Exclusive closable journal with validated replay and durable reopen barrier |
| `CampaignJournal.start_session(*, session_id, ceiling_usd=None)` | Synchronizes the current process session and effective total ceiling; `None` inherits, never removes a cap |
| `CampaignJournal.inspect(root)` | Detached validated record list from pinned read-only storage; no repair, append, session or execution; concurrent drift refuses |
| `CampaignJournal.seed_progress(organism_id)` | Framework-owned organism progress |
| `SeedProgress.completed` | Detached read-only mapping of deep-copied committed results by seed index |
| `SeedProgress.outstanding` | Detached copies of starts lacking a terminal |
| `SeedProgress.latest_inconclusive(index)` | Latest inconclusive attempt ID for explicit retry linkage, or `None` |
| `SeedProgress.start(index, *, retry_of=None)` | Generates/durably commits a unique start, returns owned `SeedAttempt` |
| `SeedAttempt.attempt_id` | Registered attempt identity |
| `SeedAttempt.capture_costs()` | Context manager capturing attributed callback observations and persisting them before exit, including exceptional exit |
| `SeedAttempt.cost_references()` | Observation IDs already durably attributed to this attempt |
| `SeedAttempt.observe_cost(observation)` | Validates and durably persists cost once |
| `SeedAttempt.commit(result)` | Commits measured terminal before returning |
| `SeedProgress.commit(index, *, attempt_id, result)` | Compatibility wrapper requiring an existing start |
| `SeedProgress.record_attempt(index, *, attempt_id, reason, observation_digest=None)` | Emits `seed_inconclusive`, never a retrospective start |

`SeedAttempt` retains its existing public name. Journal, attempt and progress
owners are process-local and noncopyable. They confer no export
authority. Persistence failure returns no usable start. Foreign campaign or
organism contexts reject.

`CampaignJournal.inspect` pins existing storage, runs the same transition
validator as replay and returns detached records. It creates no directory,
lockfile, journal or session and performs no repair, tail archive, truncation,
newline normalization or synchronization. It detects descriptor/content drift
rather than taking writer ownership. A concurrent change refuses inspection;
retry once the writer is quiescent. Missing storage remains missing. Complete
malformed records and interior corruption refuse. Only an exclusive writer can
perform the recovery procedure above.

There is no progress-observer callback required from adapters. Monitor
reconstruction reads validated records after writer closure, including on
exceptional exit. A secondary inspection or reconstruction failure is retained
as diagnostic context and cannot replace the original exception or cancellation.

The monitor derives annotations only from validated records and final
read-only inspection after writer closure. Before publishing any annotations, validate the
complete ordered mapping of selected candidates to stored candidate identities
and reject duplicate queue identities. Zipping unchecked stored members with the
current queue is insufficient. Mismatches leave prior annotations intact.
Successful earlier organisms remain represented if a later one fails.

`run_campaign` explicitly selects `progress_runner(candidate, *, seed_progress)`
or legacy `organism_runner(candidate)`; supplying both rejects before work. It
never catches an internal `TypeError` to infer compatibility. Progress-aware
`run_organism(..., seed_progress=None)` and the SWE-bench runner
`(repo, candidate, *, seed_progress=None)` propagate owned progress. Standalone
`None` has no durable resume promise. SWE-bench supplies complete
`identity_configuration` before any seed dispatch. Hermes and SWE-bench flush
actual callback-ledger cost observations through attempt owners at durable
boundaries and on exceptional exits. Gate/worktree cleanup runs in `finally`;
missing cost coverage remains unknown. Systemic containment and persistence
failures propagate, preserving progress and the original cancellation.

Legacy runners use durable `organism_started`/`organism_inconclusive` and atomic
whole-organism completion. Reports label durability `organism`; partial internal
seeds are not recoverable. Fully committed organisms are reused without invoking
the runner. A legacy runner that starts and then becomes inconclusive retains
that attempt and propagates inconclusive control flow. It cannot append an
eligibility skip afterward; skip eligibility is established before any start. Progress-aware runners provide `seed` durability.

Monitor `attempt_candidates(..., progress_root=None)` and optional
`--progress-root` freeze the ordered selected queue identity when configured.
`None` preserves explicitly nonrecoverable operation. Queue annotations are
derived outputs. Harvesting and attempt wiring connects through lazy `evolution.composition.monitor_code` wrappers;
monitor domain modules import no concrete Tier-4 implementation. Propose-only
behavior and existing authorization requirements remain unchanged.

## Errors and historical records

| Stable prefix | Action |
|---|---|
| `campaign_writer_busy` | Preserve other writer; do not delete the lock |
| `campaign_storage_untrusted` | Refuse unsafe or candidate-accessible storage |
| `campaign_state_incompatible` | Preserve journal; correct unknown/different identities or use a new experiment directory |
| `campaign_state_corrupt` | Preserve exact stream; do not skip complete invalid records |
| `campaign_transition_invalid` | Reject live API operation without append/dispatch |
| `campaign_persistence_uncertain` | Stop and require exclusive validated durable reopen |
| `campaign_accounting_incomplete` | No further required spending under an unprovable hard remaining budget |

Version 1, version `"2"` and unversioned ledgers retain their historical
interpretation and remain diagnostic evidence for this planned contract. They
cannot authorize export or become version `"3"` progress by relabeling.
Unknown original identities are not inferred from current files/settings.
A version `"3"` record with incomplete or incompatible payloads also refuses
resume; matching version labels cannot supply absent starts, sessions,
dispatch registrations, reconciliation, costs or identities. There is no
speculative import or silent migration. See
[wire compatibility](#monetary-encoding-and-version-compatibility).
Preserve original bytes separately
when starting a new identified experiment.

Containment remains required by default. Explicit `--allow-unconfined` is labeled
diagnostic and never supplies semantic/export authority. Diagnostic abstention,
core-to-tier and validation composition boundaries, DSPy `>=3.4.1,<3.5` and
explicit LiteLLM engine selection remain unchanged.

Production Hermes campaigns accept `resolved_production_identity` (CLI:
`--production-identity-file`) as an expected declaration. It contains `provider`,
`model`, `model_revision`, `runtime_id`, `harness_id`, `dataset_id` and nullable
`image_id`. IDs are SHA-256 identities; an omitted or unresolved required value
refuses. `validate_production_identity` validates declaration shape and copies
it; it does not establish authority over actual execution. The planned production
adapter must independently resolve and compare dispatched material before
initialization and every dispatch. The planned SWE-bench integration must also
verify image content, platform and harness/build inputs. These checks remain
implementation blockers; see [resolved identity checks](#resolved-identity-checks).
