---
title: Run repairs with contained execution
description: Prepare a contained repair runtime and interpret configuration and refusal outcomes
doc_type: howto
maintenance: Update with repair CLI or containment configuration changes
---

# Run repairs with contained execution

Use this guide when preparing a repair environment or investigating a containment
refusal. Repair, campaign, monitor attempts, import checks, setup, and benchmarks
are intended to share the [execution contract](../reference/execution-contracts.md).

**[PLANNED - Implementation Pending]** The preparation and acceptance steps below
describe the target configuration. They do not certify the recovered runtime.
Its `prepare_environment` still inherits parent `PATH`; trusted runtime selection
and several deployment-evidence checks remain required. Cooperative pytest runs
are diagnostic-only under this contract, even if the recovered gate emits
`decision="deploy"`. Deployment is blocked until an independent verifier and its
gate integration exist. There is no flag that enables that verifier. Consult the
[implementation boundary](../reference/execution-contracts.md#implementation-boundary)
before using a repair result.

## Contents

- [Prepare the runtime separately](#prepare-the-runtime-separately)
- [Select roots and credentials](#select-roots-and-credentials)
- [Use the repair containment controls](#use-the-repair-containment-controls)
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
It builds an environment for each execution rather than copying the shell's
environment. Do not supply a custom `PYTHONPATH` or `PYTEST_ADDOPTS` as an isolation
workaround. Required paths and pytest configuration belong to trusted harness
preparation.

Provider credentials belong to trusted proposer inference. Repository setup,
imports, tests, and benchmarks receive none. A separately authorized validation
agent receives only its selected provider credential and network policy; the
post-agent test command receives neither credential nor network access.

For an authorized agent run, select the provider and authentication mode in the
trusted parent. Only supported configuration data and the chosen credential enter
the private home. Do not copy a complete Hermes or Claude configuration directory:
it can contain executable extensions and unrelated credentials. Unsupported modes
refuse preparation rather than inheriting the developer's configuration.

## Use the repair containment controls

| Existing control | Behavior |
|---|---|
| `--require-sandbox` | Default in the recovered CLI; the planned contract requires capability refusal before repository code runs. This flag alone does not establish deployment eligibility |
| `--allow-unconfined` | Requests reduced protection; diagnostic-only under the planned contract. The recovered gate must not be relied on to enforce deployment blocking |
| `--base-python` | Selects the prepared interpreter; does not grant access to its owner's home or ambient configuration |
| `--benchmark-cmd` | Runs under the repair policy with private paths and bounded cleanup; cannot escape containment through a shell |
| `--benchmark-timeout-seconds` | Bounds benchmark runtime; cleanup has a separate finite deadline |
| `--no-create-pr` | Keeps the result local; publication is not required to inspect a repair |

The table's containment and lifecycle guarantees are requirements pending full
implementation and verification. The base documentation checkout and recovered
CLI can differ; use the selected runtime's `--help` for its option defaults.

Monitor attempts must enforce the same required capabilities as direct repairs.
Queue scanning is propose-only and does not execute a repair. Capability failure
is recorded as an operational refusal, not silently converted into a successful
attempt or a harmless per-candidate skip.

The CLI option inventory is available without running a proposer or an agent:

```bash
uv run --no-sync python -m evolution.code.evolve_code --help
```

The command prints usage and repair options, then exits. It requires an already
installed project environment; it does not download dependencies. A repair run
itself can invoke a paid proposer and needs separate authorization.

## Inspect the result before relying on it

Read `gate_decision.json` and `repair_trace.json` in the chosen output directory.
Legacy schemas do not contain all required authority evidence. An emitted
`deploy` or `TestRun.authoritative=true` cannot replace the missing checks.
Confirm that the evaluated source and test scope match the intended baseline.
Check containment capabilities, execution completion, cleanup, structured test
evidence, and checked Git scope results before interpreting a comparison verdict.
An absent field in an older artifact means unknown protection or completion.

| Observation | Action |
|---|---|
| Sandbox unavailable or a capability probe fails | Correct the host prerequisites or move to a capable host; keep the run non-authoritative |
| Offline setup lacks a build dependency | Retrieve the approved prerequisite separately, then restart preparation |
| Requested host restrictions cannot be enforced | Supply an enforceable network mechanism or retain refusal |
| Exit 1 without complete failure identities | Treat evidence as incomplete; do not subtract an empty failure set |
| Collection error, interruption, timeout, or no required tests | Fix the execution problem and rerun the complete evaluation |
| Child exited zero but cleanup is unknown | Reject deployment evidence and investigate descendants |
| A complete pytest session ran a different selection | Reject evidence; restore the parent-owned required test scope |
| Test records can be forged in the candidate interpreter | Keep diagnostics; refuse deployment until independent verification exists |
| Capture exceeded its size limit | Treat execution as incomplete; inspect redacted overflow diagnostics |
| macOS launch succeeded without certified descendant cleanup | Keep deployment blocked; successful launch is not cleanup evidence |
| Offline probe passed but a provider needs restricted networking | Require separate evidence for that policy or retain refusal |
| Git status or diff failed | Restore reliable inspection; an empty output is not proof of clean scope |
| All validation tasks abstained | Interpret as a diagnostic result only; prompt deployment remains blocked |

Keep raw subprocess capture private. Share only redacted diagnostics and the
necessary source diff. Do not attach credential stores, runtime locks, or snapshot
contents to a review.

The future supported eligible path is a contained tool worker evaluated through
bounded data requests by a separate trusted verifier, as specified in
[independent verification](../reference/execution-contracts.md#independent-verification-and-eligible-execution).
Running pytest again or reviewing its JSON manually does not enable that path.

For local handoff without publication, follow
[review and deliver a local remediation](review-local-remediation.md). For suite
authoring, follow the [offline fixture tutorial](../tutorials/validate-task-fixtures.md).
