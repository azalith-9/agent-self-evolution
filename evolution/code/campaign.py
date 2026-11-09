"""``evolve_code_campaign`` — the code-evolution measurement campaign.

Harvests real historical tool bugs, repairs each in an isolated worktree, and
verifies the repair against the upstream-fix oracle (no held-out split — the
oracle is the ground truth). Runs staged (N=8→20→50) with an organism-level
futility stop, so spend escalates only while the GREEN holds. Reports
cluster-honest organism-level estimands. This validates the loop at scale; the
novel-bug-repair product (held-out split, live feed) is deferred.

Run: ``python -m evolution.code.campaign --repo <hermes> --max-organisms 8``
"""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
import os
import uuid
from decimal import Decimal
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from evolution.code.campaign_state import CampaignJournal, SeedProgress
from evolution.code import strict_json as js
from evolution.code.campaign_report import OrganismResult, build_report
from evolution.code.gate import run_code_oracle_gate
from evolution.code.harvest import (
    Candidate,
    _failures,
    harvest_candidates,
    stratify,
)
from evolution.code.repair import RepairEngine, build_dspy_proposer
from evolution.core.sandbox import require_sandbox_or_fail
from evolution.code.worktree import (
    ContainmentError,
    NonAuthoritativeRunError,
    WorktreeEnv,
    WorktreeError,
)
from evolution.core.hermes_provider import resolve_default_lm

console = Console()

# The proposer emits the COMPLETE corrected file, so the output budget must hold
# the whole rewrite plus chain-of-thought reasoning. At 8000 a large tool's
# rewrite truncates → unparseable → a false "couldn't repair". 32000 (~120k chars)
# covers nearly all tools; genuinely huge ones are excluded by MAX_TOOL_CHARS
# rather than silently truncated (whole-file rewrite has an inherent size ceiling).
PROPOSER_MAX_TOKENS = 32000
MAX_TOOL_CHARS = 80000


@dataclass
class Skip:
    """A candidate that yielded no organism, with the reason (for the ledger)."""

    reason: str


def _git_show(repo: Path, ref: str) -> Optional[str]:
    import subprocess

    r = subprocess.run(["git", "-C", str(repo), "show", ref],
                       capture_output=True, text=True, timeout=120)
    return r.stdout if r.returncode == 0 else None


def run_organism(
    repo: Path, c: Candidate, engine: RepairEngine, *, seeds: int,
    base_python: str | None, max_tool_chars: int = MAX_TOOL_CHARS,
    require_sandbox: bool = True,
    seed_progress: SeedProgress | None = None,
) -> "OrganismResult | Skip":
    """Repair one harvested bug across ``seeds`` seeds in a single worktree and
    verify each against the oracle. Returns a :class:`Skip` (with reason) when the
    candidate yields no organism: source missing, too large for a whole-file
    rewrite, worktree setup failed, a test run that established nothing
    (``run_inconclusive``), or the parent doesn't fail anything the fix passes
    (not a clean single-tool bug)."""
    parent_src = _git_show(repo, f"{c.parent_sha}:{c.tool_path}")
    if parent_src is None:
        return Skip("source_missing")
    if len(parent_src) > max_tool_chars:
        # Whole-file rewrite would exceed the output budget; excluded honestly
        # rather than counted as an unrepairable bug (a method ceiling, not a
        # loop failure). Diff-based repair for huge files is a future extension.
        return Skip("too_large")
    try:
        env = WorktreeEnv.create(repo, base_ref=c.fix_sha, base_python=base_python,
                                 require_sandbox=require_sandbox)
    except ContainmentError:
        # Systemic, not this organism's: a broken profile fails every run, and
        # absorbing it as a skip would grind through the whole candidate list
        # reporting "worktree_failed" for a cause unrelated to worktrees.
        raise
    except WorktreeError:
        return Skip("worktree_failed")
    try:
        env.assert_authoritative(c.tool_path.split("/")[0])
        # Oracle (fix) is on disk at fix_sha → its own failures are env-flaky tests.
        oracle_failures = frozenset(_failures(env, c.test_path))
        env.write_tool(c.tool_path, parent_src)
        bug_tests = tuple(sorted(set(_failures(env, c.test_path)) - oracle_failures))
        if not bug_tests:
            return Skip("not_valid")
        seed_results: list[bool] = []
        for index in range(seeds):
            if seed_progress is not None and index in seed_progress.completed:
                seed_results.append(seed_progress.completed[index]['diagnostic_status'] == 'passed')
                continue
            attempt = (seed_progress.start(index, retry_of=seed_progress.latest_inconclusive(index))
                       if seed_progress is not None else None)
            env.write_tool(c.tool_path, parent_src)  # reset to buggy
            with attempt.capture_costs() if attempt is not None else nullcontext():
                repair = engine.repair(env, c.tool_path, bug_tests)
            try:
                gate = run_code_oracle_gate(
                    env, tool_relpath=c.tool_path, test_relpath=c.test_path,
                    bug_tests=bug_tests, oracle_failures=oracle_failures,
                    base_src=parent_src, repair_result=repair,
                )
                diagnostic = gate.decision.get("diagnostic_comparison", {})
                try:
                    if diagnostic.get("status") not in {"passed", "failed"}:
                        if seed_progress is not None:
                            seed_progress.record_attempt(index, attempt_id=attempt.attempt_id,
                                reason="run_inconclusive", observation_digest=None)
                        return Skip("run_inconclusive")
                    if seed_progress is not None:
                        attempt.commit(dict(diagnostic_seed_result(gate.decision),
                            cost_observation_ids=attempt.cost_references()))
                    seed_results.append(diagnostic["status"] == "passed")
                finally:
                    gate.close()
            except NonAuthoritativeRunError:
                return Skip("run_inconclusive")

        return OrganismResult(tool=c.tool_path, fix_sha=c.fix_sha, seeds=seed_results)
    except ContainmentError:
        raise  # systemic; see the create-time handler above
    except NonAuthoritativeRunError:
        # The candidate could not be measured (hang, kill, uncollectable tests).
        # Its own reason, so the ledger does not blame worktree setup for it.
        return Skip("run_inconclusive")
    except WorktreeError:
        return Skip("worktree_failed")
    finally:
        env.destroy()


def run_campaign(
    repo: Path,
    *,
    output_dir: Path,
    max_organisms: int = 50,
    stages: tuple[int, ...] = (8, 20, 50),
    seeds: int = 3,
    max_rounds: int = 5,
    max_per_tool: int = 3,
    max_tool_chars: int = MAX_TOOL_CHARS,
    max_cost_usd: Optional[float] = None,
    proposer_model: Optional[str] = None,
    base_python: Optional[str] = None,
    require_sandbox: bool = True,
    organism_runner=None,
    progress_runner=None,
    identity_configuration: dict | None = None,
    resolved_production_identity: dict | None = None,
    candidates: Optional[list[Candidate]] = None,
) -> dict:
    """Drive the staged campaign. Resumable: organisms already in the ledger are
    skipped. Futility-stops at a stage boundary if organism-level deploy-reachable
    Wilson-lower < 0.10.

    ``organism_runner`` / ``candidates`` are injection seams for testing the
    orchestration (ledger, resume, futility, stratification) without LM spend or
    worktrees; in production both default to the real harvest + repair+gate path.
    """
    if organism_runner is not None and progress_runner is not None:
        raise ValueError("select exactly one organism or progress runner")
    # Injected runners do not execute candidate code. Real adapters enforce this again.
    if organism_runner is None and progress_runner is None:
        require_sandbox_or_fail(require_sandbox)
    from evolution.core.lm_timing_callback import COST_LEDGER, CostCeilingExceeded

    output_dir = Path(output_dir).absolute()
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidates = list(candidates) if candidates is not None else stratify(
        harvest_candidates(repo), max_per_tool=max_per_tool)
    if not (output_dir / "campaign_progress.jsonl").exists() and (output_dir / "campaign_ledger.jsonl").exists():
        raise ValueError("campaign_state_incompatible: legacy ledger needs independently demonstrated identities")
    production = organism_runner is None and progress_runner is None
    configuration = {
        "durability": "organism" if organism_runner is not None else "seed",
        "reporting_algorithm": "cluster-honest-v1", "max_rounds": max_rounds,
        "proposer_model": proposer_model or ("resolved-at-preparation" if production else "injected"),
        "require_sandbox": require_sandbox, "runtime_id": base_python or "diagnostic-default",
        "max_tool_chars": max_tool_chars, "max_organisms": max_organisms,
        "max_per_tool": max_per_tool,
    }
    budget = None
    progress_path = output_dir / 'campaign_progress.jsonl'
    if progress_path.exists():
        prior = js.loads(progress_path.read_bytes().splitlines()[0])
        budget = prior['payload']['configuration'].get('budget_policy')
    if budget is not None or max_cost_usd is not None or production:
        configuration['budget_policy'] = budget or {
            'currency': 'USD', 'scope': 'campaign_total', 'change_rule': 'increase_only',
            'initial_ceiling_usd': Decimal(str(max_cost_usd)) if max_cost_usd is not None else None}
    if identity_configuration is not None:
        configuration["adapter"] = identity_configuration
    if production:
        configuration['resolved_production_identity'] = validate_production_identity(resolved_production_identity)
        import dspy
        from evolution.core.lm_timing_callback import (
            LMTimingCallback, register_litellm_cost_callback, register_litellm_failure_callback)
        rlm = resolve_default_lm(role="optimizer", explicit_model=proposer_model)
        if rlm.model != configuration['resolved_production_identity']['model']:
            raise ValueError('campaign_state_incompatible: resolved model differs from dispatch model')
        configuration["proposer_model"] = rlm.model
        configuration['runtime_id'] = configuration['resolved_production_identity']['runtime_id']
        configuration["temperature"] = Decimal('0.7')
        configuration["max_tokens"] = PROPOSER_MAX_TOKENS
        # Credentials are never included in resume identity material.
        configuration["dspy_version"] = dspy.__version__
        lm = dspy.LM(rlm.model, engine="litellm", **rlm.lm_kwargs,
                     temperature=.7, max_tokens=PROPOSER_MAX_TOKENS)
        dspy.configure(callbacks=[LMTimingCallback()])
        register_litellm_cost_callback()
        register_litellm_failure_callback()
        COST_LEDGER.reset()
        if max_cost_usd is not None:
            COST_LEDGER.set_ceiling(max_cost_usd)
        engine = RepairEngine(build_dspy_proposer(lm), max_rounds=max_rounds)

        def progress_runner(c: Candidate, *, seed_progress: SeedProgress):
            return run_organism(repo, c, engine, seeds=seeds, base_python=base_python,
                require_sandbox=require_sandbox, max_tool_chars=max_tool_chars,
                seed_progress=seed_progress)
    members = []
    for candidate in candidates:
        if hasattr(candidate, 'instance'):
            from dataclasses import asdict
            candidate_identity = {"adapter_kind": "swebench", "instance": js.loads(json.dumps(asdict(candidate.instance)).encode())}
        else:
            source = _git_show(repo, f"{candidate.parent_sha}:{candidate.tool_path}") if production else None
            test = _git_show(repo, f"{candidate.fix_sha}:{candidate.test_path}") if production else None
            if production and (source is None or test is None):
                raise ValueError("campaign_state_incompatible: cannot establish original source/test identities")
            candidate_identity = {
                "repository_id": str(Path(repo).absolute()), "baseline_commit": candidate.parent_sha,
                "fix_commit": candidate.fix_sha, "tool_path": candidate.tool_path,
                "test_path": candidate.test_path, "adapter_kind": "hermes" if production else "injected",
                "source_sha256": hashlib.sha256(source.encode()).hexdigest() if source is not None else None,
                "test_sha256": hashlib.sha256(test.encode()).hexdigest() if test is not None else None,
            }
        oid = js.identity('organism', candidate_identity)
        members.append({"organism_id": oid, "candidate_identity": candidate_identity, "seeds": [
            {"seed_index": index, "seed_value": index,
             "seed_id": js.identity('seed', {"organism_id": oid, "seed_index": index,
                 "seed_value": index, "configuration": configuration})} for index in range(seeds)]})
    identity = {"identity_manifest": {"repository_id": str(Path(repo).absolute()),
        "method": "repair", "seed_count": seeds, "journal_version": "2"},
        "configuration": configuration, "organisms": members, "stages": list(stages)}
    aborted = False
    with CampaignJournal.open(output_dir, identity=identity) as journal:
        def organisms_now() -> list[OrganismResult]:
            by_id = {member['organism_id']: candidate for member, candidate in zip(members, candidates)}
            return [OrganismResult(by_id[row['payload']['organism_id']].tool_path,
                by_id[row['payload']['organism_id']].fix_sha, row['payload']['seeds'])
                for row in journal.records if row['kind'] == 'organism_completed']

        def recover_stages() -> bool:
            n = len(organisms_now())
            for index, boundary in enumerate(stages):
                if index in journal._stages:
                    if journal._stages[index]['payload']['decision'] == 'stop':
                        return True
                elif n == boundary:
                    payload = journal.stage_payload(index)
                    journal.append('stage_decided', payload)
                    if payload['decision'] == 'stop':
                        return True
                elif n > boundary:
                    raise ValueError('campaign_state_corrupt: missing stage decision')
            return False

        stopped = recover_stages()
        if not journal._terminal and not stopped:
            journal.start_session(session_id=uuid.uuid4().hex,
                ceiling_usd=Decimal(str(max_cost_usd)) if max_cost_usd is not None else None)
        if not journal._terminal and not stopped:
            if production and configuration.get('budget_policy') is not None:
                ceiling = journal._sessions[journal._current_session]['payload']['ceiling_usd']
                spent = sum((row['payload']['amount_usd'] for row in journal._costs.values()
                             if row['payload']['status'] == 'measured'), Decimal('0'))
                COST_LEDGER.set_ceiling(float(max(Decimal('0'), ceiling - spent)) if ceiling is not None else None)
            for candidate, member in zip(candidates, members):
                if len(organisms_now()) >= max_organisms:
                    break
                oid = member['organism_id']
                if oid in journal._organisms:
                    continue
                progress = journal.seed_progress(oid)
                for outstanding in progress.outstanding:
                    progress.record_attempt(outstanding['seed_index'], attempt_id=outstanding['attempt_id'],
                                            reason='interrupted_before_commit')
                # A crash after the final seed commit must not invoke the adapter again.
                if len(progress.completed) == seeds:
                    org = OrganismResult(candidate.tool_path, candidate.fix_sha,
                        [progress.completed[i]['diagnostic_status'] == 'passed' for i in range(seeds)])
                else:
                    legacy_start = None
                    if organism_runner is not None:
                        prior = [r for r in journal._starts.values()
                                 if r['kind'] == 'organism_started' and r['payload']['organism_id'] == oid]
                        for row in prior:
                            if row['payload']['attempt_id'] not in journal._terminals:
                                journal.append('organism_inconclusive', {'organism_id': oid,
                                    'attempt_id': row['payload']['attempt_id'],
                                    'start_record_hash': row['record_hash'], 'reason': 'interrupted_before_commit'})
                        aid = uuid.uuid4().hex
                        journal.append('organism_started', {'organism_id': oid, 'attempt_id': aid,
                            'retry_of': prior[-1]['payload']['attempt_id'] if prior else None})
                        legacy_start = journal._starts[aid]
                    try:
                        org = (organism_runner(candidate) if organism_runner is not None else
                               progress_runner(candidate, seed_progress=progress))
                    except CostCeilingExceeded:
                        progress.recover_outstanding(reason='cost_ceiling_interrupted')
                        aborted = True
                        break
                    except BaseException as original:
                        try:
                            progress.recover_outstanding(reason='interrupted_before_commit')
                        except BaseException as recovery_error:
                            raise original from recovery_error
                        try:
                            if legacy_start is not None:
                                journal.append('organism_inconclusive', {'organism_id': oid,
                                    'attempt_id': legacy_start['payload']['attempt_id'],
                                    'start_record_hash': legacy_start['record_hash'], 'reason': 'interrupted_before_commit'})
                        except BaseException as recovery_error:
                            raise original from recovery_error
                        raise
                if not isinstance(org, OrganismResult):
                    reason = org.reason if isinstance(org, Skip) else 'not_valid'
                    if reason == 'run_inconclusive' or progress.completed or progress.latest_inconclusive(0) is not None:
                        progress.recover_outstanding(reason=reason)
                        break
                    if organism_runner is not None:
                        journal.append('organism_inconclusive', {'organism_id': oid,
                            'attempt_id': legacy_start['payload']['attempt_id'],
                            'start_record_hash': legacy_start['record_hash'], 'reason': reason})
                    if organism_runner is not None:
                        break
                    journal.append('organism_skipped', {'organism_id': oid, 'reason': reason})
                    continue
                if organism_runner is not None:
                    if len(org.seeds) != seeds or any(type(value) is not bool for value in org.seeds):
                        raise ValueError('campaign_transition_invalid: malformed injected organism')
                    aggregate = {'attempt_id': legacy_start['payload']['attempt_id'],
                                 'start_record_hash': legacy_start['record_hash']}
                else:
                    measured = progress.completed
                    if len(measured) != seeds or org.seeds != [measured[i]['diagnostic_status'] == 'passed' for i in range(seeds)]:
                        raise ValueError('campaign_transition_invalid: adapter aggregate differs from durable seeds')
                    aggregate = {'seed_record_hashes': [journal._seeds[(oid, i)]['record_hash'] for i in range(seeds)]}
                journal.append('organism_completed', {'organism_id': oid,
                    **aggregate, 'seeds': org.seeds, 'deploy_reachable': org.deploy_reachable})
                stopped = recover_stages()
                if stopped:
                    break
        if not journal._terminal and (stopped or len(journal._organisms) == len(members) or
                                      len(organisms_now()) >= max_organisms):
            journal.append('campaign_completed', {
                'stage_record_hashes': [r['record_hash'] for r in journal._stages.values()],
                'organism_record_hashes': [r['record_hash'] for r in journal._organisms.values()],
                'stop_reason': ('futility_stop' if stopped else 'population_complete'
                    if len(journal._organisms) == len(members) else 'configured_limit_reached'),
                'unexecuted_organism_ids': [x for x in journal._members if x not in journal._organisms]})
        organisms = organisms_now()
        report = build_report(organisms)
        report['containment'] = {'sandboxed': bool(require_sandbox and production),
            'mechanism': ('bubblewrap' if __import__('sys').platform.startswith('linux') else 'sandbox-exec')
                if require_sandbox and production else None, 'required': require_sandbox}
        report['aborted_on_cost'] = aborted
        observed = [row['payload'] for row in journal._costs.values()]
        report['cost_summary'] = {'observed_cost_usd': str(sum(
            (row['amount_usd'] for row in observed if row['status'] == 'measured'), Decimal('0'))),
            'unknown_remainder': (not observed or bool(journal._attempts) or
                any('attempt_id' in row['payload'] for row in journal._organisms.values()) or
                any(row['payload']['result']['cost_coverage'] == 'unknown_remainder'
                    for row in journal._seeds.values()) or
                any(row['status'] == 'unknown' or row['coverage'] != 'complete' for row in observed) or
                len(journal._terminals) < len(journal._starts)), 'observation_count': len(observed)}
        report['progress'] = {'campaign_id': journal.campaign_id, 'requested_seeds': len(members) * seeds,
            'measured_seeds': (len(journal._seeds) if organism_runner is None else len(organisms) * seeds),
            'outstanding_seeds': len(members) * seeds - (len(journal._seeds) if organism_runner is None
                else len(organisms) * seeds) -
                seeds * sum(r['kind'] == 'organism_skipped' for r in journal._organisms.values()),
            'inconclusive_seeds': len({(r['payload']['organism_id'], r['payload']['seed_index'])
                for r in journal._attempts.values()} - set(journal._seeds)),
            'completed': journal._terminal is not None}
        rows = []
        by_id = {member['organism_id']: candidate for member, candidate in zip(members, candidates)}
        for row in journal.records:
            if row['kind'] not in ('organism_completed', 'organism_skipped'):
                continue
            payload = row['payload']
            candidate = by_id[payload['organism_id']]
            rows.append({'fix_sha': candidate.fix_sha, 'tool': candidate.tool_path,
                'status': 'organism' if row['kind'] == 'organism_completed' else payload['reason'],
                **({k: payload[k] for k in ('seeds', 'deploy_reachable')} if row['kind'] == 'organism_completed' else {})})
        _derived(output_dir, 'campaign_ledger.jsonl', ''.join(json.dumps(r) + '\n' for r in rows).encode())
        _derived(output_dir, 'campaign_report.json', json.dumps(report, indent=2).encode())
        return report


def validate_production_identity(value: object) -> dict:
    """Require explicit resolved identities; operational aliases are insufficient.

    Resolution is an operator/adapter responsibility. This function validates and
    copies the declaration, not a provider's claim of immutable remote state.
    """
    from evolution.code.verification_contracts import fields, text, digest
    try:
        fields(value, {'provider', 'model', 'model_revision', 'runtime_id',
                       'harness_id', 'dataset_id', 'image_id'})
        text(value['provider'])
        text(value['model'])
        revision = text(value['model_revision'])
        if revision.lower() in {'latest', 'default', 'unknown', 'unresolved'}:
            raise ValueError('immutable model revision required')
        for name in ('runtime_id', 'harness_id', 'dataset_id'):
            digest(value[name])
        if value['image_id'] is not None:
            digest(value['image_id'])
        return js.loads(js.dumps(value))
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('campaign_state_incompatible: explicit resolved production identities required') from exc


def _derived(root: Path, name: str, payload: bytes) -> None:
    from evolution.core.secure_paths import ProtectedRoot
    with ProtectedRoot.open(root) as pinned:
        temp = '.' + name + '.' + uuid.uuid4().hex
        fd = pinned.open_regular(temp, flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, name, src_dir_fd=pinned.fd, dst_dir_fd=pinned.fd)
            os.fsync(pinned.fd)
        finally:
            try:
                os.unlink(temp, dir_fd=pinned.fd)
            except FileNotFoundError:
                pass


def diagnostic_seed_result(decision: dict) -> dict:
    """Normalize completed diagnostic measurements without granting export authority."""
    normalized = json.loads(json.dumps(decision, allow_nan=False))
    return {'diagnostic_status': decision['diagnostic_comparison']['status'],
        'reason': decision['diagnostic_comparison']['reason'], 'candidate_snapshot_id': None,
        'observation_digest': hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
        'cost_observation_ids': [], 'cost_coverage': 'unknown_remainder'}


@click.command()
@click.option("--repo", "repo_root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Target git repo to harvest + repair (e.g. the Hermes checkout).")
@click.option("--max-organisms", default=8, type=click.IntRange(min=1),
              help="Stop after this many valid organisms (default 8 = the pilot).")
@click.option("--seeds", default=3, type=click.IntRange(min=1),
              help="Repair attempts per organism (default 3; the organism is the honest unit).")
@click.option("--repair-rounds", default=5, type=click.IntRange(min=1))
@click.option("--max-per-tool", default=3, type=click.IntRange(min=1),
              help="Cap organisms per tool so the sample stays diverse (default 3).")
@click.option("--max-tool-chars", default=MAX_TOOL_CHARS, type=click.IntRange(min=1),
              help="Skip tools whose source exceeds this (whole-file rewrite ceiling).")
@click.option("--max-cost-usd", default=None, type=click.FloatRange(min=0.0),
              help="Abort cleanly when cumulative LM cost exceeds this.")
@click.option("--production-identity-file", default=None, type=click.Path(exists=True, path_type=Path),
              help="Reviewed resolved model/runtime/harness/dataset identity JSON; required for production.")
@click.option("--proposer-model", default=None)
@click.option("--base-python", default=None,
              help="Interpreter for the isolated venv (default: the repo's venv/.venv).")
@click.option("--require-sandbox/--allow-unconfined", "require_sandbox", default=True,
              help="Refuse to run tests unless the OS can confine writes to the run dir.")
@click.option("--output-dir", default=None, type=click.Path(file_okay=False, path_type=Path))
def main(repo_root, max_organisms, seeds, repair_rounds, max_per_tool, max_tool_chars,
         max_cost_usd, proposer_model, base_python, require_sandbox, output_dir, production_identity_file=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    if output_dir is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("output") / "code_campaign" / ts
    run_campaign(repo_root, output_dir=Path(output_dir), max_organisms=max_organisms,
                 seeds=seeds, max_rounds=repair_rounds, max_per_tool=max_per_tool,
                 max_tool_chars=max_tool_chars, max_cost_usd=max_cost_usd,
                 proposer_model=proposer_model, base_python=base_python,
                 require_sandbox=require_sandbox, resolved_production_identity=(
                     js.loads(production_identity_file.read_bytes()) if production_identity_file is not None else None))


if __name__ == "__main__":
    main()
