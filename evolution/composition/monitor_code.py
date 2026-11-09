"""Optionally attempt the top triage candidates with the validated repair loop.

Reuses the campaign's per-organism flow (worktree → repair → oracle gate) verbatim
and annotates each queue row with the verdict. Strictly propose-only: it records
whether the loop *could* repair the bug; it never opens a PR. A human reads the
annotated queue and decides what to deploy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional



def _build_runner(*, proposer_model, base_python, seeds, max_rounds, max_cost_usd, require_sandbox=True):
    """The real organism runner: sets up the proposer LM + cost tracking exactly
    as the campaign does, and returns a callable (repo, Candidate) -> result."""
    import dspy
    from evolution.code.campaign import run_organism
    from evolution.code.harvest import Candidate

    from evolution.code.campaign import PROPOSER_MAX_TOKENS
    from evolution.code.repair import RepairEngine, build_dspy_proposer
    from evolution.core.hermes_provider import resolve_default_lm
    from evolution.core.lm_timing_callback import (
        COST_LEDGER,
        LMTimingCallback,
        register_litellm_cost_callback,
        register_litellm_failure_callback,
    )

    rlm = resolve_default_lm(role="optimizer", explicit_model=proposer_model)
    lm = dspy.LM(rlm.model, engine="litellm", **rlm.lm_kwargs, temperature=0.7, max_tokens=PROPOSER_MAX_TOKENS)
    dspy.configure(callbacks=[LMTimingCallback()])
    register_litellm_cost_callback()
    register_litellm_failure_callback()
    COST_LEDGER.reset()
    if max_cost_usd is not None:
        COST_LEDGER.set_ceiling(max_cost_usd)
    engine = RepairEngine(build_dspy_proposer(lm), max_rounds=max_rounds)

    def _run(repo: Path, c: Candidate, *, seed_progress=None):
        return run_organism(repo, c, engine, seeds=seeds, base_python=base_python,
                            require_sandbox=require_sandbox, seed_progress=seed_progress)

    return _run, COST_LEDGER.summary


def attempt_candidates(
    repo: Path,
    candidates: list[object],
    payload: dict,
    *,
    max_cost_usd: Optional[float] = None,
    proposer_model: Optional[str] = None,
    base_python: Optional[str] = None,
    seeds: int = 3,
    max_rounds: int = 5,
    console=None,
    organism_runner=None,
    cost_summary=dict,
    require_sandbox: bool = True,
    persist: Callable[[dict], None] | None = None,
    progress_root: Path | None = None,
) -> None:
    """Attempt each candidate; annotate ``payload['candidates']`` rows in place
    with the verdict. ``organism_runner`` is an injection seam for testing."""
    from evolution.code.campaign import Skip
    from evolution.code.campaign_report import OrganismResult
    from evolution.code.harvest import Candidate
    from evolution.core.lm_timing_callback import CostCeilingExceeded

    if progress_root is not None:
        return _attempt_with_progress(repo, candidates, payload, progress_root=progress_root,
            max_cost_usd=max_cost_usd, proposer_model=proposer_model, base_python=base_python,
            seeds=seeds, max_rounds=max_rounds, require_sandbox=require_sandbox,
            organism_runner=organism_runner, persist=persist)
    if organism_runner is None:
        from evolution.code.worktree import prune_orphan_worktrees  # noqa: PLC0415
        prune_orphan_worktrees(repo)  # self-heal leaks from a prior hard-killed run
        organism_runner, cost_summary = _build_runner(
            proposer_model=proposer_model, base_python=base_python,
            seeds=seeds, max_rounds=max_rounds, max_cost_usd=max_cost_usd,
            require_sandbox=require_sandbox)

    by_key = {(r["tool"], r["fix_sha"]): r for r in payload.get("candidates", [])}
    for rc in candidates:
        c = Candidate(rc.tool_path, rc.test_path, rc.fix_sha, rc.parent_sha)
        row = by_key.get((rc.tool_path, rc.fix_sha))
        if row is not None:
            row["attempt"] = {"status": "running"}
        if persist is not None:
            persist(payload)
        try:
            res = organism_runner(repo, c)
        except CostCeilingExceeded:
            if row is not None:
                row["attempt"] = {"status": "cost_ceiling"}
            if persist is not None:
                persist(payload)
            if console is not None:
                console.print("[yellow]cost ceiling reached during attempts[/yellow]")
            break
        if isinstance(res, OrganismResult):
            attempt = {"status": "attempted", "correct_seeds": res.n_correct,
                       "seeds": len(res.seeds), "deploy_reachable": res.deploy_reachable}
        else:
            attempt = {"status": res.reason if isinstance(res, Skip) else "not_valid"}
        if row is not None:
            row["attempt"] = attempt
        payload["cost_summary"] = cost_summary()
        if persist is not None:
            persist(payload)
        if console is not None:
            console.print(f"  attempted {rc.tool_path.split('/')[-1]}@{rc.fix_sha[:8]}: "
                          f"{attempt}")
    payload["cost_summary"] = cost_summary()


def _git(repo: Path, *args: str) -> object:
    from evolution.code.harvest import _git as git
    return git(repo, *args)


def harvest_candidates(*args: object, **kwargs: object) -> list:
    from evolution.code.harvest import harvest_candidates as harvest
    return harvest(*args, **kwargs)


def _attempt_with_progress(repo: Path, candidates: list, payload: dict, *, progress_root: Path,
                           max_cost_usd: float | None, proposer_model: str | None,
                           base_python: str | None, seeds: int, max_rounds: int,
                           require_sandbox: bool, organism_runner: object,
                           persist: Callable | None) -> None:
    from evolution.code.campaign import run_campaign
    from evolution.code.harvest import Candidate
    population = [Candidate(c.tool_path, c.test_path, c.fix_sha, c.parent_sha) for c in candidates]
    runner = (lambda candidate: organism_runner(repo, candidate)) if organism_runner is not None else None
    report = None
    try:
        report = run_campaign(repo, output_dir=progress_root, candidates=population,
            max_organisms=len(population), stages=(), seeds=seeds, max_rounds=max_rounds,
            max_cost_usd=max_cost_usd, proposer_model=proposer_model, base_python=base_python,
            require_sandbox=require_sandbox, organism_runner=runner,
            identity_configuration={'ordered_queue': [vars(c) for c in candidates]})
    except BaseException as original:
        try:
            _reconstruct_progress(progress_root, candidates, payload, report=report, persist=persist)
        except BaseException as persistence_error:
            raise original from persistence_error
        raise
    else:
        _reconstruct_progress(progress_root, candidates, payload, report=report, persist=persist)


def _reconstruct_progress(progress_root: Path, candidates: list, payload: dict, *,
                          report: dict | None, persist: Callable | None) -> None:
    from evolution.code.campaign_state import CampaignJournal
    from evolution.code import strict_json as js
    path = Path(progress_root) / 'campaign_progress.jsonl'
    if not path.exists():
        return
    rows = CampaignJournal.inspect(Path(progress_root))
    initialization = rows[0]['payload']
    ordered = initialization['configuration'].get('adapter', {}).get('ordered_queue')
    if not js.equivalent(ordered, [vars(candidate) for candidate in candidates]):
        raise ValueError('campaign_state_incompatible: complete ordered queue differs')
    members = initialization['organisms']
    if len(members) != len(candidates) or any(
            m['candidate_identity'].get('tool_path') != c.tool_path or
            m['candidate_identity'].get('fix_commit') != c.fix_sha or
            m['candidate_identity'].get('test_path') != c.test_path or
            m['candidate_identity'].get('baseline_commit') != c.parent_sha
            for m, c in zip(members, candidates)):
        raise ValueError('campaign_state_incompatible: monitor queue differs')
    by_oid = {m['organism_id']: (c.tool_path, c.fix_sha) for m, c in zip(members, candidates)}
    by_key = {(r['tool'], r['fix_sha']): r for r in payload.get('candidates', [])}
    if len(by_key) != len(payload.get('candidates', [])):
        raise ValueError('campaign_state_incompatible: duplicate queue keys')
    selected = set(by_oid.values())
    if [key for key in by_key if key in selected] != list(by_oid.values()):
        raise ValueError('campaign_state_incompatible: ordered queue population differs')
    for candidate in candidates:
        row = by_key[(candidate.tool_path, candidate.fix_sha)]
        expected = {'tool': candidate.tool_path, 'test': candidate.test_path,
            'fix_sha': candidate.fix_sha, 'parent_sha': candidate.parent_sha,
            'kind': candidate.kind, 'committed_at': candidate.committed_at, 'score': candidate.score}
        if not js.equivalent({key: row.get(key) for key in expected}, expected):
            raise ValueError('campaign_state_incompatible: queue row identity differs')
    for row in rows:
        data = row['payload']
        target = by_key.get(by_oid.get(data.get('organism_id')))
        if target is None:
            continue
        if row['kind'] == 'organism_completed':
            target['attempt'] = {'status': 'attempted', 'correct_seeds': sum(data['seeds']),
                'seeds': len(data['seeds']), 'deploy_reachable': data['deploy_reachable']}
        elif row['kind'] == 'organism_skipped':
            target['attempt'] = {'status': data['reason']}
        elif row['kind'] in ('seed_inconclusive', 'organism_inconclusive'):
            target['attempt'] = {'status': 'inconclusive', 'reason': data['reason']}
    if report is not None:
        payload['progress'] = report['progress']
        payload['cost_summary'] = report['cost_summary']
    else:
        payload['progress'] = {'campaign_id': rows[0]['campaign_id'],
                               'completed': any(row['kind'] == 'campaign_completed' for row in rows),
                               'last_record_hash': rows[-1]['record_hash']}
    if persist is not None:
        persist(payload)
