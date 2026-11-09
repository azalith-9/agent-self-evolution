---
title: Run repairs with contained execution
description: Prepare a contained repair runtime and interpret configuration and refusal outcomes
doc_type: howto
maintenance: Update with repair CLI or containment configuration changes
---

# Run repairs with contained execution

Use this guide when preparing a repair environment or investigating a containment
refusal. Repair, campaign, monitor attempts, import checks, setup, and benchmarks
share the [execution contract](../reference/execution-contracts.md).

## Contents

- [Prepare the runtime separately](#prepare-the-runtime-separately)
- [Select roots and credentials](#select-roots-and-credentials)
- [Use the repair containment controls](#use-the-repair-containment-controls)
- [Configure protected semantic verification](#configure-protected-semantic-verification)
- [Inspect the result before relying on it](#inspect-the-result-before-relying-on-it)

## Prepare the runtime separately

Provision the selected Python runtime and the target repository's build and test
dependencies before candidate execution. Dependency downloads are a separate
operation with explicit network authorization. Keep retrieved packages in an
approved cache; repository builds use those prerequisites offline.

On Linux, install Bubblewrap through the operating system's package management.
Its presence does not establish usable namespaces or the required capabilities.
On macOS, the adapter requires OS containment for the full process tree. If the
host cannot enforce required reads, writes, networking, or cleanup, use a host
that can. Do not treat a write-only sandbox as confidential-read isolation.

See [runtime dependencies](../dependencies.md#execution-containment-backends)
for backend responsibilities. No package version alone establishes containment.

## Select roots and credentials

Choose the target Git repository and the Python interpreter containing its
prepared dependencies. Repair source, visible tests, held-out tests, and floor
paths are relative to that repository. They cannot traverse outside it through
`..`, an absolute path, or a symlink.

The harness creates private home, cache, temporary, output, and capture paths.
Certified source, tests, configuration, runtime and evidence remain protected;
writable scratch is separate. A runtime requiring writes to protected inputs
needs a supported scratch arrangement or preparation refuses it.

It builds an environment for each execution rather than copying the shell's
environment. Do not supply a custom `PYTHONPATH` or `PYTEST_ADDOPTS` as an isolation
workaround. Required paths and pytest configuration belong to trusted harness
preparation.

Provider credentials belong to trusted proposer inference. Repository setup,
imports, tests, and benchmarks receive none. A separately authorized validation
agent receives only its explicitly selected supported credential arrangement and
network policy; the post-agent test command receives neither credential nor network access.

Select the provider through the existing model/configuration resolver before
building the child environment. Supported environment-only Hermes credentials
are forwarded deliberately for that provider. Multi-field arrangements require
the adapter's complete explicit mapping; supported no-auth providers receive no
credentials. An unsupported arrangement refuses rather than reading arbitrary
host auth stores or forwarding all available keys. See
[environment configuration](../reference/execution-contracts.md#environment-configuration).
The selected executable is resolved once, and its identity supplies both the
launch path and runtime read roots.

## Use the repair containment controls

| Existing control | Behavior |
|---|---|
| `--require-sandbox` | Default for contained repair execution; refuses unavailable required capabilities before repository code runs |
| `--allow-unconfined` | Explicit diagnostic operation only; records reduced protection and can never authorize deployment |
| `--base-python` | Selects the prepared interpreter; does not grant access to its owner's home or ambient configuration |
| `--benchmark-cmd` | Runs under the repair policy with private paths and bounded cleanup; cannot escape containment through a shell |
| `--benchmark-timeout-seconds` | Bounds benchmark runtime; cleanup has a separate finite deadline |
| `--no-create-pr` | Keeps the result local; publication is not required to inspect a repair |

Monitor attempts enforce the same required capabilities as direct repairs.
Queue scanning is propose-only and does not execute a repair. Capability failure
is recorded as an operational refusal, not silently converted into a successful
attempt or a harmless per-candidate skip.

The CLI option inventory is available without running a proposer or an agent:

```bash
uv run --no-sync python -m evolution.code.evolve_code --help
```

Expected output begins with `Usage:` and lists repair options; exit status is 0.
The command requires an already installed project environment; it does not
download dependencies. For a prepared active virtualenv outside the worktree,
use `uv run --active --no-sync`. A repair run itself can invoke a paid proposer
and needs separate authorization.

## Configure protected semantic verification

**[PLANNED — Implementation Pending]** The accepting/export steps in this
section describe the intended interface. Protected setup and retained-byte
prerequisite replay currently refuse. Provisioning a host or selecting these
options cannot resolve the implementation gaps; see
[verification blockers](../protected_verification.md).

For the planned single-file Python JSON command path, supply all three options:
`--semantic-spec`, `--verification-runtime-config` and `--runtime-id`. Keep the
reviewed specification and runtime registry outside candidate control. The
[semantic reference](../protected_verification.md) defines their exact schemas;
the [credential-free tutorial](../tutorials/verify-json-command.md) exercises the
protocol and production acceptance, rejection, export and replay checks. A repair interpreter selected with
`--base-python` is not implicitly a trusted semantic runtime.

Add `--export-to` only when a local approved existing destination root is
prepared; it binds that root during `VerificationContext.prepare`. Assessment
without a bound root can pass but cannot issue export authority. The
export retains the authorized target's relative path and uses protected captured
bytes and mode. `--no-create-pr` keeps operation local; unsupported publication
requests fail
before preparation, candidate execution or spend. No semantic
configuration leaves diagnostics usable and export refused. Partial semantic
configuration fails validation rather than falling back to an implicit runtime.

Campaign execution also requires containment by default. Resume reuses committed
seeds through its [progress journal](../campaign_recovery.md); a historical
organism ledger alone does not establish per-seed recovery.

## Inspect the result before relying on it

Diagnostic artifacts remain inspectable but cannot authorize export. The CLI
holds the
live gate result open through export and closes it on every exit; see
[ownership and disposal](../protected_verification.md#gate-to-export-ownership).

Read `gate_decision.json` and `repair_trace.json` in the chosen output directory.
Confirm that the evaluated source and test scope match the intended baseline.
Inspect `deployment_verification` as well as containment capabilities,
supervisor completion, cleanup, required-test identities, and checked Git scope.
An accepted verification must bind the same bytes and modes used by surface
checks, tests, and export. Applicable benchmarks and every selected execution prerequisite replay against
retained read-only bytes before sealing. An unsupported protected evaluator
leaves the assessment unverifiable; diagnostic mappings cannot replace replay.
Every later candidate dispatch revokes authority before execution and requires
fresh assessment. Export consumes the stored accepted snapshot and verifies the
destination.
An absent field in an older artifact means unknown protection or completion.

| Observation | Action |
|---|---|
| `independent_test_verification_unavailable` | Keep diagnostic repair/comparison results; deployment is refused because cooperative pytest records cannot prove semantics independently |
| Required tests skipped, deselected, replaced, missing or unexecuted | Restore the independently reviewed required checks; a green exit cannot substitute |
| Stale, malformed, replayed or unbound supervisor receipt | Retain redacted diagnostics and rerun with protected supervisor evidence |
| Payload or mode changed after tests, including during a benchmark | Invalidate acceptance and evaluate a fresh protected snapshot |
| Sandbox unavailable or a capability probe fails | Correct the host prerequisites or move to a capable host; keep the run non-authoritative |
| Offline setup lacks a build dependency | Retrieve the approved prerequisite separately, then restart preparation |
| Requested host restrictions cannot be enforced | Supply an enforceable network mechanism or retain refusal |
| Exit 1 without complete failure identities | Treat evidence as incomplete; do not subtract an empty failure set |
| Collection error, interruption, timeout, or no required tests | Fix the execution problem and rerun the complete evaluation |
| Child exited zero but cleanup is unknown | Reject deployment evidence and investigate descendants |
| Git status or diff failed | Restore reliable inspection; an empty output is not proof of clean scope |
| All validation tasks abstained | Interpret as a diagnostic result only; prompt deployment remains blocked |

Both code gates use the same verifier. No flag upgrades cooperative records or
unconfined diagnostics into independent proof. A refused deployment can coexist
with a diagnostically fixed repair; it does not certify the supported deployment
flow. See [verification outcomes](../reference/deployment-evidence.md#verification-schema-1).
Native capability skips in mock-only checks do not certify Linux or macOS
containment. Uncertified macOS descendant cleanup remains a refusal.

Keep raw subprocess capture private. Share only redacted diagnostics and the
necessary source diff. Do not attach credential stores, runtime locks, or snapshot
contents to a review.

For local handoff without publication, follow
[review and deliver a local remediation](review-local-remediation.md). For suite
authoring, follow the [offline fixture tutorial](../tutorials/validate-task-fixtures.md).
