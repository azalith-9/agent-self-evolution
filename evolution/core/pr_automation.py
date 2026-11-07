"""Open a PR against the source repository after a successful evolve run.

GEPA writes evolved artifacts to ``output/.../evolved_skill.md`` (or the
tool equivalent). Promoting an evolution to the source repo is otherwise a
manual copy-branch-commit-push-PR dance; this helper collapses those steps
into one function.

Opt-in only: the CLI flag that wires this in defaults to ``False``. The
helper is intentionally artifact-agnostic — it takes a relative path and
content blob, not a skill/tool type discriminator.
"""

import os
import re
import secrets
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from rich.console import Console

_STDERR_TAIL_BYTES = 1024
_GIT_TIMEOUT_SECONDS = 60
_GH_TIMEOUT_SECONDS = 120
_BRANCH_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class PRResult:
    status: Literal["created", "skipped", "failed"]
    reason: str = ""
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    url: Optional[str] = None


def disabled_pr_block() -> dict[str, Any]:
    """The `pr_created` block written when `--create-pr` is off.

    Shape-stable with `pr_block_from_result` so downstream consumers can
    index ``payload["pr_created"]["url"]`` without checking the status.
    """
    return {"status": "disabled", "reason": None, "branch": None, "commit_sha": None, "url": None}


def pr_block_from_result(result: PRResult) -> dict[str, Any]:
    """Convert a `PRResult` into the `gate_decision.json::pr_created` block."""
    return {
        "status": result.status,
        "reason": result.reason,
        "branch": result.branch,
        "commit_sha": result.commit_sha,
        "url": result.url,
    }


def find_git_root(path: Path) -> Optional[Path]:
    """Return the git worktree root for ``path``, or ``None`` if not in a repo."""
    start = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _tail(text: Optional[str]) -> str:
    if not text:
        return ""
    return text[-_STDERR_TAIL_BYTES:]


@dataclass(frozen=True)
class GitResult:
    ok: bool
    stdout: str = ""
    error: str = ""


def _run_git(args: list[str], *, cwd: Path) -> GitResult:
    """Run checked Git administration and preserve a typed failure reason."""
    cmd_name = args[0] if args else "git"
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return GitResult(False, error=f"git {cmd_name} timed out after {_GIT_TIMEOUT_SECONDS}s")
    except OSError as exc:
        return GitResult(False, error=f"git {cmd_name} unavailable: {exc}")
    if result.returncode != 0:
        return GitResult(False, error=f"git {cmd_name} failed: {_tail(result.stderr)}")
    return GitResult(True, stdout=result.stdout)


def _branch_name(prefix: str, artifact_name: str, timestamp: datetime) -> str:
    sanitized = _BRANCH_SANITIZE_RE.sub("-", artifact_name).strip("-")
    ts = timestamp.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(2)
    return f"{prefix}{sanitized}-{ts}-{suffix}"


def _atomic_copy(src: Path, dst: Path) -> None:
    # tempfile + os.replace is atomic only when src and dst share a filesystem,
    # so the tempfile is created under dst.parent.
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, dir=str(dst.parent), prefix=".pr_atomic_"
        ) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(data)
        os.replace(tmp_path, dst)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _format_pr_body(gate_decision: dict[str, Any], metrics: dict[str, Any]) -> str:
    decision = gate_decision.get("decision", "unknown")
    signal = gate_decision.get("decision_signal", "synthetic")
    reason = gate_decision.get("reason", "")
    baseline = metrics.get("baseline_mean")
    evolved = metrics.get("evolved_mean")
    delta = metrics.get("delta")
    if delta is None and baseline is not None and evolved is not None:
        delta = evolved - baseline

    lines = [f"## Evolution decision: {decision}", ""]

    if signal == "closed_loop":
        gained = gate_decision.get("cl_tasks_gained")
        required = gate_decision.get("cl_required_gain")
        if gained is not None:
            headline = f"**Closed-loop tasks gained: +{gained}**"
            if required is not None:
                headline += f" (required ≥ {required})"
            lines += [headline, ""]
        lines += ["Decision signal: `closed_loop`", ""]
    else:
        lines += ["Decision signal: `synthetic`", ""]

    if reason:
        lines += [f"Reason: `{reason}`", ""]

    if baseline is not None and evolved is not None:
        sign = "+" if (delta or 0) >= 0 else ""
        lines += [
            "### Holdout score",
            f"- baseline: `{baseline:.2f}`",
            f"- evolved:  `{evolved:.2f}`",
            f"- delta:    `{sign}{delta:.2f}`",
            "",
        ]

    bootstrap = gate_decision.get("bootstrap")
    if isinstance(bootstrap, dict) and "ci_low" in bootstrap and "ci_high" in bootstrap:
        lines += [
            "### Bootstrap CI",
            f"- 95% CI: `[{bootstrap['ci_low']:.3f}, {bootstrap['ci_high']:.3f}]`",
            "",
        ]

    baseline_chars = gate_decision.get("baseline_chars")
    evolved_chars = gate_decision.get("evolved_chars")
    if baseline_chars is not None and evolved_chars is not None:
        size_delta = evolved_chars - baseline_chars
        lines += [
            "### Artifact size",
            f"- baseline: `{baseline_chars}` chars",
            f"- evolved:  `{evolved_chars}` chars (`{size_delta:+d}`)",
            "",
        ]

    cost_summary = gate_decision.get("cost_summary")
    if isinstance(cost_summary, dict) and "total_usd" in cost_summary:
        lines += ["### Cost", f"- total: `${cost_summary['total_usd']:.4f}`", ""]

    lines += [
        "---",
        "Generated by agent-self-evolution. Review and merge or close manually.",
    ]
    return "\n".join(lines)


def _commit_message(
    artifact_name: str, metrics: dict[str, Any], signal: str, gate_decision: dict[str, Any]
) -> str:
    if signal == "closed_loop":
        gained = gate_decision.get("cl_tasks_gained", 0)
        summary = f"CL tasks +{gained}"
    else:
        baseline = metrics.get("baseline_mean")
        evolved = metrics.get("evolved_mean")
        delta = metrics.get("delta")
        if delta is None and baseline is not None and evolved is not None:
            delta = evolved - baseline
        if baseline is not None and evolved is not None and delta is not None:
            summary = f"holdout {baseline:.2f}->{evolved:.2f} ({delta:+.2f})"
        else:
            summary = "deploy"
    return f"evolve({artifact_name}): {summary}"


def create_pr(
    *,
    source_repo_root: Optional[Path],
    source_artifact_relpath: str,
    evolved_artifact_path: Path,
    artifact_name: str,
    gate_decision: dict[str, Any],
    metrics: dict[str, Any],
    base_branch: str,
    branch_prefix: str,
    draft: bool,
    allow_dirty: bool,
    console: Console,
    labels: Optional[list[str]] = None,
    body_override: Optional[str] = None,
) -> PRResult:
    """Branch from ``origin/<base>``, copy the evolved artifact in, commit, push,
    and open a PR. ``body_override`` replaces the default GEPA-shaped body (used
    by code evolution to carry its own anti-gaming evidence); ``labels`` are
    passed through to ``gh pr create`` (e.g. a ``human-review`` label).
    """
    if source_repo_root is None:
        return PRResult(
            status="skipped",
            reason="source repo not git-backed (e.g., Claude Code plugin cache)",
        )

    relative = Path(source_artifact_relpath)
    source_repo_root = Path(source_repo_root).resolve()
    if (not source_artifact_relpath or relative.is_absolute() or ".." in relative.parts
            or not (source_repo_root / relative).resolve().is_relative_to(source_repo_root)):
        return PRResult(status="failed", reason="artifact destination must remain inside the source repository")

    result = _run_git(["status", "--porcelain"], cwd=source_repo_root)
    if not result.ok:
        return PRResult(status="failed", reason=result.error)
    if result.stdout.strip() and not allow_dirty:
        console.print("[yellow]Dirty working tree detected:[/yellow]")
        console.print(result.stdout.rstrip())
        return PRResult(status="skipped", reason="dirty working tree (pass --pr-allow-dirty to override)")
    result = _run_git(["fetch", "origin", base_branch], cwd=source_repo_root)
    if not result.ok:
        return PRResult(status="failed", reason=result.error)

    branch = _branch_name(branch_prefix, artifact_name, datetime.now(timezone.utc))
    with tempfile.TemporaryDirectory(prefix="evolution_pr_") as tmp:
        worktree = Path(tmp) / "checkout"
        result = _run_git(
            ["worktree", "add", "-b", branch, str(worktree), f"origin/{base_branch}"],
            cwd=source_repo_root,
        )
        if not result.ok:
            return PRResult(status="failed", reason=result.error, branch=branch)
        outcome = PRResult(status="failed", reason="PR preparation did not complete", branch=branch)
        try:
            outcome = _prepare_pr_worktree(
                worktree=worktree, relative=source_artifact_relpath,
                evolved_artifact_path=evolved_artifact_path, artifact_name=artifact_name,
                gate_decision=gate_decision, metrics=metrics, base_branch=base_branch,
                branch=branch, draft=draft, labels=labels, body_override=body_override,
            )
        finally:
            cleanup = _run_git(["worktree", "remove", "--force", str(worktree)], cwd=source_repo_root)
            if not cleanup.ok:
                outcome = PRResult(status="failed", reason=f"{outcome.reason}; worktree cleanup failed: {cleanup.error}",
                                   branch=branch, commit_sha=outcome.commit_sha, url=outcome.url)
        return outcome


def _prepare_pr_worktree(
    *, worktree: Path, relative: str, evolved_artifact_path: Path, artifact_name: str,
    gate_decision: dict[str, Any], metrics: dict[str, Any], base_branch: str,
    branch: str, draft: bool, labels: Optional[list[str]], body_override: Optional[str],
) -> PRResult:
    from evolution.core.paths import write_contained

    try:
        write_contained(worktree, relative, evolved_artifact_path.read_bytes())
    except (OSError, ValueError) as exc:
        return PRResult(status="failed", reason=f"atomic copy failed: {exc}", branch=branch)
    signal = gate_decision.get("decision_signal", "synthetic")
    message = _commit_message(artifact_name, metrics, signal, gate_decision)
    for args in (["add", "--", relative], ["commit", "-m", message]):
        result = _run_git(args, cwd=worktree)
        if not result.ok:
            return PRResult(status="failed", reason=result.error, branch=branch)
    result = _run_git(["rev-parse", "HEAD"], cwd=worktree)
    if not result.ok or not result.stdout.strip():
        return PRResult(status="failed", reason=result.error or "missing committed HEAD", branch=branch)
    commit_sha = result.stdout.strip()
    result = _run_git(["push", "origin", branch], cwd=worktree)
    if not result.ok:
        return PRResult(status="failed", reason=result.error, branch=branch, commit_sha=commit_sha)
    body = body_override if body_override is not None else _format_pr_body(gate_decision, metrics)
    body_path = worktree.parent / "pr-body.md"
    try:
        body_path.write_text(body, encoding="utf-8")
        gh_args = ["gh", "pr", "create", "--base", base_branch, "--head", branch,
                   "--title", message, "--body-file", str(body_path)]
        if draft:
            gh_args.append("--draft")
        for label in labels or []:
            gh_args += ["--label", label]
        gh_res = subprocess.run(gh_args, cwd=str(worktree), capture_output=True, text=True,
                                timeout=_GH_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return PRResult(status="failed", reason=f"gh pr create failed: {exc}", branch=branch, commit_sha=commit_sha)
    finally:
        body_path.unlink(missing_ok=True)
    if gh_res.returncode != 0:
        return PRResult(status="failed", reason=f"gh pr create failed: {_tail(gh_res.stderr)}",
                        branch=branch, commit_sha=commit_sha)
    url = gh_res.stdout.strip().splitlines()[-1] if gh_res.stdout.strip() else ""
    if not url:
        return PRResult(status="failed", reason="gh pr create returned no URL", branch=branch, commit_sha=commit_sha)
    return PRResult(status="created", branch=branch, commit_sha=commit_sha, url=url)
