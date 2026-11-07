---
title: Review and deliver a local remediation
description: Preserve checkout state and hand off evidence-backed remediation without publication
doc_type: howto
maintenance: Update with repository safety and local integration requirements
---

# Review and deliver a local remediation

Use this procedure to hand off remediation from an isolated worktree while
preserving unrelated work in a shared checkout. It produces a local reviewable
deliverable. Publication and live provider validation require their own
authorization.

## Contents

- [Preserve both checkout states](#preserve-both-checkout-states)
- [Respect the usage guardian](#respect-the-usage-guardian)
- [Reuse tracking without duplicates](#reuse-tracking-without-duplicates)
- [Maintain one disposition per finding](#maintain-one-disposition-per-finding)
- [Record verification and review](#record-verification-and-review)
- [Make the deliverable accessible](#make-the-deliverable-accessible)

## Preserve both checkout states

Read the working-copy `CHECKPOINT.md`, `AGENTS.md`, and `.review/findings.md`.
Verify the branch, HEAD, worktree registrations, permissions, and active workflow.
Use a reversible write probe inside the designated implementation before spending
on design or review. Each delegated worker checks its own effective access.
A permission failure halts that step with the exact path and error; another
checkout is not a substitute implementation.

When a file exists only in the shared checkout, record that origin rather than
claiming it is present in the isolated checkout.

Before modifying either index, store private snapshots outside the deliverable:
the actual index and split-index dependencies, staged and unstaged binary diffs,
NUL-delimited status/index listings, untracked inventory, and worktree registrations.
Record both checkout identities and the snapshot location. Snapshots can contain
private data and are not review attachments.

Reuse the designated existing branch and worktree when supplied. Do not switch
shared main, create an alias checkout, or replace recovered implementation with
a documentation-only worktree. Treat other worktrees' reports, logs and review
records as provenance-bearing inputs. Compare recovered tests by identity,
checksum and overlap; install only reviewed missing files. Missing originals
remain unresolved recovery inputs, never reconstructed originals.

Make source changes only within the authorized implementation step. Select staging
paths explicitly. Never stage the entire checkout, commit the entire preexisting
index, reset unrelated changes, or disable hooks or signing.

When authorized to unstage runtime/checkpoint additions, select only verified
additions in the shared index and preserve every file on disk. Merge precise
ignore rules with existing edits. Retain locks, PIDs, checkpoints, patch backups,
and historical dirty worktrees. Checkpoint patches are history, not instructions
to reapply changes.

## Respect the usage guardian

Read the configured control directory's current `guard-state.json` before each
stage and long check. When the allowance reserves 15%, stop launching work at
85% used. A guardian pause or lost telemetry also stops new launches; retain
precise remaining steps and durable evidence. A historical usage snapshot does
not authorize another stage. Preserve the guardian's configuration and evidence.

Before launching any detached test, append its registration to
`registered_jobs.json`, preserving existing entries. Each object contains
`socket` (an absolute private `/tmp/ase-*` path) and `session` (an `ase-*` name).
Registration precedes launch so the guardian can stop every owned job. All manual
tmux operations use that private `-S` socket, including inspection and cleanup;
never operate on an ambient user server.

Checks expected to exceed 30 seconds run detached with durable logs and numeric
exit receipts under `.review/` or checkpoints. Do not foreground-sleep or keep
the only evidence in temporary storage. If monitoring pauses first, checkpoint
an incomplete handoff rather than claiming completion.

## Reuse tracking without duplicates

Where issue creation is authorized, verify Issues availability and search both
open and closed issues. Inspect likely matches for scope before reusing one.
Create a tracking issue only when no suitable match exists. After an ambiguous
creation response, repeat lookup before retrying. Record the issue URL and
whether it was reused or created.

Tracking authorization does not grant permission to push, open a PR, deploy, or
send unrelated messages. Continue the active workflow without starting another
recipe.

## Maintain one disposition per finding

Keep durable accounting in `.review/remediation_report.md`. For a review numbered
1–50, include exactly one primary disposition for every number:

| Disposition | Required evidence |
|---|---|
| Fixed | Concrete source changes and observed behavioral verification |
| Already addressed | Current source/history and applicable regression evidence |
| Invalid | Reproduction or contract evidence contradicting the claim |
| Deferred | Concrete blocker and the confirmed behavior still unresolved |

Within each entry, retain all material subclaims and amendments, including mixed
outcomes. A fixed subclaim does not erase a deferred confirmed defect. Cite paths,
commands, history, or primary documentation. Historical test counts and previous
privacy claims are context, not current verification. Audit privacy across text
and binary report contents and distinguish new observations from old inventory
claims. Inventory all remaining import-boundary violations individually; removing
one cycle does not establish that the package layering is clean.

Investigate compatibility and maintenance claims individually. Preserve the exact
README MIT attribution chain; derive any license text and package attribution
from repository history independently of newly staged metadata, without inventing
copyright provenance. Preserve exactly:

MIT — © 2026 [azalith-9](https://github.com/azalith-9) / [jramos](https://github.com/jramos) / [Nous Research](https://github.com/NousResearch)

Dependency bounds need compatibility evidence. Native CI additions need backend evidence; local
checks cannot establish a hosted run's success. Cosmetic relocation or broad
orchestration splitting is not required merely to account for a finding.

## Record verification and review

Use mock-only provider and agent tests. Hermetic configuration discovery replaces
the historical global `Path.home()` override. Simulate developer configuration
with synthetic files and credential canaries rather than reading real secrets.

Run focused checks before a fresh full mock-only suite from the actual
implementation cwd. Use the prepared environment without dependency upgrades.
Required command surfaces are `uv run --no-sync pytest tests/ -q`,
`uv run --no-sync ruff check evolution tests`, `uv lock --check --offline`,
`uv pip check`, a `git diff --check` against the recorded baseline, and
`uv run --no-sync pre-commit run --all-files`. Supply the exact recorded commit
as the whitespace check's revision argument, not an inferred branch tip. Review
any hook-generated changes before accepting results; never bypass hooks or signing to obtain a pass.

Record focused checks, the full suite, lint, whitespace, and required hooks with
exact commands, logs, exit-status artifacts, and observed pass/fail/skip counts.
Validate lock/config consistency where changed. Mark unavailable native checks as
unavailable. Runs overlap; do not sum historical counts or combine different cwd
runs into a passing full-suite result. Record source identity, cwd, exact failed
IDs and skip reasons with each run. Do not label a capability enforced because
its mock passed. Obsolete mocks change only with an explicit current-contract
explanation; preserve adversarial assertions and strict non-inferiority boundary
semantics.

Long checks run detached with private logs and status files. Every manual tmux
command specifies its private socket. Keep the user's tmux server and unrelated
processes untouched; do not use foreground sleeps.

Obtain consensus review for security, architecture, and public API changes within
the active workflow. Record reviewers' scope, evidence, concerns, and resolutions
or concrete blockers. Review containment, descendant cleanup, authentication
concurrency, completion evidence, and the deliberate-forgery threat boundary.

## Make the deliverable accessible

Always provide a reviewed local integration patch with its checksum, changed-path
manifest including file hashes and modes, baseline, and non-destructive
application instructions in
`.review/integration_instructions.md`, regardless of shared-checkout availability.
Include reviewed additions explicitly when constructing the patch; an ordinary
working-tree diff omits untracked files.

When authorized and writable, also put reviewed changes in the shared checkout
while preserving unrelated work. Shared-checkout updates do not replace the
patch, checksum, manifest, baseline, or application instructions.

Exclude unrelated dirt, runtime stores and credentials. Keep unresolved defects
and independent security/architecture review evidence alongside the package.
Review documentation-only changes as specifications; they do not close source
findings or establish passing implementation checks.

Identify the artifact with an absolute local path. State whether the shared
checkout contains the changes. Instructions must account for existing edits and
conflicts; never instruct blind application of historical checkpoint patches.
Provide checksum verification and `git apply --check` instructions before any
application. An already-modified checkout needs overlap review; do not overwrite
it or blindly reapply the patch. Verify against an isolated baseline copy without
changing the designated branch or worktree. Verify the patch before
describing it as reviewed integration evidence.

Update the working-copy checkpoint while retaining historical safety context and
backup references. Record the baseline, branch/worktree, tracking outcome, source
paths, unresolved findings, verification and review evidence, artifact location,
and commit status. If shared writes are unavailable, keep the merged checkpoint
and ignore changes in the deliverable and state that limitation explicitly.

The report and checkpoint contain operational evidence and stay outside `docs/`.
They must not claim complete remediation while confirmed defects remain deferred,
or claim success for checks that were not run. See
[contained execution](run-contained-repairs.md) for interpreting refusals.
