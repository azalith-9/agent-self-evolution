---
title: Resume a code-repair campaign
description: Recover committed seeds, uncertain attempts, cumulative costs, and campaign decisions
doc_type: howto
implementation_status: planned; production resume guarantees incomplete
maintenance: Update with campaign CLI, journal, or recovery behavior
---

# Resume a code-repair campaign

**[PLANNED — Implementation Pending]** These steps specify the intended
production recovery procedure. Scoped recovery exists, but complete billing
coverage, paid-preparation reconciliation, SWE-bench residual-ledger integration
and actual immutable execution identity verification remain unresolved. Unknown
production coverage blocks subsequent finite-budget dispatch. Host provisioning
cannot finish these integrations. See [current blockers](../campaign_recovery.md).

The target journal is version `"3"`; its canonical decimal strings and durable
dispatch/reconciliation records are not implemented by the existing version
`"2"` writer. Preserve historical journals unchanged; the procedure is not a
migration command. Read-only inspection and CLI help do not demonstrate
production resume conformance.

Under the intended contract, resume from the protected journal using the same ordered population and immutable
configuration. Every writing process establishes a durable session before
spending; committed seeds are reused. See the
[recovery contract](../campaign_recovery.md).

Use an already installed project environment; `uv run --no-sync` does not
install dependencies. When the prepared virtualenv is active outside this
worktree, use `uv run --active --no-sync` to select it explicitly.

Use the same output directory and result-affecting configuration to continue an
interrupted campaign. The validated journal determines completed work; a report's presence
or a historical deployment flag does not. See the
[campaign state reference](../campaign_recovery.md) for identities and record fields.

## Inspect progress without executing repairs

Preserve `campaign_progress.jsonl`, `campaign_progress.lock`, any torn-tail
archives and session receipts. Do not edit rows, delete a lock file, concatenate
ledgers or replace completed records with report data.

Inspect the latest derived report using only the standard library:

```bash
python -m json.tool output/code_campaign/recovery/campaign_report.json
```

This command prints formatted JSON and exits 0 for a valid report. It does not
validate journal integrity or prove that the report reflects the latest commit.
If that output directory has not been used, the command reports a missing file;
choose the original campaign's directory.

Compare requested, measured, outstanding and inconclusive counts. A partial
organism remains outstanding even if its completed seeds already exceed half.
An inconclusive attempt is eligible for a fresh measurement; a committed failed
seed is a completed measurement and is reused.

## Resume with matching inputs

Repeat the original `python -m evolution.code.campaign` invocation, preserving
`--repo`, `--output-dir`, seed count, stage schedule and result-affecting settings.
Resume is automatic for a compatible versioned journal; there is no flag that
ignores identity mismatches. The default requires containment. Resume may invoke
a paid proposer for outstanding seeds, so use it only within the authorized run's
budget. Replay restores durable measured and estimated observations before
arming the residual dispatch ledger. Unknown amounts or residual coverage block
finite-budget dispatch, including when using a supplied production progress runner.

Omit `--max-cost-usd` to inherit
the last committed total campaign ceiling, or supply a strictly larger finite
total. The increase becomes effective only after a durable `session_started`
audit. It is not an additional per-session allowance and does not rerun completed
seeds. A decrease or removal of a finite cap requires a new campaign. An initially
null ceiling stays null; other identity-bound limits cannot change in place. See the
[budget and replay rules](../campaign_recovery.md#budget-ceilings-and-session-audits).

The current command inventory can be read without a repair or provider call:

```bash
uv run --no-sync python -m evolution.code.campaign --help
```

Expected output begins with `Usage:` and exits 0. A new campaign creates
`campaign_initialized`; an existing one acquires the exclusive writer lock,
validates the planned version `"3"` journal and identities, passes durable reopen barriers
and reconstructs pending aggregates before executing more seeds.

Use `CampaignJournal.inspect(root)` for journal validation without executing
repairs. It returns detached validated records through pinned read-only storage,
without initialization, repair, newline normalization or session append. Inspect
a quiescent journal; concurrent descriptor/content drift refuses the read.
Missing storage remains missing. Only an exclusive writer performs recovery;
a writable resume can dispatch work and is not a read-only substitute.

If another writer holds the lock, stop this invocation and let the owner finish.
An abandoned process releases its OS lock automatically; a retained lock file
needs no deletion. A storage or synchronization error stops dependent work.
Reopen through the campaign command after correcting the storage problem so the
reader can determine whether an unacknowledged completion survived.

## Verify production identity before resuming

Keep the expected production identity declaration with the authorized campaign
configuration. Hermes uses `--production-identity-file`; Python integrations use
`resolved_production_identity`. A declaration alone cannot authorize dispatch.
The adapter compares actual provider/model revision, runtime, harness, ordered
dataset and applicable image/platform with retained verified material. It
executes that material rather than re-resolving a mutable alias or image tag.
See [identity fields and verification](../campaign_recovery.md#resolved-identity-checks).

If a required identity cannot be resolved immutably, preserve the journal and
stop. An unsupported provider revision or mismatched runtime is a dispatch
blocker, not a reason to rerun completed seeds or edit initialization records.

## Handle damaged or incompatible state

A demonstrably incomplete final JSON record is archived and truncated under the
writer lock. A complete valid record without a final newline is preserved.
Interior corruption, malformed completed records, changed identities and
unsupported versions refuse resume without discarding completed progress.
Keep the exact journal and diagnostic error for review; use a new output directory
for an intentionally changed experiment.

Version 1 and unversioned ledgers remain historical diagnostics. There is no
automatic migration or speculative identity import. Preserve them and use a new
output directory for a new experiment; current configuration cannot establish
missing historical runtime, source, test or provider identities.

## Preserve attempts and costs

A durable `seed_started` precedes every dispatched seed. If it has no terminal,
resume preserves it as an inconclusive interrupted attempt with unknown possible
spend. A retry explicitly supplies the old inconclusive attempt ID as `retry_of` and
receives a new identity. Closing the interrupted start does not automatically
authorize retry. Execution can have
occurred before a result was committed; do not delete the start or declare that
attempt free. Reuse committed failed results as well as passed ones.

Accounting persists each attributed cost observation once and reconstructs it
across resumes. Reconciliation establishes coverage for every billable dispatch,
including retries, preparation and late callbacks. Measured zero requires an
actual observation; it differs from an unknown amount or unknown remainder. Inspect measured/estimated subtotals, unknown
attempts and unknown remainders before relying on a hard remaining budget.
`campaign_accounting_incomplete` stops further spending when the remaining
budget cannot be established. This includes completed legacy organisms without
cost evidence, not just interrupted seeds. Raising a ceiling cannot erase
uncertain prior spend. Reopening a writer also requires a new current-process
session; a previous process's committed session does not authorize dispatch.

## Recover monitor attempts

Set `--progress-root` to the same protected root when repeating a monitor attempt.
The configured progress path uses the campaign journal and reconstructs annotations
from final read-only inspection after writer closure, including exceptional exit.
Before any annotation changes, it validates the entire ordered candidate mapping,
selected queue payloads and unique queue identities. A mismatch leaves prior
annotations intact. A secondary reconstruction error preserves the original
exception or cancellation; already committed successes remain in progress.
Inspection performs no journal repair or session modification. Changed candidate
ordering or result-affecting configuration requires a new experiment. Without
`progress_root`, attempts have no durable recovery promise. Scan-only operation
and propose-only behavior are unchanged.
Legacy injected runners have `organism` durability: only a full committed
organism is reused, not its internal partial seeds. Once a legacy runner starts,
an inconclusive outcome remains an attempt; it cannot become an eligibility skip. Progress-aware code and
SWE-bench runners use `seed` durability.

## Confirm recovery before relying on aggregates

The resumed report must include each committed seed exactly once and retain
its recorded diagnostic result and cost. It must regenerate a missing organism
aggregate or stage decision before advancing. A committed futility stop remains
a stop. A configured organism limit retains the full requested population and
lists unexecuted members; it does not turn them into failures or shrink the
denominator. Due stage decisions and limit/completion state reconstruct before
any new dispatch. Compatibility ledgers and reports can be regenerated from committed
records; none authorizes code export. Code export separately requires the
[protected verifier](../protected_verification.md).
