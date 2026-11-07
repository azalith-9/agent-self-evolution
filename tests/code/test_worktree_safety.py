"""Boundary regressions without creating a venv or executing repository code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from evolution.code.worktree import WorktreeEnv, WorktreeError


@pytest.fixture
def env(tmp_path: Path) -> WorktreeEnv:
    root = tmp_path / "run"
    worktree = root / "wt"
    worktree.mkdir(parents=True)
    return WorktreeEnv(tmp_path / "repo", root, worktree, root / "venv")


def test_repository_code_requires_containment_by_default(env: WorktreeEnv) -> None:
    assert env.require_sandbox is True


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("escape", ["parent", "absolute", "symlink"])
def test_tool_access_refuses_escape(env: WorktreeEnv, operation: str, escape: str) -> None:
    sentinel = env.worktree.parent / "sentinel"
    sentinel.write_text("original")
    (env.worktree / "link").symlink_to(sentinel)
    relative = {"parent": "../sentinel", "absolute": str(sentinel), "symlink": "link"}[escape]
    with pytest.raises((ValueError, WorktreeError)):
        if operation == "read":
            env.read_tool(relative)
        else:
            env.write_tool(relative, "changed")
    assert sentinel.read_text() == "original"


def test_authority_check_rejects_prefix_sibling(env: WorktreeEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, "confine", lambda argv: (argv, False))
    sibling = str(env.worktree) + "_other/tools/__init__.py"
    monkeypatch.setattr("evolution.code.worktree._run", Mock(return_value=
                        subprocess.CompletedProcess([], 0, json.dumps([sibling]), "")))
    with pytest.raises(WorktreeError, match="isolation"):
        env.assert_authoritative("tools")


def test_git_scope_failure_cannot_mean_no_changes(env: WorktreeEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evolution.code.worktree._run", Mock(return_value=
                        subprocess.CompletedProcess([], 128, "", "fatal: index unavailable")))
    with pytest.raises(WorktreeError):
        env.changed_files()


def test_test_environment_drops_ambient_credentials_and_injection(env: WorktreeEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"GH_TOKEN", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "SSH_AUTH_SOCK",
                 "PYTEST_ADDOPTS", "PYTHONSTARTUP", "LD_PRELOAD", "BASH_ENV"}
    for name in forbidden:
        monkeypatch.setenv(name, "synthetic-canary")
    monkeypatch.setenv("PYTHONPATH", "/synthetic/hostile")
    env._dep_sites = []
    child = env._test_env()
    leaked = sorted(forbidden.intersection(child))
    assert leaked == []
    assert "/synthetic/hostile" not in child.get("PYTHONPATH", "")
    assert Path(child["HOME"]).is_relative_to(env._root)


def test_import_time_ambient_credentials_do_not_enter_candidate_environment(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    script = '''import json
from pathlib import Path
from evolution.code.worktree import WorktreeEnv
root = Path.cwd()
env = WorktreeEnv(root, root, root, root / 'venv')
child = env._test_env()
print(json.dumps(sorted(set(child).intersection({'GH_TOKEN', 'OPENAI_API_KEY', 'AWS_SECRET_ACCESS_KEY'}))))
'''
    parent = {"PATH": os.defpath, "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
              "PYTHONPATH": str(root), "GH_TOKEN": "synthetic-gh-canary",
              "OPENAI_API_KEY": "synthetic-openai-canary", "AWS_SECRET_ACCESS_KEY": "synthetic-aws-canary",
              "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=parent,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_authority_import_uses_containment(env: WorktreeEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    confined = ["synthetic-sandbox", "python"]
    guard = Mock(return_value=(confined, True))
    monkeypatch.setattr(env, "confine", guard)
    monkeypatch.setattr(env, "_dep_sites", [], raising=False)
    launched = Mock(return_value=subprocess.CompletedProcess([], 0,
                    json.dumps([str(env.worktree / "tools/__init__.py")]), ""))
    monkeypatch.setattr("evolution.code.worktree._run", launched)
    env.assert_authoritative("tools")
    assert launched.call_args.args[0] == confined
