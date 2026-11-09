---
title: Operating the triage sentinel
description: Scan, attempt, budget scheduling, and optional durable recovery
doc_type: howto
maintenance: Update with monitor, cost accounting, or recovery behavior
---

# Operating the triage sentinel

The sentinel is the **supply side** of the code-evolution loop: it scans a target
repo's recent git stream for bugs the validated repair loop *could* fix, ranks
them, and writes a triage queue. It is **propose-only** — it never evolves code or
opens a PR. A human reads the queue and decides what, if anything, to attempt.

The repair loop (`evolution.code.campaign`) is the **consumer**. The sentinel finds
work; you choose when to spend on it.

## Two steps, one of which costs money

| Step | Command | Cost | Who triggers |
|------|---------|------|--------------|
| **Scan** (rank candidates → queue) | `python -m evolution.monitor --repo <repo>` | **$0** (pure git, no LLM) | safe to schedule |
| **Attempt** (run the repair loop on the top K) | `… --attempt-top K --max-cost-usd <cap>` | **spends** (LLM calls) | manual, gated, cost-capped |

The scan never spends. The attempt is the only step that calls an LLM, so it stays
a deliberate, capped, human-triggered action — **never scheduled** (see below).

## Scanning

On demand:

```bash
python -m evolution.monitor --repo /path/to/target-repo --since-days 90
```

Or via the wrapper (writes a timestamped dir plus a stable `latest` pointer):

```bash
scripts/monitor_scan.sh /path/to/target-repo
# SENTINEL_SINCE_DAYS=30 scripts/monitor_scan.sh /path/to/target-repo
```

Each run writes to `output/monitor/<timestamp>/`:
- `triage_queue.json` — machine-readable, jq-aggregable.
- `triage_report.md` — the human-readable ranked table + the ready-to-run attempt command.

## Reading the queue

Each candidate row carries:

| field | meaning |
|-------|---------|
| `rank` | position after sorting (see ranking below) |
| `kind` | `dependency_regression` or `bug_fix` |
| `tool` / `test` | the tool source and the test file that pins its behavior |
| `fix_sha` / `parent_sha` | the upstream fix commit and its buggy parent (the oracle handle) |
| `committed_at` | committer date of the fix (also the recency sort key) |
| `score` | ranking weight (`dependency_regression` = 2.0, `bug_fix` = 1.0) |

**Ranking** is git-only and intentionally cheap: dependency-regressions first, then
most recent. Difficulty and value are *not* estimated here — that needs a worktree —
so a high rank means "look at this first," not "this will repair."

### Honest caveat on `dependency_regression`

This label is **noisy**. It fires when the fix commit also touched a dependency
manifest (`pyproject.toml`, `uv.lock`, `requirements.txt`, …) — not when a dependency
version was actually bumped and broke a tool. A supply analysis over a year of one
active repo found **zero** clean, tool-local dependency-version regressions: the
manifest-touching commits were broad migrations (dozens of files) that don't
reproduce as a single-tool repair, or feature additions. So treat a
`dependency_regression` tag as "this commit happened to touch a manifest," and judge
the candidate on its actual diff — do not assume it is a genuine version regression.

## Attempting the top candidates (the spend)

When you decide a few candidates are worth the spend:

```bash
python -m evolution.monitor --repo /path/to/target-repo \
    --attempt-top 3 --max-cost-usd 5.0
```

This reuses the validated repair loop (worktree → repair → oracle gate) on the top K
and annotates each queue row with an `attempt` block. It still **never opens a PR** —
it records whether the loop *could* produce an oracle-matching fix for review.
A diagnostic success does not authorize deployment or export.

Oracle `correct`/`incorrect` are diagnostic comparison verdicts. Campaign and
sentinel seeds consume diagnostic comparison outcomes rather than `gate.deploy`.
Independent verification and snapshot integrity are separate deployment
requirements; see the [verification evidence boundary](protected_verification.md#evidence-boundary).

Verdicts in the annotated `triage_queue.json`:

| `attempt.status` | meaning |
|------------------|---------|
| `attempted` (+ `correct_seeds`/`seeds`, `deploy_reachable`) | all requested seeds were measured; `correct_seeds` counts diagnostic comparison passes; `deploy_reachable` requires at least one pass and `2 * correct_seeds >= seeds` (two of three by default) |
| `not_valid` | the parent doesn't cleanly fail what the fix passes — not a clean single-tool bug |
| `source_missing` / `too_large` / `worktree_failed` | skipped before repair (source gone, too big for a whole-file rewrite, or isolation setup failed) |
| `run_inconclusive` | required diagnostic observations were incomplete (for example a hang, collection failure, or unknown cleanup); retain seed identity, reason and completed observations for resumption rather than declaring a failed repair |
| `cost_ceiling` | the cost callback stopped further work; already in-flight calls can still incur cost |

Independent verification can refuse deployment with
`independent_test_verification_unavailable` even when every diagnostic comparison
passes. Preserve those successful seeds and the organism's diagnostic denominator;
missing independent proof alone is neither `incorrect` nor `run_inconclusive`.
A demonstrated diagnostic failure remains a failed seed. If diagnostic measurement
itself is unavailable, do not coerce it to false or report a partial set as a
completed attempt. Report requested, measured, and inconclusive counts separately
and, under the complete recovery contract, resume only outstanding seeds with
fresh invocation identities. Reusing queue observations restores accounting
only, never deployment authority. See the
[canonical comparison and campaign contract](reference/deployment-evidence.md#diagnostic-comparison-and-campaign-accounting)
and [artifact fields](data_models.md#campaign_ledgerjsonl--campaign_reportjson).

`--max-cost-usd` is **required** whenever `--attempt-top > 0` (the CLI refuses to run
the repair loop uncapped). It guards further scheduling using observed LLM cost;
in-flight calls may overshoot it. It is not a provider billing cap. The scan
itself needs no cap.

Durable progress is optional: set `--progress-root` to use campaign seed commits
and reuse the same root and ordered queue on a compatible retry. Without it,
queue annotations do not provide durable per-seed recovery. Monitor reconstruction
uses pinned read-only `CampaignJournal.inspect` after writer closure, including
exceptional exits. It validates the complete ordered candidate identity and every
selected queue row before annotation, rejecting duplicate queue keys. Inspection
performs no initialization, repair or session append. A reconstruction failure
preserves the original execution exception or cancellation. See the
[resume guide](howto/resume-code-campaign.md#recover-monitor-attempts).

**Production recovery [PLANNED — Implementation Pending].** Complete billing
coverage, paid-preparation reconciliation, SWE-bench residual-ledger integration
and actual immutable identity checks remain unresolved. Scoped recovery and
callback attribution do not establish these guarantees. The planned version
`"3"` records and monetary encoding are not implemented by the version `"2"`
writer. See [recovery blockers](campaign_recovery.md).

The intended [campaign recovery contract](campaign_recovery.md) applies the total ceiling
to measured and estimated cost across all sessions. Attributed callbacks alone
cannot establish complete billing coverage; dispatch reconciliation retains
unknown liability. A durable current-process session and restored residual
ledger precede further spending. Interrupted work and completed legacy organisms
without complete cost evidence remain unknown even when some callbacks exist;
`campaign_accounting_incomplete` blocks finite-budget dispatch. A larger ceiling
cannot turn unknown cost into zero. Progress records and queue annotations carry
no export authority.

## Scheduling the scan (opt-in, macOS launchd)

The scan is $0, so a periodic refresh is safe. This is **opt-in** — nothing is
installed for you.

1. Copy the template and fill in the two placeholders:

   ```bash
   sed -e "s#__REPO_ROOT__#$(pwd)#g" \
       -e "s#__TARGET_REPO__#/path/to/target-repo#g" \
       scripts/com.agent-self-evolution.sentinel-scan.plist.template \
       > ~/Library/LaunchAgents/com.agent-self-evolution.sentinel-scan.plist
   ```

2. Enable / disable:

   ```bash
   launchctl load   ~/Library/LaunchAgents/com.agent-self-evolution.sentinel-scan.plist   # enable
   launchctl unload ~/Library/LaunchAgents/com.agent-self-evolution.sentinel-scan.plist   # disable
   ```

The template runs weekly (Mondays 09:00) and logs to `output/monitor/sentinel-scan.log`.

**Never put `--attempt-top` in the scheduled job.** A schedule must only scan; the
spend step stays manual. The wrapper and template are written to enforce this, and a
copy-paste that adds `--attempt-top` would turn a free job into unsupervised spend.

**Cron alternative** (any Unix): `0 9 * * 1 /path/to/repo/scripts/monitor_scan.sh /path/to/target-repo`

### Retention

Each scan writes a new `output/monitor/<timestamp>/` and never deletes old ones, so
the audit trail is preserved. Prune periodically to keep the directory bounded — e.g.
keep the most recent 12:

```bash
ls -dt output/monitor/2* | tail -n +13 | xargs rm -rf
```

## What the sentinel never does

- It never edits the target repo, evolves code, or opens a PR.
- It never spends on a schedule — only `--attempt-top`, run by you, spends.
- It never decides a deploy — it surfaces candidates and verdicts; the human deploys.
