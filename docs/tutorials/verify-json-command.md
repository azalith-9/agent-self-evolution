---
title: Verify a JSON command and inspect native evidence
description: Exercise a JSON protocol and inspect protected acceptance, rejection, export, and replay evidence
doc_type: tutorial
implementation_status: planned; native accepting demonstrations blocked
maintenance: Update with native evidence CLI or JSON command contract changes
---

# Verify a JSON command and inspect native evidence

**[PLANNED — Implementation Pending]** The protocol-only exercise below is
independent of protected verification. Production accepting/export demonstrations
remain blocked: protected setup and retained-byte prerequisite replay still
refuse. Effective aggregate scratch limits and continuous runtime/path protection
also remain unresolved. Host provisioning alone cannot complete this tutorial's
protected demonstrations. See [verification blockers](../protected_verification.md).
The target outcomes below are requirements, not demonstrated current behavior.

This exercise uses a single Python file that adds two integers. It makes no
provider calls, runs no agent and publishes nothing. The
[semantic reference](../protected_verification.md) defines its trust and coverage
limits; the exercise checks two requests rather than proving arbitrary addition
programs correct.

The exercise checks the protocol. After implementation blockers are resolved,
the remaining steps will run production probes and demonstrations on a supported
provisioned host. Missing protected setup, prerequisites or
effective controls refuses the relevant execution. A refusal does not establish
acceptance. Keep implementation conformance separate from native host evidence;
see the [evidence boundary](../protected_verification.md#evidence-boundary).

## Prepare the host

Use a Linux host with a trusted provisioned standard-library runtime, usable
Bubblewrap isolation, enforced process/thread creation denial, bounded address
space/CPU/scratch and owned-scope cleanup. The semantic policy requires
`processes=1`; per-process limits alone cannot demonstrate that policy.
Have the administrator provision `python-stdlib` in the protected registry
`/etc/agent-self-evolution/verification-runtimes.json`. That registry identifies
the interpreter, approved runtime roots and their manifest. Do not generate it
from an untrusted repository or use a repair virtualenv as implicit authority.

Install the framework environment beforehand. `uv run --no-sync` uses that
existing environment; no package download is part of this exercise. If the
prepared virtualenv is active outside the worktree, use `uv run --active
--no-sync` in the launch script instead. A missing
registry or unavailable capability is reported as unavailable evidence. These host prerequisites are separate from the demonstration checks. A macOS host cannot
substitute mocked or historical evidence for this Linux exercise.

## Understand the command protocol

The demonstration's candidate has this behavior:

```python
import json
import sys

left, right = json.load(sys.stdin)
json.dump({"sum": left + right}, sys.stdout)
sys.stdout.write("\n")
```

For input `[2,3]` followed by newline, it emits `{"sum": 5}` and exits 0.
For input `[-2,3]` followed by newline, it emits `{"sum": 1}` and exits 0.
The semantic cases encode those exact requests as `WzIsM10K` and `Wy0yLDNdCg==`.
Only the parent knows the expected responses; the child sees its current request.

You can check the protocol itself using the installed standard-library runtime:

```bash
printf '[2,3]\n' | python -I -S -c 'import json,sys; a,b=json.load(sys.stdin); print(json.dumps({"sum":a+b}))'
printf '[-2,3]\n' | python -I -S -c 'import json,sys; a,b=json.load(sys.stdin); print(json.dumps({"sum":a+b}))'
```

Expected output, in order:

```text
{"sum": 5}
{"sum": 1}
```

This shell exercise illustrates the protocol only. It supplies no containment,
protected observations or export authority.

## Collect native evidence

The native evidence tool runs credential-free probes and retains an entry for
every named capability, including checks that cannot execute. `--demo` runs
known-good acceptance, wrong-response rejection, exact-byte/mode export and
replay rejection through production APIs. Use a fresh private output directory. Run the probe detached because
resource checks can exceed 30 seconds. This invocation uses a private tmux socket on every
tmux command and writes a log and synchronized numeric exit receipt. When a
workflow has a usage guardian, register the socket/session before the launch
line using its existing controls; see [job registration](../howto/review-local-remediation.md#respect-the-usage-guardian).

```bash
probe_dir=$(mktemp -d "$PWD/output-verifier-demo.XXXXXX")
chmod 700 "$probe_dir"
probe_socket_dir=$(mktemp -d /tmp/ase-verifier-demo.XXXXXX)
export ASE_PROBE_DIR="$probe_dir"
cat > "$probe_dir/run.sh" <<'SH'
#!/bin/sh
umask 077
uv run --no-sync python -m evolution.code.native_evidence \
  --verification-runtime-config /etc/agent-self-evolution/verification-runtimes.json \
  --runtime-id python-stdlib \
  --output-dir "$ASE_PROBE_DIR" --demo > "$ASE_PROBE_DIR/run.log" 2>&1
probe_status=$?
python - "$probe_status" "$ASE_PROBE_DIR" <<'PYTHON' || exit 3
import os
import sys
from pathlib import Path

root = Path(sys.argv[2])
with (root / "run.log").open("rb") as log:
    os.fsync(log.fileno())
with (root / "exit.status").open("x") as receipt:
    receipt.write(sys.argv[1] + "\n")
    receipt.flush()
    os.fsync(receipt.fileno())
directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PYTHON
exit "$probe_status"
SH
chmod 700 "$probe_dir/run.sh"
env -u TMUX tmux -S "$probe_socket_dir/tmux.sock" new-session -d -s ase-verifier-demo \
  -e "ASE_PROBE_DIR=$probe_dir" -c "$PWD" /bin/sh "$probe_dir/run.sh"
printf 'Evidence directory: %s\n' "$probe_dir"
```

Launch prints the evidence directory and returns immediately. Inspect the
`exit.status` file when available and read `run.log`; do not treat a running pane
as successful evidence. The detached process is a local probe, not an AI worker.

For an invocation that reaches evidence persistence, inspect the actual output:

```bash
cat "$probe_dir/exit.status"
python -m json.tool "$probe_dir/native_evidence.json"
```

The persisted output has `schema_version="2"` and `demo_requested=true`.
Exit `0` requires every required control and requested demonstration enforced.
Exit `1` records an observed failure, including when capability gaps also exist;
exit `2` records required capability/refusal gaps without observed failure.
An unlaunched entry has a null child exit, never an inferred zero. Inspect each
entry's category, status, command and receipt references; generic cleanup does
not establish semantic enforcement. `collector_exit_code` records the collector
outcome, while `exit.status` records the actual process exit separately.

The wrapper's `exit.status` records process completion, not acceptance or export.
Wrapper exit `3` means receipt synchronization failed; a missing receipt is never
success. An unexpected error can prevent evidence persistence. Preserve each
unavailable capability by name. Distinguish a missing host prerequisite from a
missing implementation guarantee; host provisioning alone cannot establish a
production accepting path. Do not bypass
a capability with unconfined operation or modify host security policy to make this exercise pass.

## Inspect acceptance and export receipts

The demonstration creates reviewed credential-free fixtures, a baseline, a
version `"2"` semantic specification and an approved local destination. The
specification includes `scratch_inodes` alongside the aggregate scratch byte
limit. Protected setup approval and complete retained-byte prerequisite replay
precede assessment. No provider, agent or package installer is invoked.

Once the implementation conforms, the required outcome on a supported host is:
the known-good candidate is accepted, the wrong sum is
rejected, the accepted snapshot is exported with exact bytes/mode and a second
claim is refused. Required negative controls exercise interference and transport.
Semantic process-creation denial and generic detached-descendant cleanup have
separate evidence.

Successful outputs are `native_evidence.json` version `"2"` with
all required guarantees enforced, and `export_receipt.json` version `"2"` with
`status="succeeded"`, `phase="complete"` and `replacement="replaced_durable"`.
Fixture/command identities, hashes and receipt references must make the execution
reviewable. The required exit codes are `0` for complete enforced evidence,
`1` for failed requirements/controls and `2` for required capability/refusal gaps.
Check the individual receipt references and exact fixture hashes before calling
the exercise complete. Missing, refused or unavailable demonstrations keep it
incomplete even when protocol checks pass. This tutorial records no native run
result and cannot establish evidence for an unavailable macOS host.

## Use the verifier with a repair

A repair adds `--semantic-spec`, `--verification-runtime-config` and `--runtime-id`
to its existing gate inputs. `--export-to` binds an approved existing local destination
root during context preparation; the authorized target retains its repository-relative path beneath it.
See the [CLI options](../interfaces.md#protected-code-verification-options).
Repair proposer calls are separate from this credential-free exercise.

Diagnostics, scope, surface, regression/oracle and configured benchmarks bind to
the retained read-only snapshot before the final semantic check. Export uses
that snapshot. All execution and cleanup finish before acceptance. Assessment
without a bound export root issues no authority; any subsequent candidate
dispatch revokes previously issued authority before it begins.
An audit copied from this demo, a previous accepted summary or an exported file
cannot authorize a different repair. A new context needs new verification.

Keep private receipts for the independent security and architecture review.
Share redacted evidence and checksums, excluding requests, expected responses,
credentials or runtime storage. Local export does not create a PR or deployment.

Generic Linux descendant probes are recorded separately under `generic_cleanup`.
They use credential-free synthetic children and the generic process supervisor;
they do not establish protected semantic verification. `collector_exit_code` is
numeric even when protected child exits are null. Cancellation and macOS require
their own completed observations; Linux receipts cannot certify macOS behavior.
