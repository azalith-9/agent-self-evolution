"""Isolated worktree + venv harness for code evolution.

A code repair must be measured against the *repaired* code and nothing else.
Two failure modes make that harder than it looks, and this module exists to
foreclose both:

1. **Never touch the user's checkout.** Repairs happen in a throwaway ``git
   worktree`` of the target repo, created from a base ref. The user's working
   copy is never written to.

2. **Never measure a Frankenstein import.** The target repo (Hermes) is
   installed *editable*: its import finder hardcodes a package→original-path
   map. Putting the worktree on ``PYTHONPATH`` is not enough — submodule
   resolution can still fall through to the original tree, so the loop would
   score a mix of repaired and original code. The robust fix is to make the
   worktree *authoritative*: a dedicated venv with ``pip install -e <worktree>``
   so the editable finder points at the worktree. ``--system-site-packages
   --no-deps`` keeps that install cheap by inheriting the user's already-built
   dependencies instead of reinstalling them.

   Because that mechanism has version- and ordering-dependent edge cases, it is
   never *trusted* — :meth:`WorktreeEnv.assert_authoritative` empirically
   confirms that the ``tools`` package resolves from inside the worktree before
   any verdict is believed, and aborts loudly otherwise. Once the ``tools``
   package object resolves to the worktree, every ``tools.X`` submodule import
   searches ``tools.__path__`` in the worktree — and a repair only ever mutates
   one ``tools/`` file — so that single check is sufficient for the repair's
   blast radius.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from rich.console import Console

from evolution.core.execution import ExecutionPolicy, ExecutionRequest
from evolution.core.process import run_process
from evolution.core.paths import read_contained, write_contained
from evolution.code.test_evidence import read_test_evidence

from evolution.core.sandbox import (
    SandboxUnavailableError,
    sandbox_available,
    runtime_read_roots,
    wrap_argv,
)

# Repairs write whole files in a tight loop; consecutive rounds can produce
# same-size sources within the filesystem's mtime resolution, which defeats
# CPython's (mtime, size) .pyc invalidation and silently runs stale bytecode.
# Disabling bytecode writes forces recompilation from source every run — and
# keeps __pycache__ out of the worktree so it never dirties git status.
logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 120
_VENV_TIMEOUT = 600
_DEFAULT_TEST_TIMEOUT = 600


class WorktreeError(RuntimeError):
    """Raised when worktree/venv setup fails or the authoritative-import guard
    trips. A BaseException-like hard stop in spirit: callers must not proceed to
    score a repair against a non-isolated environment."""


@dataclass
class TestRun:
    """Outcome of one pytest invocation inside the worktree venv.

    ``exit_code`` is pytest's raw exit status (None on timeout): 0 = all passed,
    1 = tests failed, 5 = no tests collected, 2/3/4 = interrupted/internal/usage
    error. Callers distinguish "ran and failed" (a real bug to repair) from "did
    not run cleanly" (a misconfiguration that must not look like a fail-or-pass).
    """

    passed: bool
    output: str  # combined stdout+stderr tail
    duration_seconds: float
    exit_code: int | None = None
    evidence_complete: bool | None = None
    cleanup_complete: bool | None = None
    failures: frozenset[str] | None = None
    invocation_id: str | None = None

    selected: frozenset[str] = frozenset()
    skipped: frozenset[str] = frozenset()
    missing: frozenset[str] = frozenset()
    trusted_inputs_id: str | None = None
    unexecuted: frozenset[str] = frozenset()

    @property
    def diagnostic_complete(self) -> bool:
        return (self.evidence_complete is True and self.cleanup_complete is True
                and type(self.exit_code) is int and self.exit_code in (0, 1) and self.failures is not None
                and bool(self.invocation_id)
                and self.passed == (self.exit_code == 0)
                and bool(self.failures) == (self.exit_code == 1) and not self.unexecuted)

    @property
    def authoritative(self) -> bool:
        """Compatibility alias for diagnostic completeness, never deployment authority."""
        return self.diagnostic_complete


def _run(
    args: list[str], *, cwd: Path, timeout: int, env: dict | None = None
) -> subprocess.CompletedProcess[str]:
    child_env = env if env is not None else {
        "PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0", "PYTHONDONTWRITEBYTECODE": "1",
    }
    request = ExecutionRequest(
        argv=args, cwd=cwd.resolve(), env=child_env,
        policy=ExecutionPolicy(read_roots=(), write_roots=(), required=False),
        timeout_seconds=timeout, cleanup_timeout_seconds=2,
        invocation_id=child_env.get("ASE_EXECUTION_ID", uuid.uuid4().hex),
    )
    result = run_process(request)
    if result.timed_out:
        raise subprocess.TimeoutExpired(args, timeout, result.stdout, result.stderr)
    if result.exit_code is None:
        raise WorktreeError(f"process launch failed: {result.error}")
    if not result.cleanup_complete:
        raise WorktreeError(f"process cleanup could not be verified: {result.error}")
    completed = subprocess.CompletedProcess(args, result.exit_code, result.stdout, result.stderr)
    completed.cleanup_complete = result.cleanup_complete
    completed.invocation_id = result.invocation_id
    return completed



def prune_orphan_worktrees(repo_root: Path) -> int:
    """Remove only worktrees with a verifiably dead recorded owner.

    Unknown ownership is retained: a name prefix cannot distinguish a live
    concurrent repair from an orphan.
    """
    removed = 0
    res = _run(["git", "worktree", "list", "--porcelain"], cwd=repo_root, timeout=_GIT_TIMEOUT)
    for line in res.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        wt = Path(line[len("worktree "):].strip())
        root = wt.parent
        if root.name.startswith("evolve_code_") and wt.name == "wt":
            try:
                owner = json.loads((root / "owner.json").read_text())
                pid = owner["pid"]
                if type(pid) is not int or pid < 1:
                    continue
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            except (OSError, ValueError, KeyError, TypeError):
                continue
            else:
                continue
            _run(["git", "worktree", "remove", "--force", str(wt)],
                 cwd=repo_root, timeout=_GIT_TIMEOUT)
            shutil.rmtree(root, ignore_errors=True)
            removed += 1
    _run(["git", "worktree", "prune"], cwd=repo_root, timeout=_GIT_TIMEOUT)
    return removed


def _detect_base_python(repo_root: Path) -> str:
    """The interpreter whose environment has the target repo's deps installed.

    Prefers the repo's own ``venv``/``.venv`` (where an editable Hermes install
    and all its dependencies live); falls back to the current interpreter for
    dependency-free targets (e.g. the synthetic test repo)."""
    for cand in (
        repo_root / "venv" / "bin" / "python",
        repo_root / ".venv" / "bin" / "python",
    ):
        if cand.exists():
            return str(cand)
    return sys.executable


# pytest's own exit codes. A *positive* code above this range from a confined run
# means the sandbox, not pytest, decided the outcome. Negative codes are signal
# deaths (OOM kill, SIGSEGV) — those are real test-run outcomes, and calling them
# containment failures would misdiagnose them and, worse, drop the organism from
# the campaign denominator on macOS only.
_PYTEST_EXIT_CODES = frozenset(range(6))
console = Console()


class NonAuthoritativeRunError(WorktreeError):
    """A pytest run that cannot answer "what failed?".

    Distinct so callers can classify it honestly: an inconclusive run is not a
    worktree setup problem, and recording it as one would put the wrong cause in
    the campaign ledger for a candidate that simply could not be measured.
    """


class ContainmentError(WorktreeError):
    """The OS sandbox, not the test run, determined the outcome.

    Distinct from :class:`WorktreeError` so a caller whose handler turns worktree
    trouble into a skipped item cannot quietly absorb a systemic containment
    failure as one more skip.
    """


class WorktreeEnv:
    """A disposable git worktree of ``repo_root`` with its own editable venv.

    Lifecycle: :meth:`create` → :meth:`assert_authoritative` →
    (:meth:`write_tool` / :meth:`run_test`)* → :meth:`destroy`. Use as a context
    manager to guarantee cleanup. ``create`` builds the worktree and venv;
    nothing is trusted until ``assert_authoritative`` passes.
    """

    def __init__(
        self, repo_root: Path, root: Path, worktree: Path, venv: Path,
        *, require_sandbox: bool = True,
    ):
        self.repo_root = repo_root
        self._root = root  # the run tempdir holding both worktree and venv
        self.worktree = worktree
        self.venv = venv
        self.require_sandbox = require_sandbox
        self.sandboxed = sandbox_available()
        self._output_tail_bytes = 6000
        self._base_python = sys.executable
        self._dep_sites: list[str] = []
        self._git_pointer: bytes | None = None

    # -- construction ------------------------------------------------------

    @classmethod
    def create(
        cls,
        repo_root: Path,
        *,
        base_ref: str,
        base_python: str | None = None,
        output_tail_bytes: int = 6000,
        require_sandbox: bool = True,
    ) -> "WorktreeEnv":
        """Add a detached worktree at ``base_ref`` and build its isolated venv.

        The venv lives *beside* the worktree (not inside it) so the worktree's
        ``git status`` stays clean except for the repair — which keeps the PR
        diff to exactly the repaired file. ``base_python`` is the interpreter the
        venv is based on; it must be the environment that already has the target
        repo's dependencies (so the regression floor can import them). Defaults
        to the repo's own ``venv``/``.venv``, else the current interpreter.
        """
        root = Path(tempfile.mkdtemp(prefix="evolve_code_"))
        (root / "owner.json").write_text(json.dumps({"pid": os.getpid()}))
        worktree = root / "wt"
        venv = root / "venv"
        env = cls(repo_root, root, worktree, venv, require_sandbox=require_sandbox)
        env._output_tail_bytes = output_tail_bytes
        env._base_python = base_python or _detect_base_python(repo_root)
        try:
            # Inside the cleanup guard: a refusal or a broken profile would
            # otherwise leak the mkdtemp root — one per attempt.
            env._assert_sandbox_usable()
            env._add_worktree(base_ref)
            env._build_venv()
        except BaseException:
            env.destroy()
            raise
        return env

    def _add_worktree(self, base_ref: str) -> None:
        res = _run(
            ["git", "worktree", "add", "--no-checkout", "--detach", str(self.worktree), base_ref],
            cwd=self.repo_root,
            timeout=_GIT_TIMEOUT,
        )
        if res.returncode != 0:
            raise WorktreeError(
                f"git worktree add failed (base_ref={base_ref!r}): {res.stderr.strip()}"
            )
        config = _run(["git", "config", "--get-regexp", r"^(filter\..*\.(process|smudge|clean)|core\.fsmonitor)$"],
                      cwd=self.repo_root, timeout=_GIT_TIMEOUT)
        if config.returncode not in (0, 1):
            raise WorktreeError("could not inspect executable Git filter configuration")
        if config.stdout.strip():
            raise WorktreeError("repository Git filters require a separately contained checkout")
        checkout = _run(["git", "read-tree", "--reset", "-u", "HEAD"],
                        cwd=self.worktree, timeout=_GIT_TIMEOUT)
        if checkout.returncode:
            raise WorktreeError(f"could not populate worktree: {checkout.stderr.strip()}")
        self._git_pointer = read_contained(self.worktree, ".git")

    def _build_venv(self) -> None:
        # A *clean* venv (no --system-site-packages): the base interpreter is
        # often itself a venv symlinked to a bare base, so --system-site-packages
        # would chain to the base and miss the deps we need. Instead, the
        # worktree's own editable install maps every Hermes package to the
        # worktree, and the base venv's site-packages is added via PYTHONPATH at
        # test time (see _test_env) — that exposes the third-party dependencies
        # *without* executing the base's editable .pth, so the original Hermes
        # finder is never installed and there is no competing `tools` import.
        # Offline setup requires the build backend to be preinstalled; dependency
        # retrieval is a separate trusted preparation step.
        argv, _ = self.confine([self._base_python, "-m", "venv", str(self.venv)])
        res = _run(
            argv,
            cwd=self._root,
            timeout=_VENV_TIMEOUT,
        )
        if res.returncode != 0:
            raise WorktreeError(f"venv creation failed: {res.stderr.strip()}")
        self._dep_sites = self._query_dep_sites()
        argv, _ = self.confine(
            [str(self.python), "-m", "pip", "install", "-e", str(self.worktree),
             "--no-deps", "--no-build-isolation", "--no-index", "-q"])
        res = _run(
            argv,
            cwd=self.worktree,
            timeout=_VENV_TIMEOUT,
            env=self._test_env(),
        )
        if res.returncode != 0:
            raise WorktreeError(
                f"editable install failed: {(res.stderr or res.stdout).strip()[-1500:]}"
            )
        self._dep_sites = self._query_dep_sites()

    def _query_dep_sites(self) -> list[str]:
        """The base interpreter's site-packages dirs, where the target repo's
        third-party deps live. Added to PYTHONPATH at test time so imports
        resolve, without running that environment's .pth files."""
        probe = "import site, json; print(json.dumps(site.getsitepackages()))"
        argv, _ = self.confine([self._base_python, "-c", probe])
        res = _run(argv, cwd=self._root, timeout=60, env=self._test_env())
        if res.returncode != 0:
            return []
        try:
            return [p for p in json.loads(res.stdout.strip() or "[]") if Path(p).is_dir()]
        except ValueError:
            return []

    def _assert_sandbox_usable(self) -> None:
        """Fail construction whenever confinement is claimed but will not start.

        Note the condition: this fires when the OS *reports* confinement is
        available and the profile nonetheless refuses to compile — never silently
        downgrading to unconfined once we have claimed sandboxing works. Compiling
        once here turns that into an immediate error instead of a per-test surprise
        mid-run.
        """
        if not self.sandboxed:
            if self.require_sandbox:
                raise SandboxUnavailableError(
                    "confinement was required but is unavailable on this machine"
                )
            console.print(
                "  [yellow]⚠ tests will run unconfined[/yellow] — no OS filesystem "
                "sandbox here; the posture is recorded in this run's evidence"
            )
            return
        argv, _ = self.confine(["/usr/bin/true"])
        try:
            res = _run(argv, cwd=self._root, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as exc:
            # ContainmentError, not a bare TimeoutExpired: no caller anticipates
            # that type, so it would abort a whole campaign instead of failing
            # this one worktree.
            raise ContainmentError(f"OS sandbox probe failed to run: {exc}") from exc
        if res.returncode != 0:
            raise ContainmentError(
                "OS sandbox profile failed to start: "
                f"{(res.stderr or res.stdout or '').strip()[-300:]}"
            )

    def confine(self, argv: list[str]) -> tuple[list[str], bool]:
        """Wrap ``argv`` in this env's confinement policy.

        The seam every in-worktree execution should go through. Anything that runs
        candidate code but builds its own subprocess call bypasses the policy
        silently — the flag would then promise a guarantee that path does not
        provide.
        """
        read_roots = [*runtime_read_roots(), self._root.resolve(), Path(sys.base_prefix).resolve(),
                      Path(self._base_python).resolve().parent.parent,
                      Path(__file__).resolve().parent,
                      *[Path(path).resolve() for path in self._dep_sites]]
        write_roots = [self._root.resolve()]
        if self.worktree.exists():
            write_roots.append(self.worktree.resolve())
        return wrap_argv(
            argv, write_roots=write_roots, read_roots=read_roots,
            network="deny", require=self.require_sandbox, available=self.sandboxed,
        )

    def containment(self) -> dict:
        """How confined this run's test execution actually is.

        Recorded in run evidence so an unconfined run is visible rather than
        assumed. Note what the confined case does and does not mean: writes
        outside the run root and the temp roots are denied; reads, process-exec
        and network are not. It prevents corrupting the checkout or home dir --
        it is not isolation.
        """
        return {
            "sandboxed": self.sandboxed,
            "mechanism": (("bubblewrap" if sys.platform.startswith("linux") else "sandbox-exec")
                          if self.sandboxed else None),
            "network": "deny" if self.sandboxed else "unrestricted",
            "platform": sys.platform,
        }

    def _test_env(self) -> dict:
        """Env for in-worktree python runs: no bytecode writes, plus the base
        interpreter's site-packages on PYTHONPATH for third-party deps."""
        home = self._root / "home"
        temporary = self._root / "tmp"
        for directory in (home, temporary):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        env = {"PATH": os.defpath, "HOME": str(home), "TMPDIR": str(temporary),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PIP_NO_INDEX": "1"}
        if self._dep_sites:
            env["PYTHONPATH"] = os.pathsep.join(self._dep_sites)
        return env

    # -- properties --------------------------------------------------------

    @property
    def python(self) -> Path:
        return self.venv / "bin" / "python"

    # -- the authoritative-import guard -----------------------------------

    def assert_authoritative(self, package: str) -> None:
        """Confirm ``package`` resolves *entirely* from inside the worktree, else
        abort. ``package`` must be the top-level package that contains the file
        being repaired — guarding a sibling package proves nothing about the code
        actually under test.

        The load-bearing safety net for the venv mechanism: if the user's
        original install won the import race for any reason, the loop would score
        original code and silently certify nonsense. We never want a verdict from
        a non-isolated import, so a failed check is a hard stop. Every entry of
        the package's ``__file__``/``__path__`` must be under the worktree (a
        namespace package can list several roots; one outside is a breach).
        """
        probe = (
            f"import {package} as _m, os, sys, json\n"
            f"paths = [getattr(_m, '__file__', None)] + list(getattr(_m, '__path__', []))\n"
            f"sys.stdout.write(json.dumps([os.path.realpath(p) for p in paths if p]))\n"
        )
        if not package.isidentifier():
            raise WorktreeError("authority package must be a top-level Python identifier")
        argv, _ = self.confine([str(self.python), "-c", probe])
        res = _run(argv, cwd=self.worktree, timeout=60, env=self._test_env())
        if res.returncode != 0:
            raise WorktreeError(
                f"could not import '{package}' in the isolated venv: {res.stderr.strip()}"
            )
        try:
            resolved = json.loads(res.stdout.strip() or "[]")
        except ValueError:
            resolved = []
        wt_real = str(Path(self.worktree).resolve())
        outside = [p for p in resolved if not isinstance(p, str)
                   or not Path(p).resolve().is_relative_to(Path(wt_real))]
        if not resolved or outside:
            raise WorktreeError(
                f"isolation breach: '{package}' resolved to {resolved!r} "
                f"(outside the worktree {wt_real!r}: {outside or 'nothing resolved'}). "
                f"Refusing to score a Frankenstein import (mixed repaired/original code)."
            )

    # -- mutation + measurement -------------------------------------------

    def read_tool(self, relpath: str) -> str:
        return read_contained(self.worktree, relpath).decode("utf-8")

    def write_tool(self, relpath: str, src: str) -> None:
        """Write ``src`` to ``relpath`` in the worktree. Only tool source is
        ever written by the loop; test files are read-only (the gate verifies
        the test split was untouched against the worktree's git diff)."""
        write_contained(self.worktree, relpath, src.encode("utf-8"))

    def assert_git_metadata(self) -> None:
        """Refuse candidate replacement of the worktree administration pointer."""
        if self._git_pointer is not None:
            try:
                current = read_contained(self.worktree, ".git")
            except (OSError, ValueError) as exc:
                raise WorktreeError("worktree Git administration pointer is unavailable") from exc
            if current != self._git_pointer:
                raise WorktreeError("worktree Git administration pointer changed")

    def diff(self) -> str:
        """The worktree's working-tree diff against its base (what a PR ships)."""
        self.assert_git_metadata()
        res = _run(["git", "diff", "--no-ext-diff", "--no-textconv"],
                   cwd=self.worktree, timeout=_GIT_TIMEOUT)
        if res.returncode != 0:
            raise WorktreeError(f"git diff failed: {res.stderr.strip()}")
        return res.stdout

    def changed_files(self) -> list[str]:
        """Repo-relative *source* paths with a working-tree change (tracked or
        not). Build artifacts (``__pycache__``/``.pyc``/the egg-info the editable
        install drops) are not source changes and are filtered out so the gate's
        file-scope check sees only what a PR would actually ship."""
        self.assert_git_metadata()
        res = _run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=self.worktree, timeout=_GIT_TIMEOUT,
        )
        if res.returncode != 0:
            raise WorktreeError(f"git scope inspection failed: {res.stderr.strip()}")
        fields = iter(res.stdout.split("\0"))
        out: list[str] = []
        for field in fields:
            if not field:
                continue
            if len(field) < 4 or field[2] != " ":
                raise WorktreeError("malformed NUL-delimited git status")
            paths = [field[3:]]
            if "R" in field[:2] or "C" in field[:2]:
                source = next(fields, None)
                if not source:
                    raise WorktreeError("missing rename source in git status")
                paths.append(source)
            out.extend(path for path in paths if "__pycache__" not in Path(path).parts
                       and not path.endswith((".pyc", ".egg-info", ".egg-link")))
        return out

    def run_test(
        self, *test_paths: str, timeout: int = _DEFAULT_TEST_TIMEOUT,
        extra_args: list[str] | None = None, full_output: bool = False,
    ) -> TestRun:
        """Run pytest on ``test_paths`` with the worktree venv, cwd=worktree.

        ``-p no:cacheprovider`` keeps the worktree free of a ``.pytest_cache``
        that would dirty its git status. ``full_output`` keeps the entire
        combined output instead of a tail — needed when the caller must parse the
        complete set of failing test ids (e.g. the baseline-diff regression floor),
        which a tail could truncate.
        """
        invocation_id = uuid.uuid4().hex
        evidence_dir = self._root / "evidence"
        evidence_dir.mkdir(mode=0o700, exist_ok=True)
        evidence_path = evidence_dir / f"{invocation_id}.json"
        plugin = str(Path(__file__).resolve().parent)
        child_env = self._test_env()
        child_env["ASE_EXECUTION_ID"] = invocation_id
        child_env["PYTHONPATH"] = os.pathsep.join(
            [plugin, *self._dep_sites])
        args = [
            str(self.python), "-m", "pytest", "-q", "--no-header",
            "-p", "no:cacheprovider", "-p", "pytest_evidence_plugin",
            "--evidence-path", str(evidence_path),
            "--evidence-invocation-id", invocation_id, *(extra_args or []), *test_paths,
        ]
        argv, sandboxed = self.confine(args)
        start = time.monotonic()
        try:
            res = _run(argv, cwd=self.worktree, timeout=timeout, env=child_env)
            duration = time.monotonic() - start
            if sandboxed and res.returncode > 5:
                # sandbox-exec exits 65 without running the child when a profile
                # fails to compile. The gate special-cases only exit 5 and its
                # failure parser yields an empty set on unrecognised output, so a
                # run where nothing executed would read as "no failures" and could
                # be certified correct. Refuse to return it as a test result.
                detail = (res.stderr or res.stdout or "").strip()[-500:]
                raise ContainmentError(
                    f"sandboxed pytest exited {res.returncode}, which is not a pytest "
                    f"outcome — the sandbox decided this, not the tests: {detail}"
                )
            combined = res.stdout + "\n" + res.stderr
            out = combined if full_output else combined[-self._output_tail_bytes:]
            cleanup_complete = (getattr(res, "cleanup_complete", False)
                                and getattr(res, "invocation_id", None) == invocation_id)
            evidence = read_test_evidence(evidence_path, invocation_id=invocation_id,
                                          exit_code=res.returncode,
                                          cleanup_complete=cleanup_complete,
                                          required_nodeids=tuple(p for p in test_paths if "::" in p))
            return TestRun(passed=res.returncode == 0 and evidence.complete and not evidence.missing, output=out,
                           duration_seconds=duration, exit_code=res.returncode,
                           evidence_complete=evidence.complete,
                           cleanup_complete=cleanup_complete, failures=evidence.failures,
                           invocation_id=invocation_id, selected=evidence.selected,
                           skipped=evidence.skipped, missing=evidence.missing, unexecuted=evidence.unexecuted,
                           trusted_inputs_id=WorktreeEnv._diagnostic_inputs_id(self, test_paths, extra_args))
        except subprocess.TimeoutExpired as exc:
            # Keep what pytest managed to print. The last test it named before
            # hanging is the diagnostic someone chasing an introduced infinite
            # loop actually needs, and it is otherwise discarded.
            partial = "".join(
                part.decode(errors="replace") if isinstance(part, bytes) else (part or "")
                for part in (exc.stdout, exc.stderr)
            ).strip()
            note = f"pytest timed out after {timeout}s"
            # Honour full_output here too. A caller that asked for the complete
            # summary needs it even from a timeout: a run that hung *after*
            # printing its failures would otherwise return a truncated subset,
            # and a smaller failure set biases the diff toward "no new failures".
            kept = partial if full_output else partial[-self._output_tail_bytes:]
            return TestRun(
                passed=False,
                output=f"{note}\n{kept}" if partial else note,
                duration_seconds=float(timeout),
                exit_code=None,
            )

    def _diagnostic_inputs_id(self, test_paths: tuple[str, ...], extra_args: list[str] | None) -> str:
        """Fingerprint diagnostic selection and test bytes; this is not protection."""
        import hashlib

        digest = hashlib.sha256(repr((test_paths, extra_args)).encode())
        for path in sorted(self.worktree.rglob("*.py")):
            if "tests" in path.relative_to(self.worktree).parts or path.name == "conftest.py":
                digest.update(str(path.relative_to(self.worktree)).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def failing_tests(self, *test_paths: str, timeout: int = _DEFAULT_TEST_TIMEOUT) -> set[str]:
        """Return complete invocation-bound failures, or refuse an inconclusive run."""
        run = self.run_test(*test_paths, extra_args=["--tb=no"], full_output=True, timeout=timeout)
        if run.diagnostic_complete:
            return set(run.failures)
        raise NonAuthoritativeRunError(
            f"pytest on {list(test_paths)} exited {run.exit_code} and established nothing "
            f"without complete execution evidence: {run.output[-500:]}"
        )

    # -- teardown ----------------------------------------------------------

    def destroy(self) -> None:
        """Remove the worktree (best-effort) and the whole run tempdir."""
        try:
            _run(
                ["git", "worktree", "remove", "--force", str(self.worktree)],
                cwd=self.repo_root,
                timeout=_GIT_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass  # best-effort; the tempdir removal below is the real cleanup
        shutil.rmtree(self._root, ignore_errors=True)
        # Prune the now-dangling worktree registration from the source repo.
        try:
            _run(["git", "worktree", "prune"], cwd=self.repo_root, timeout=_GIT_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def __enter__(self) -> "WorktreeEnv":
        return self

    def __exit__(self, *exc: object) -> None:
        self.destroy()
