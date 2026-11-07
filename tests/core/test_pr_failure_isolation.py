"""PR preparation failures must not change the caller's branch, index or files.

All Git and GitHub operations are mocked at subprocess.run. These tests never
push, create a PR, execute a hook, or mutate this repository's index.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from evolution.core.pr_automation import _atomic_copy, create_pr


def _create(root: Path, artifact: Path, relative: str = "skills/demo/SKILL.md") -> object:
    return create_pr(source_repo_root=root, source_artifact_relpath=relative,
                     evolved_artifact_path=artifact, artifact_name="demo",
                     gate_decision={"decision": "deploy"}, metrics={}, base_branch="main",
                     branch_prefix="evolve/", draft=True, allow_dirty=True, console=Console())


@pytest.mark.parametrize("failure", ["copy", "commit", "push", "gh"])
def test_failed_preparation_preserves_caller_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    root = tmp_path / "caller"
    root.mkdir()
    artifact = tmp_path / "evolved.md"
    artifact.write_text("evolved")
    original = root / "skills/demo/SKILL.md"
    original.parent.mkdir(parents=True)
    original.write_text("original")
    commands = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        cwd = Path(kwargs["cwd"])
        commands.append((argv, cwd))
        if argv[:3] == ["git", "worktree", "add"]:
            # The disposable worktree is simulated; no git mutation occurs.
            dest = Path(argv[-2] if argv[-1].startswith("origin/") else argv[-1])
            dest.mkdir(parents=True, exist_ok=True)
        if (argv[0] == "gh" and failure == "gh") or (len(argv) > 1 and argv[1] == failure):
            return subprocess.CompletedProcess(argv, 1, "", "synthetic failure")
        return subprocess.CompletedProcess(argv, 0, "" if "status" in argv else "abc\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    if failure == "copy":
        def fail_replace(*args: object, **kwargs: object) -> None:
            raise PermissionError("synthetic copy refusal")
        monkeypatch.setattr("os.replace", fail_replace)
    result = _create(root, artifact)
    assert result.status == "failed"
    mutations = {"checkout", "switch", "add", "commit", "reset", "read-tree"}
    caller_mutations = [argv for argv, cwd in commands
                        if cwd == root and len(argv) > 1 and argv[0] == "git" and argv[1] in mutations]
    assert caller_mutations == []
    assert original.read_text() == "original"
    assert not list(root.rglob(".pr_atomic_*"))


def test_atomic_copy_removes_tempfile_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src, dst = tmp_path / "source", tmp_path / "destination"
    src.write_bytes(b"changed")
    dst.write_bytes(b"original")

    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError("synthetic replace failure")

    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(PermissionError):
        _atomic_copy(src, dst)
    assert dst.read_bytes() == b"original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["destination", "source"]


@pytest.mark.parametrize("relative", ["../escape", "/tmp/absolute-artifact"])
def test_pr_artifact_destination_rejects_escape_before_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str) -> None:
    artifact = tmp_path / "evolved.md"
    artifact.write_text("evolved")
    calls = []

    def no_git(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "unexpected git")

    monkeypatch.setattr(subprocess, "run", no_git)
    result = _create(tmp_path, artifact, relative)
    assert result.status == "failed"
    assert calls == []
