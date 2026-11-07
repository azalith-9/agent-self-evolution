---
title: Review and deliver a local remediation
description: Preserve recovered work and deliver a verifiable local integration package
doc_type: howto
maintenance: Update with recovery, evidence, or package contract changes
---

# Review and deliver a local remediation

Use this procedure to resume recovered implementation and deliver a local package
without publication. It preserves unrelated checkout state and records unresolved
behavior explicitly. A package's presence does not establish successful remediation.

## Contents

- [Preserve recovered state](#preserve-recovered-state)
- [Verify and account for findings](#verify-and-account-for-findings)
- [Retain review and validation evidence](#retain-review-and-validation-evidence)
- [Build the integration package](#build-the-integration-package)
- [Verify the package independently](#verify-the-package-independently)
- [Apply to a destination safely](#apply-to-a-destination-safely)
- [Report the handoff](#report-the-handoff)

## Preserve recovered state

Read `AGENTS.md`, the working-copy `CHECKPOINT.md`, `.review/findings.md`,
`.review/tdd_handoff.md`, and `.review/tdd_test_manifest.json`. If a file comes
from the shared checkout, record that origin. Confirm the surviving implementation
worktree, its branch, exact baseline, permissions, and current staged, unstaged,
and untracked files. Earlier inventories and test counts require confirmation.
A tests-first red run does not describe validation of later implementation.

Continue in the surviving implementation worktree. Do not create a replacement,
relocate the implementation, or copy it into a workflow worktree. If permissions
exclude it, record the access blocker and stop dependent implementation changes.
Documentation specifications can be prepared separately without changing source.

Before mutation, snapshot both implementation and shared-checkout indexes,
including split-index dependencies, staged and unstaged binary diffs, file modes,
NUL-delimited inventories, and worktree registrations. Keep private snapshots
outside the package. Verify recovery archive checksums without applying historical
patches again. Retain archives, manifests, locks, PIDs, backups, and runtime files.

Preserve the shared checkout's staged `.gitignore` change and any unrelated edits.
Do not stage the entire checkout, reset unrelated work, or alter a historical dirty
worktree. Select paths explicitly for any authorized commit; hooks and signing
remain enabled. Shared-checkout integration requires authorization and writable
access; the local package remains required whether or not integration occurs.

Where tracking is authorized, inspect the existing issue's scope before reusing
it. Record its URL and reuse outcome. Do not create a duplicate or interpret
tracking permission as permission to publish.

## Verify and account for findings

Investigate each claim against current source and behavior before changing it.
Distinguish confirmed defects, documentation discrepancies, unsupported claims,
and environmental limitations. Preserve compatible behavior and avoid refactors,
dependency bounds, or relocations without a demonstrated need.

In `.review/remediation_report.md`, account for exactly the integers 1–50, each
once, using these primary dispositions:

| Disposition | Required evidence |
|---|---|
| `fixed` | Concrete correction and observed behavioral verification |
| `already addressed` | Current source/history and applicable regression evidence |
| `invalid` | Reproduction or contract evidence contradicting the claim |
| `deferred` | Confirmed unresolved behavior and a concrete blocker |

Retain mixed subclaims and amendments beneath their parent. Any unresolved confirmed
subclaim makes that parent's disposition `deferred`; record completed corrections
separately. Test-file presence alone is not evidence of a fix.

Verify licensing and attribution from authoritative upstream provenance and
repository history. Preserve the README's MIT attribution chain without inventing
legal authorship. A LICENSE file alone does not establish provenance. Refresh the
privacy inventory of intended source, datasets, reports, and package material;
historical clean-scan claims are not fresh evidence.

## Retain review and validation evidence

Obtain independent security and architecture/API reviews within the active workflow.
Retain scope, conclusions, disagreements, resulting corrections, and unresolved
objections in `.review/security_review.md` and `.review/architecture_api_review.md`.
Reviewers receive the complete requirements, including diagnostic abstention
compatibility, evidence forgery, selection integrity, platform refusals, and the
supported acceptance path. Consult current primary documentation for backend,
dependency, or CI changes and retain the supporting references.

Validate in this order:

1. Establish test hermeticity with synthetic developer configuration and credential
   canaries, without reading real secrets or globally replacing `Path.home()`.
   Audit provider and agent mocks and confirm the interpreter/dependency environment.
2. Run focused security and behavioral regressions, including successful eligible
   evaluations as well as rejection paths.
3. Run credential-free native subprocess probes for the actual claimed policies.
   Record platform, backend, commands, results, skips, and unavailable checks.
4. Run the full mock-only suite without the historical home override.
5. Run Ruff, lock consistency, installed dependency consistency, applicable
   pre-commit checks, and whitespace checks. Inspect autofixes and rerun affected
   validation when the reviewed payload changes.

Deployment-eligible validation is a planned requirement, not an available result
of the recovered pytest path. Until the
[independent verifier and gate integration](../reference/execution-contracts.md#independent-verification-and-eligible-execution)
exist, record that blocker and keep cooperative test results diagnostic. Source
review, package byte comparison, and successful mock tests do not establish an
eligible execution path. Local package handoff remains possible with the limitation
stated explicitly.

Run work expected to exceed 30 seconds detached, with durable logs and exit-status
artifacts. Every manual tmux command specifies a private socket, including status
and cleanup commands. Keep the user's tmux server untouched and do not foreground-sleep.

Record revision and payload identity, exact commands, versions, relevant non-secret
settings, exit codes, and exact passed, failed, skipped, error, and deselected
counts in `.review/validation_manifest.json`. Include skip reasons and durable log
paths. Label historical results. Mocks establish policy behavior; native probes
establish only the capabilities they exercise. A successful offline probe does
not certify provider-network restrictions, socket isolation, or macOS cleanup.
Unavailable native validation remains a limitation, not inferred success.

## Build the integration package

Finalize the remediation report and update `CHECKPOINT.md` before constructing the
patch. Retain historical safety context and backup references. Record remaining
behavioral defects separately from unavailable validation.

Use an explicit allowlist of intended paths. Include all intended source, tests,
and documentation, including new and ignored files. Exclude credentials, private
snapshots, runtime debris, recovery archives, and delivery artifacts. Use an isolated
temporary index to build a binary-capable diff against the exact baseline; leave
the real index untouched. An ordinary working-tree diff omits untracked additions.

The local handoff contains:

| Path | Content |
|---|---|
| `.review/remediation_report.md` | All primary dispositions, subclaims, blockers, and evidence |
| `.review/validation_manifest.json` | Reproducible validation metadata and durable evidence locations |
| `.review/security_review.md` | Independent security review and unresolved objections |
| `.review/architecture_api_review.md` | Independent architecture/API review and resolutions |
| `CHECKPOINT.md` | Recovery context, remaining work, safety boundaries, and handoff identity |
| `.review/delivery/integration.patch` | Complete intended binary-capable payload diff |
| `.review/delivery/file_manifest.json` | Exact baseline and each path's change type, mode, and content hash; deletions identify absence |
| `.review/delivery/APPLY.md` | Preservation, checksum, baseline, path review, and application instructions |
| `.review/package_application_verification.json` | Independent application and resulting byte/mode comparison |
| `.review/delivery/SHA256SUMS` | External checksums of finalized delivery artifacts and verification record |

Keep delivery files and the application-verification record outside the patch's
payload. They refer to the finalized patch and must not introduce self-inclusion
or checksum cycles. `SHA256SUMS` does not hash itself. Record its final checksum in
the handoff message if needed. The package may include reviewed `.review/` reports
without including every ignored `.review/` file.

## Verify the package independently

Materialize the exact baseline in a disposable directory, not another implementation
worktree. Inspect patch paths, modes, additions, and deletions against the allowlist
and manifest. Verify checksums, run `git apply --check`, and apply without fallback
merging. Compare resulting bytes and modes against every intended payload entry,
including new files and removals. Record baseline, patch checksum, commands, exit
codes, and comparison results durably in the application-verification record.

Finalize external checksums only after that record is written. A patch application
check alone does not prove that the patch contains every intended file, and byte
comparison alone does not establish behavioral correctness.

## Apply to a destination safely

The delivered `APPLY.md` supplies the exact baseline and artifact locations and
instructs the recipient to:

1. Preserve the destination's index, staged/unstaged changes, modes, and untracked
   files before mutation. Never reset or discard destination edits to make a patch fit.
2. Verify the patch and manifest checksums against the handoff before use.
3. Confirm the destination baseline matches the recorded commit exactly. If it
   differs, stop automatic application and review integration separately.
4. Review all changed paths and modes against the manifest and identify overlap
   with destination changes, including untracked additions.
5. Run `git apply --check` in the destination before applying. Stop on conflicts,
   existing additions, or partial application; do not force or blindly reapply.
6. Apply once only after the preservation and review checks pass. Verify resulting
   bytes/modes and run the relevant validation before relying on the changes.

**Never reapply the package to the surviving implementation worktree.** Its files
already contain the implementation. Historical recovery patches likewise remain
backups, not instructions to replay changes.

## Report the handoff

State absolute artifact locations, baseline, branch/worktree identity, commit and
index status, whether the shared checkout contains changes, fresh verification
counts, native limitations, consensus conclusions, and every outstanding defect or
blocker. Do not claim completion because files exist or because a package applies.

Operational evidence belongs in `.review/` and the checkpoint, not `docs/`. A local
handoff authorizes no push, PR, merge, deployment, paid provider call, live-agent
validation, unrelated message, or tooling upgrade. For execution refusals, see
[contained repair operation](run-contained-repairs.md).
