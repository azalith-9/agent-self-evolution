---
title: Protected semantic verification
description: Semantic checks, protected runtime configuration, ownership, and exact-byte export
doc_type: reference
implementation_status: planned; accepting path blocked
contract_version: "2"
maintenance: Update with verification, runtime, export, or evidence contract changes
---

# Protected semantic verification

**[PLANNED — Implementation Pending]** This reference defines the intended
semantic verification and local export contract. Requirements below describe
the feature to build; they are not guarantees supplied by the current code.

Protected setup still refuses with `verification_containment_unavailable`;
independently observed setup, invocation-bound lease issuance and aggregate
scratch inode enforcement are unfinished. Retained-byte prerequisite replay
also refuses with `verification_prerequisites_unavailable`. Runtime/path
protection across every candidate-capable phase remains unresolved. These are
implementation blockers: provisioning a host or runtime cannot resolve them.
There is no established production protected acceptance/export path.

Native enforcement is established by invocation-specific protected observations;
a configuration file, audit record or successful mock does not supply them.
Missing trusted evidence refuses execution or yields an unverifiable assessment.

The planned Tier-4 adapter targets `python-json-command-v1`: a
single Python source file reads one request from standard input and writes one JSON response.
A protected parent compares the response with reviewed expectations. Acceptance establishes
conformance to those cases and the applicable code gates. It does not establish
universal correctness or resistance to hardcoded responses for known inputs.

For a credential-free exercise, see the [verification tutorial](tutorials/verify-json-command.md).
For existing pytest diagnostics and supervisor fields, see
[deployment evidence](reference/deployment-evidence.md).

## Contents

- [Evidence boundary](#evidence-boundary)
- [Supported artifacts and trust boundary](#supported-artifacts-and-trust-boundary)
- [Semantic specification](#semantic-specification)
- [Strict JSON and identities](#strict-json-and-identities)
- [Trusted runtime configuration](#trusted-runtime-configuration)
- [Execution policy and completion](#execution-policy-and-completion)
- [Python integration](#python-integration)
- [Authorization and export](#authorization-and-export)
- [Gate-to-export ownership](#gate-to-export-ownership)
- [Errors and persisted evidence](#errors-and-persisted-evidence)
- [Native evidence](#native-evidence)

## Evidence boundary

The [partial findings synthesis](../.review/implementation-20261109/FINDINGS.md)
preserves surviving review evidence and unresolved obligations. It is not final
approval or a completed validation report; see the
[findings location amendment](index.md#findings-artifact-location).

The intended public API will accept a supported command only after independently protected
setup, complete prerequisite replay and semantic observations satisfy this
contract. Missing evidence yields refusal. Installing the framework or finding
Bubblewrap does not provision a trustworthy runtime.

Native validation is a separate property. It needs completed production-API
receipts for known-good acceptance, wrong-response rejection, exact-byte/mode
export, replay rejection and each required control. A mock acceptance tests
decision logic; a refusal tests refusal; patch application tests reproducibility.
None establishes native enforcement. A host without a provisioned runtime
cannot supply positive acceptance/export evidence. Linux receipts cannot certify
macOS behavior. Record actual host outcomes in private review receipts rather
than treating this reference as a validation result.

## Supported artifacts and trust boundary

The artifact is one regular, single-link UTF-8 `.py` file with an
ordinary permission mode. It runs directly as a script, with no package installation, repository imports,
plugins, build hooks, site initialization, or candidate-supplied dependencies.
Only the independently provisioned standard-library runtime is available.
Multi-file packages, arbitrary pytest suites, network services and commands
requiring credentials have no supported semantic authorization path.

The candidate, repository dependencies, hooks, tests, test plugins, generated
files and candidate-produced evidence are untrusted. The trusted computing base
is the host kernel, containment backend, independently provisioned interpreter
and libraries, framework parent and supervisor, protected storage, and the
reviewer who supplies the semantic specification. A compromised host, malicious
oracle author or privileged concurrent administrator is outside this boundary.
Effective protection must exclude candidate modification and substitution
throughout setup, diagnostics, benchmarks and verification. An owner UID, matching
hash or read-only mount alone cannot establish independent runtime ownership.

Expectations, verifier implementation, runtime configuration, snapshot backing
storage, campaign journals, supervisor transport and authorization state are
outside candidate-accessible mounts. Only the captured candidate file, approved
runtime, current request and private scratch are exposed. The parent never
imports candidate code, evaluates candidate assertions or interprets stdout as
a certificate. A printed receipt or `{"status":"accepted"}` is ordinary output.

Protection covers process access as well as paths: candidate code cannot inspect
parent memory, trace trusted processes, read their descriptors through a process
filesystem, or inherit authority/control handles. Attempts to replace runtime or
expectation paths, inject imports, forge receipts, replay invocation identities,
or write and restore source are within the malicious-candidate threat model.
Privilege escalation against a compromised administrator or kernel is outside it.

### Protected paths and runtime inventory

Protection is checked for the full ancestry of every authority-bearing path,
including the runtime registry, specification, interpreter, backend, bootstrap,
runtime roots and supervisor storage. Ownership, ordinary permission bits and
effective ACLs must exclude candidate writes and ancestor substitution. Unknown
ACL semantics refuse protection. A nonsymlink pathname or matching UID does not
establish this boundary.

Inventory opens entries relative to retained directory descriptors and captures
bytes and metadata through the same descriptor. Replacement, type/link/mode
changes, unexpected entries or incoherent reads invalidate preparation or
freshness. Protection remains effective between inventory and execution; a
before/after hash cannot detect every write-and-restore attack. The interpreter,
loader, libraries, bootstrap and backend all participate in execution identity.
Execution uses the retained objects or their independently protected roots,
without resolving an ambient alternative.

Protected-path exclusions apply during installation, build hooks, imports,
diagnostics, benchmarks, semantic execution and cleanup. Candidate-accessible
mounts exclude expectations, runtime configuration, journals, authorization
storage, supervisor channels, credentials and export destinations. Runtime
content exposed read-only to the candidate grants no access to administrative
runtime storage or the parent authority controlling it.

Capture starts only after all prior candidate execution scopes have terminated
and been reaped. Descriptor-relative access beneath pinned roots rejects
absolute paths, empty/dot/parent components, NULs, symlinks in any component,
nonregular files and special permission bits. Inspection cannot block on a FIFO
or open a device. Scope, surface freeze and retain-floor checks consume the
captured bytes, target and mode used for semantic execution and export.

## Semantic specification

Version `"2"` is required. Legacy specifications without `scratch_inodes` refuse.
The launcher verifies effective aggregate scratch byte, inode and metadata bounds
before entry; parsing requested limits alone cannot establish enforcement.

The specification is a strict JSON object in protected storage. All fields below
are required, no additional fields are accepted, and versions are strings.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Exactly `"2"` |
| `kind` | string | Exactly `"python-json-command-v1"` |
| `baseline` | object | Exact baseline identity described below |
| `runtime_id` | string | Key in the trusted runtime registry |
| `required_case_ids` | array of strings | Nonempty, ordered, unique complete case population |
| `cases` | array of objects | Exactly one case per required ID, in the same order |
| `limits` | object | All execution and transport limits below |

`baseline` contains exactly `repository_id`, `commit`, `target` and
`source_sha256`. `repository_id` is a reviewed local repository identity,
independent of a credential-bearing remote URL. `commit` is the full resolved
Git commit ID (40 or 64 lowercase hex digits); `target` is the canonical
repository-relative `.py` path;
`source_sha256` is the lowercase 64-digit SHA-256 of the baseline file bytes.
Hash the raw Git blob before UTF-8 decoding; newline conversion or re-encoding
`base_source` cannot establish its identity. The repository ID must match the
resolved repository, not merely its pathname. A missing baseline file or identity
mismatch refuses this adapter.

Paths use relative POSIX components: no empty, `.`, `..`, absolute, backslash
or NUL components. Ordinary modes are integers `0..511`; special bits refuse.

Each case contains exactly `id`, `request_base64` and `expected`. IDs are
nonempty NUL-free strings. `request_base64` is canonical padded RFC 4648 base64,
without whitespace, decoding to the exact request bytes; the harness adds no
newline. Requests need not themselves be JSON. `expected` is a strict JSON value.
Expectations are never mounted into the child or included in ordinary receipts.

For example, these complete case objects check an addition command:

```json
[
  {"id":"positive","request_base64":"WzIsM10K","expected":{"sum":5}},
  {"id":"negative","request_base64":"Wy0yLDNdCg==","expected":{"sum":1}}
]
```

These cases are the complete required population when
`required_case_ids` is `["positive","negative"]`. Reducing the population changes
the specification identity and requires a fresh reviewed specification and run.

### Limit fields

Limits are integers, never Boolean values. Every field is required. Preparation never silently clamps a request; unsupported values refuse. The
example/default values below do not make omitted fields valid. Storage and output ceilings are enforced while data
is produced, before parsing or reading an entire capture into memory.

| Field | Example value | Supported inclusive range | Scope |
|---|---:|---:|---|
| `wall_seconds` | 5 | 1–60 | Each case, including stdin delivery |
| `cleanup_seconds` | 5 | 1–30 | Each owned execution scope |
| `cpu_seconds` | 2 | 1–30 | Hard CPU time for the sole candidate process |
| `memory_bytes` | 268435456 | 67108864–1073741824 | Hard address-space ceiling for the sole candidate process |
| `processes` | 1 | Exactly 1 | No additional candidate processes or threads |
| `scratch_bytes` | 16777216 | 4096–67108864 | Private writable storage per case |
| `scratch_inodes` | 4096 | 16–65536 | Aggregate private scratch files and directories per case |
| `source_bytes` | 1048576 | 1–1048576 | Captured source |
| `request_bytes` | 65536 | 1–65536 | Decoded request per case |
| `stdout_bytes` | 65536 | 1–1048576 | Response capture per case |
| `stderr_bytes` | 65536 | 1–1048576 | Diagnostic capture per case |

The specification has at most 256 cases and is at most 4 MiB encoded. Response
syntax must also fit the strict JSON bounds. A child exit of zero after output
truncation is incomplete execution, not a valid response.

The inode bound covers empty files and directories, including the scratch root;
the byte bound covers aggregate scratch capacity. Both are hard bounds enforced
while entries or data are created. Neither a per-file `RLIMIT_FSIZE` nor a
post-run directory count supplies aggregate protection. Descriptor and other
metadata caps are also explicit in the prepared policy. Missing effective
enforcement of any requested bound refuses execution.

## Strict JSON and identities

`strict_json.py` handles specifications, observations, audits and journals.
It rejects duplicate keys, trailing documents, invalid UTF-8, byte-order marks,
unpaired surrogates, NaN/Infinity, and values exceeding these limits:

| Limit | Maximum |
|---|---:|
| Container nesting depth, counting the root container as 1 | 32 |
| Members in one array or object | 4096 |
| Total values, including object keys | 16384 |
| UTF-8 bytes in one decoded string | 87384 |
| Characters in one numeric token | 128 |
| Absolute explicit decimal exponent | 308 |

The decoded-string ceiling includes the ASCII `request_base64` field. A
65,536-byte request encodes to `4 * ceil(65536 / 3) = 87,384` characters, which
fits this bound. Decode canonical base64 only after checking that field's bound,
then enforce `limits.request_bytes` on the decoded bytes. The 4 MiB specification
ceiling still applies to the entire document; the maximum case count and maximum
per-case request size cannot necessarily be used together.

Bounds apply before unbounded recursion, integer conversion or decimal expansion.
Object key order is irrelevant; array order matters. Booleans, integers and
decimal numbers are distinct types: `true`, `1` and `1.0` do not compare equal.
Decimal comparison uses exact base-ten values, so `1.0` equals `1e0`. Negative
zero equals zero within its numeric type. No binary floating-point rounding,
string coercion or Unicode normalization is applied.

Identity encoding uses a tagged JSON tree. Null is `["null"]`; Booleans are
`["bool",value]`; strings are `["str",value]`; integers are `["int",digits]`;
decimals are `["decimal",coefficient,exponent]`. Numeric components are canonical
base-ten strings, with no leading plus/zeros; decimal trailing coefficient zeros
are removed while adjusting the exponent, and decimal zero is `"0","0"`.
Arrays use `["array",children]`; objects use `["object",pairs]` with string keys
sorted by Unicode code point and each pair containing its key and encoded value.
Serialize this tree as compact UTF-8 JSON with `ensure_ascii=False` and no spaces.

An identity is lowercase hex SHA-256 over
`UTF8("agent-self-evolution:" + domain + ":1")`, one NUL byte, then that encoding.
Domains are distinct for `specification`, `runtime`, `policy`, `snapshot`,
`campaign`, `organism`, `seed` and `journal-record`. Raw source/request digests
use SHA-256 over exact bytes; those digests are fields inside structured
identities. Paths, modes, ordered case IDs and baseline identities participate
in their relevant structured identities. Digests detect changes; they confer no
authority over attacker-controlled storage.

## Trusted runtime configuration

`--verification-runtime-config` selects an absolute protected registry file;
there is no repository, PATH, environment or home-directory fallback.
`--runtime-id` selects one entry and must equal the specification's runtime ID.
`--base-python` remains the diagnostic repair interpreter and cannot select the
semantic runtime.

The registry has exactly `schema_version` (`"1"`) and `runtimes` (a nonempty
object keyed by runtime ID). Each entry contains exactly:

| Field | Type | Meaning |
|---|---|---|
| `interpreter` | string | Absolute, pinned regular executable |
| `interpreter_sha256` | string | SHA-256 of its exact bytes |
| `runtime_roots` | array of strings | Absolute, independently controlled readonly runtime roots |
| `runtime_manifest_sha256` | string | Canonical digest of runtime relative paths, bytes and ordinary modes |
| `backend` | string | `bubblewrap` for supported Linux semantic verification |
| `policy` | string | Exactly `python-json-command-v1` |

The runtime manifest is an array sorted by `(root_index, path)`. Each entry
contains exactly `root_index` (integer index in `runtime_roots`), `path`
(relative path), `kind` (`file` or `directory`), `mode` (ordinary permission bits)
and `source_sha256` (raw byte digest for a file, null for a directory). Directory
entries include otherwise-empty directories. Symlinks and special files are
excluded by trusted provisioning; any unexpected entry invalidates the manifest.
`runtime_manifest_sha256` is SHA-256 over the canonical tagged encoding of that
array, before domain separation; the complete runtime handle has its own
`runtime` domain identity. Inventory is bounded to 2,048 entries, 64 MiB per
regular file and 256 MiB
total file content. Runtime roots are ordered, unique, dedicated absolute paths
(1–16 entries). Manifests cover the interpreter, loader, standard library and
required shared libraries. Provisioning records their identities; execution revalidates
them through protected access. Broad mounts exposing home directories,
repository source, auth stores, sockets, mutable dependencies or verifier state
are refused. A runtime root cannot overlap candidate-writable or parent-authority
storage. Symlinked interpreter configurations must be resolved and pinned during
trusted provisioning, not followed through candidate-controlled paths at launch.

## Execution policy and completion

### Protected setup and entry

The launcher holds candidate entry until an independently protected observer
establishes effective controls for the complete immutable invocation. The observer
operates outside candidate control and reports through a private setup channel,
separate from stdout and stderr. Candidate-written JSON, a mutable dictionary,
a generic successful subprocess or a later host probe cannot approve entry.

The parent compares observed namespaces, mount views, capabilities, syscall/ABI
filters, process/network restrictions, aggregate scratch limits, metadata/FD
caps, supervisor lineage and inherited descriptors with the prepared policy.
It binds invocation ID, execution mode, source/mode, request and the complete
runtime, loader, bootstrap and backend identity. Failed, missing or mismatched
observations prevent entry. Control and authority descriptors close before the
candidate starts; private observation storage stays outside candidate access.

Protection persists through execution and cleanup. Runtime leases cover the
full dependency closure and substitutable ancestors; rechecking path hashes
afterward cannot substitute for continuous protection. Effective grants include
aliases, bind mounts, ancestor writes and descriptor exposure. These exclusions
also apply to setup/builds, authoritative imports, repair tests and benchmarks,
before any candidate-capable phase runs. Unknown enforcement refuses that phase.

### Candidate limits and transport

The Linux policy allows one candidate process and no threads. Each case uses a
fresh namespace, read-only source/runtime mounts and private bounded scratch.
Capabilities are dropped, descriptors are closed and the environment is cleared.
Network/socket access, ambient imports, host credentials, protected inputs and
parent authority storage are inaccessible. The interpreter uses `-I -S -B`;
[Python isolation flags](https://docs.python.org/3.14/using/cmdline.html#cmdoption-I)
reduce ambient configuration, while OS containment supplies the security boundary.

The prepared policy manifest binds architecture/ABI filtering, backend arguments,
implementation identities, numeric descriptor/file/metadata caps, hard CPU and
address-space limits, and aggregate scratch capacity. Absent or ineffective
bounds refuse preparation. Process/thread creation denial must be demonstrated
for every supported ABI; `RLIMIT_NPROC` alone does not establish it. Unknown
architectures refuse. Trusted supervisor and Bubblewrap overhead is outside
candidate limits.

[Bubblewrap's security model](https://github.com/containers/bubblewrap#security)
requires caller-defined policy. Architecture-aware
[seccomp filtering](https://docs.kernel.org/userspace-api/seccomp_filter.html)
is one layer. Python's [resource limits](https://docs.python.org/3.14/library/resource.html)
are platform-specific, per-process limits. `RLIMIT_AS` bounds address space,
not RSS or total kernel memory. Enforced creation denial confines the candidate
workload to that single process; a process-group kill alone provides no tree-wide
guarantee. Generic detached-descendant cleanup is a separate execution contract.

The supervisor concurrently delivers stdin and captures stdout/stderr within
independent bounds. It records requested and delivered input byte counts, input
closure, both stream byte counts and EOFs, overflow and UTF-8 validity, exit or
signal, timeout, enforced limits, owned scope, termination/reaping, cleanup
deadline and supervisor completion. These facts arrive over protected supervisor
transport, never candidate stdout. Unknown facts remain unknown.

### Trusted setup and live execution leases

The launcher starts the independently protected bootstrap before transferring
candidate entry. Over an invocation-specific private control channel, the
supervisor observes namespace and mount identities, capability state, hard
resource limits, architecture-aware seccomp, scratch bounds and descriptor
closure. The parent validates those observations against its prepared policy
and approves candidate entry only after they match. Candidate stdout, a
cooperative pytest report, constructor success and a registry entry supplied by
the caller cannot establish setup. Setup/control handles close before candidate
code can execute; candidate substitution or a stale/replayed setup refuses entry.

The supervisor establishes the effective policy before candidate entry and closes
all nonstandard authority, setup, runtime and control descriptors. Setup uses a
private channel separate from candidate output. Failed setup prevents entry. A
private, process-local lease binds the exact returned result object to setup,
invocation, runtime, policy, source/mode, execution mode, request, transport and cleanup. Its owner is the
issuing process incarnation, not a reusable PID. Issuance occurs only after the
launcher has validated complete execution, transport and cleanup. An
`enforcement_id` is an audit identifier; a matching string, successful canary,
caller-created result or serialized receipt cannot recreate the lease. Host
probes do not replace setup evidence for each invocation. See the
[protected execution schema](reference/deployment-evidence.md#protected-execution-evidence-schema-2).

Every semantic case requires full stdin delivery, input closure, both output EOFs,
no overflow, valid UTF-8 on both streams, exactly one strict JSON response, exit
zero, effective limits and confirmed whole-scope termination/reaping. Nonempty
bounded stderr is allowed. Overflow terminates execution. Partial delivery,
timeout, supervisor failure or uncertain cleanup makes the assessment
`unverifiable`, even if output appears correct or contains an apparent violation.
Complete wrong or invalid output is `rejected`. Across the full required case
and prerequisite population, missing authority or incomplete evidence takes
precedence over a demonstrated mismatch in another case: the assessment remains
`unverifiable`. No weaker fallback or privilege escalation is attempted.

## Python integration

The public operations are local Python APIs. There is no attestation service,
HTTP endpoint or certificate-import API.

| Operation | Contract |
|---|---|
| `semantic_verifier.VerificationContext.prepare(*, spec_path, runtime_config, runtime_id, export_root=None)` | Validates and pins specification, independently protected runtime, policy and optional destination; executes no candidate and installs nothing |
| `VerificationContext.current()` | Side-effect-free freshness observation; false cannot authorize use |
| `VerificationContext.close()` / context-manager exit | Idempotently revokes descendant issued authority and releases prepared leases |
| `gate.run_code_gate(..., verification=None)` / `run_code_oracle_gate(..., verification=None)` | Preserve existing arguments and diagnostics; coordinate prerequisites on retained source |
| `gate.finalize_verification(result, *, env, tool_relpath, base_source, verification=None)` | Accepting boundary; refreshes assessment and optional authority on the result, returns `None` |
| `deployment_evidence.verify_deployment(env, *, tool_relpath, verification=None)` | Compatibility refusal-only helper, always `unverifiable / independent_test_verification_unavailable`; the optional keyword is inert |
| `CodeGateResult.deploy` | Read-only observation that this result currently owns issued export authority |
| `CodeGateResult.export_authorization` | Opaque registered handle or `None`; never serialized |
| `CodeGateResult.export_receipt` | Defensive read-only copy of the last identified claim receipt; survives failure, cancellation and owner closure |
| `CodeGateResult.close()` / context-manager exit | Idempotently revokes unused authority and releases retained resources |
| `verified_export.export_verified(authorization, *, destination_root, target)` | Claims authority once and installs retained bytes/mode at its bound target |

`VerificationContext` lives in `evolution.code.semantic_verifier`. Its
`runtime_config` and optional `export_root` are explicit absolute paths;
`runtime_id` selects the registry key, while audit `runtime_id` is a content
identity. Preparation checks effective protection against candidate modification
and ancestor substitution, content identities, dependencies and destination
traversal. It closes partial leases on failure and provisions no runtime.

`SemanticAssessment` is immutable audit data: `status`, `reason`, `audit` and
derived `summary`. It has no authority field. Runtime/snapshot constructors,
prerequisite registration and the semantic executor are internal coordination
seams, not caller-controlled certification APIs. Candidate mappings cannot mint
observations or authority.

Generic path/execution facilities remain in `evolution.core`; core imports no
tier. Validation's lazy composition boundaries are unchanged. DSPy remains
`>=3.4.1,<3.5` with explicit `engine="litellm"` selection.

## Authorization and export

### Snapshot-bound prerequisites

The coordinator resolves an immutable prerequisite plan from trusted gate
configuration before consulting diagnostic results. The plan fixes applicability,
ordered populations, command/input identities, baseline expectations and protected
evaluators. Candidate-written mappings cannot add, delete, weaken or satisfy a
requirement. A selected suite or benchmark without a protected evaluator makes
the assessment `unverifiable`; success on JSON cases does not waive it.

1. Resolve the full baseline commit and hash its raw blob. Finish repair execution
   and confirm all owned scopes terminated and were reaped.
2. Retain exact candidate bytes, canonical relative target and ordinary mode.
   Scope and surface checks consume this snapshot. Diagnostics, regression/oracle
   and applicable benchmarks execute against the retained read-only target;
   baseline comparisons use their own bound baseline snapshot.
3. Replay every applicable execution prerequisite through protected execution
   against retained candidate bytes, then register parent-observed records including command, test-input,
   configuration and invocation/receipt identities. Every applicable prerequisite
   must pass; an inapplicable gate needs an explicit policy reason.
4. Seal the retained source after prerequisite execution. Run the coordinated
   semantic case population, compare in the protected parent and finish cleanup.
   Bind the final execution epoch and revalidate every prerequisite before optional
   issuance. No authority exists while this assessment is collecting evidence.

| Prerequisite | Required binding |
|---|---|
| Scope and surface | Checked Git scope, canonical target, baseline and retained source/mode |
| Visible and held-out diagnostics | Distinct reviewed selections, exact test inputs, runtime and completed invocations |
| Oracle/holdout comparison | Complete baseline and candidate observations for the declared population before subtraction |
| Regression floor | Matching baseline/input/configuration identities; a new file needs complete green execution |
| Configured benchmark | Exact command, baseline/candidate snapshots, limits and complete protected execution |

Every applicable entry has a parent-registered protected observation. Mutable
diagnostic dictionaries and earlier pytest success cannot supply it. Each explicit
inapplicability has a policy reason; missing protected semantic coverage cannot
be renamed inapplicable. Cooperative tests describe diagnostic outcomes, while
protected cases establish semantic conformance. Neither channel substitutes for
the other.

An earlier green writable diagnostic or benchmark cannot certify subsequently
captured bytes. Missing, mismatched, stale or uncertain evidence refuses
acceptance. The [prerequisite schema](reference/deployment-evidence.md#snapshot-prerequisite-observations)
records these associations but only parent registry provenance makes them usable.

An accepted assessment without `export_root` has reason `semantic_checks_passed`,
`deploy=False` and `export_authorization=None`. With a prepared destination,
authority binds issuing process incarnation, context, destination descriptors, target,
bytes/mode, raw baseline, specification, complete runtime/bootstrap/backend and
policy identities, invocation and execution mode, prerequisites and final
execution epoch. `decision` and audits remain descriptive after consumption.
Neither `RepairResult.final_source`, oracle `correct`, campaign reachability nor
an accepted summary authorizes export.

### Gate-to-export ownership

Contexts own prepared leases; gate results own snapshots, prerequisite resources
and optional issued authority. Keep both open through assessment/export and close
both on every exit. The CLI uses one outer cleanup scope and persists explicit
redacted audit mappings, never live owners or handles.

Re-finalization first revokes previous authority, clears readiness and old audit,
and releases obsolete assessment resources before any early return or dispatch.
It reuses only current coordinator-registered prerequisite observations; otherwise
it reruns applicable checks against a fresh snapshot or refuses. Every subsequent
candidate dispatch, including setup, import, test, benchmark or a launch that
fails, invalidates authority *before* dispatch. Cancellation, failed assessment,
exceptions, source/mode/context drift and explicit closure revoke unused authority.

Owners and handles reject copy, deep copy and serialization/pickling. Issuing
Process-incarnation checks reject fork inheritance and PID reuse. Forged, copied, deserialized, foreign or
replayed handles cannot acquire a lease. A trusted-parent restart needs fresh
assessment; orphan storage is cleanup material, never recoverable authority.

Under one registry lock, authority follows `issued → claimed → consumed` or
`issued → revoked`. At most one concurrent claim succeeds. Claiming an identified
issued handle is irreversible even for a wrong destination or failed installation.
Unidentified handles raise `ValueError` with prefix `export_authorization_invalid`
without fabricating a receipt. A claim transfers payload/lease ownership through
cleanup; concurrent context/result closure cannot erase its retained payload.
Success, failure and cancellation consume the claim in `finally`.

### Installation and failure outcomes

Export accepts only the prepared existing root and bound relative target.
Preparation binds the complete existing destination parent, including nested
parents; binding the root alone is insufficient. Claim revalidates that binding
and transfers the owned parent descriptor together with the retained payload
under the registry lock. Substitution before claim refuses; substitution after
claim cannot redirect installation away from the pinned directory. Safe
existing parents are required; it creates no directories and follows no symlinks.
It writes every retained byte to an exclusive private regular temporary file,
applies the retained mode, fsyncs the file, atomically replaces the target, fsyncs
the parent and verifies installed bytes/mode through pinned descriptors. It never
reopens mutable candidate source. Multi-file deployment and publication are
unsupported; publication requests fail before preparation, execution or spend.

The version `"2"` receipt has exactly `schema_version`, `status`, `reason`,
`assessment_id`, `snapshot_id`, `source_sha256`, `destination_id`, `target`, `mode`,
`phase` and `replacement`. IDs are bound digests; mode is an ordinary integer.

| Field | Values |
|---|---|
| `status` | `succeeded`, `failed` |
| `reason` | `export_completed`, `export_authorization_invalid`, `export_destination_invalid`, `export_io_failed`, `export_interrupted` |
| `phase` | `claim`, `destination`, `temporary_write`, `file_sync`, `replace`, `directory_sync`, `verify`, `complete` |
| `replacement` | `not_replaced`, `replaced_durable`, `replaced_durability_uncertain`, `replacement_unknown` |

Only `succeeded + complete + replaced_durable` means success. Failed durability or
verification after confirmed replacement is `replaced_durability_uncertain`;
ambiguous replacement is `replacement_unknown`. Failure before replacement is
`not_replaced`. Cleanup errors do not overwrite the primary outcome.
Identified stale-authority failures retain `export_authorization_invalid` with
a claim-phase receipt and consume the identified claim. `ExportError`, a
`ValueError` subclass, carries `.receipt` for identified claim failures. Cancellation propagates after retaining its identified-claim receipt
in `CodeGateResult.export_receipt` for outer persistence, including after close. Receipt-write failure cannot restore authority.
Inspect the installed target before recovery; every retry needs fresh authorization.

## Errors and persisted evidence

Boundary failures use a stable lowercase reason prefix, optionally followed by
`: detail`. Match the prefix rather than human prose. Operational/preparation and
programming errors raise; complete ordinary candidate failures return an assessment.

| Prefix | Meaning |
|---|---|
| `verification_prerequisites_unavailable` | No complete protected retained-byte prerequisite evaluator exists |
| `semantic_spec_invalid` | Invalid/unsupported specification, including processes other than 1 |
| `verification_runtime_untrusted` | Runtime identity, ownership, dependencies or protection unavailable/drifted |
| `verification_containment_unavailable` | Policy, architecture or effective bounds unavailable/unproven |
| `independent_test_verification_unavailable` | No configured accepting verifier; always used by the compatibility helper |
| `verification_context_stale` | Bound source, mode, baseline, context or epoch drift |
| `verification_evidence_invalid` | Forged, missing or mismatched prerequisite/receipt |
| `verification_execution_incomplete` | Incomplete input/output, overflow, encoding failure, timeout or supervisor failure |
| `verification_cleanup_unconfirmed` | Scope termination/reaping unknown; stop dependent work |
| `semantic_child_failed` | Complete observed nonzero child exit |
| `semantic_response_invalid` | Complete output is not one strict JSON value |
| `semantic_response_mismatch` | Complete valid response differs from expectation |

`gate_decision.json.deployment_verification` remains the three-field version `"1"`
summary: `schema_version`, `status` and `reason`. Detailed
`semantic_verification.json` uses version `"2"` and exactly these additional
fields: nullable `baseline`, `snapshot_id`, `specification_id`, `runtime_id`,
`policy_id`, `prerequisite_id`, `assessment_id`; ordered `required_case_ids`,
`cases`; string arrays `violations`, `unavailable`. `assessment_id` hashes the
complete audit excluding itself. IDs remain null before establishment.

Each case has exactly `case_id`, `invocation_id`, `request_sha256`, nullable
`response_sha256`, nullable `exit_code`, nullable `stdin_complete`,
`stdout_complete`, `stderr_complete`, `cleanup_complete`, `comparison` and nullable
`receipt_id`. Completion observations are Boolean or null; `comparison` is
`matched`, `mismatched`, `invalid` or `not_compared`. Every required case remains represented in order, including
unlaunched cases whose facts remain unknown. Acceptance requires the complete
ordered population matched with no violations or unavailable facts. Audits contain no expected responses, raw
requests, credentials or authority.

Private evidence files use `0600`, directories `0700`. Raw bounded captures are
private and redacted before sharing. Snapshot storage lasts until result/claim
cleanup. Specifications and provisioned runtimes have separate administrative
retention. Readers dispatch on exact artifact versions. The runtime
registry, strict identity encoding, compact summary and code gate use version
`"1"`. The semantic specification uses `"2"`, including required
`scratch_inodes`; the command protocol kind remains `python-json-command-v1`.
Protected execution evidence, prerequisite observations, detailed audits, export
receipts, campaign journals and native evidence also use `"2"`. An older
specification without an aggregate metadata bound cannot authorize execution.
Matching version labels cannot supply absent required evidence or satisfy the
[recovery contract](campaign_recovery.md).
Unsupported historical records remain history,
with no automatic migration, compatible resume or restored authority.

## Native evidence

The collector runs credential-free probes and demonstrations through production
APIs and writes version `"2"` evidence. It requires explicit `--verification-runtime-config`,
`--runtime-id` and `--output-dir`; `--demo` requests known-good acceptance,
wrong-response rejection, exact-byte/mode export and replay rejection. It invokes
no provider, agent or dependency installer. See the [tutorial](tutorials/verify-json-command.md).

`native_evidence.json` version `"2"` records `host`, `framework_id`, `runtime_id`,
`policy_id`, `demo_requested`, `probes`, `demonstrations` and numeric
`collector_exit_code` beside `schema_version`. Host fields are `platform`, `kernel`, `backend`. The framework
identity binds a complete source manifest including new files. Runtime/policy
identities are nullable before preparation. Declared probe/demo populations are
complete, including entries that could not execute.

Each result has `id`, `category`, `status`, redacted argument-array `command`,
nullable child `exit_code`, redacted `observation` and `receipt_ids`. An unlaunched
child has a null exit, never a fabricated zero. The detached collector separately
records its numeric process exit, command and log digest in a synchronized
receipt; missing collector completion is unknown. Categories are
`semantic_policy`, `generic_cleanup`, `demonstration`.

| Status | Meaning |
|---|---|
| `enforced` | Successful production execution demonstrates the required property |
| `refused` | Attempted production launch was refused |
| `failed` | Observed guarantee/control failure |
| `unavailable` | Required capability could not be exercised |
| `skipped` | Named precondition prevents this check |
| `not_requested` | Optional work explicitly omitted |

Probes exercise malicious interference and transport through the production
builder, using synthetic credential canaries rather than real secrets:

| Control | Required exercise |
|---|---|
| Protected state | Read/write/substitution attempts against expectations, runtime, source, journals and authority; denied tracing/process-memory/descriptor access |
| Import/environment | Ambient module and startup injection; canaries absent from the candidate environment |
| Network | TCP, UDP and Unix-socket denial, including host control paths |
| Resource bounds | Hard CPU/address-space, aggregate scratch and metadata/FD caps; reject unsupported process counts/ABIs |
| Transport | Partial stdin delivery, concurrent stdout/stderr, independent EOF/overflow, invalid UTF-8 and wall deadlines |
| Authority | Forged candidate receipts/results, copied/serialized/inherited handles, invocation replay, concurrent claims and destination substitution |
| Lifecycle | Cancellation, timeout, supervisor failure, double-fork/`setsid`, retained output descriptors and signal-resistant descendants |

Process/thread creation denial belongs to semantic policy evidence; double-fork,
detached, signal-ignoring and inherited-output cleanup probes belong to generic
execution evidence. Denial is not a demonstration of descendant reaping.

Exit 0 requires every required probe and requested demonstration to be enforced.
Exit 1 records an observed failure, taking precedence if capability gaps also
exist. Exit 2 records required capability/refusal gaps without an observed
failure.
Refusal is truthful evidence but never successful acceptance/export validation.
Implementation support and host validation are separate report dimensions. An
unavailable host blocks positive native validation; it does not satisfy the
accepting implementation requirement. A validation set is incomplete if known-good acceptance, wrong-response
rejection, exact-byte/mode export or replay rejection cannot run. Linux evidence cannot certify
macOS. Native macOS success requires actual macOS receipts; neither mocks nor
`sandbox-exec` discovery suffice. Run-specific outcomes belong in review receipts,
not permanent claims about a host.
