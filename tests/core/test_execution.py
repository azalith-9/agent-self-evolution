"""Internal execution contracts specified before the shared runner is built.

Environment construction accepts explicit parent input and never copies it wholesale.
Requests snapshot argv, roots and environment at construction, before capability checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_candidate_environment_is_fresh_and_allowlisted(tmp_path: Path) -> None:
    from evolution.core.execution import prepare_environment

    parent = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GH_TOKEN": "synthetic-gh",
              "OPENAI_API_KEY": "synthetic-provider", "SSH_AUTH_SOCK": "/host/socket",
              "LD_PRELOAD": "/host/injection.so", "PYTHONPATH": "/host/modules",
              "PYTEST_ADDOPTS": "--no-summary", "BASH_ENV": "/host/bashrc"}
    child = prepare_environment(kind="candidate", parent=parent, home=tmp_path / "home",
                                tmpdir=tmp_path / "tmp")
    assert dict(child) == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                           "HOME": str(tmp_path / "home"), "TMPDIR": str(tmp_path / "tmp"),
                           "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def test_agent_receives_only_selected_credential(tmp_path: Path) -> None:
    from evolution.core.execution import prepare_environment

    child = prepare_environment(kind="agent", parent={"PATH": "/bin", "GH_TOKEN": "gh",
                                 "OPENAI_API_KEY": "openai", "CLAUDE_CODE_OAUTH_TOKEN": "claude"},
                                home=tmp_path / "home", tmpdir=tmp_path / "tmp",
                                credential_name="CLAUDE_CODE_OAUTH_TOKEN")
    assert child["CLAUDE_CODE_OAUTH_TOKEN"] == "claude"
    assert set(child).isdisjoint({"GH_TOKEN", "OPENAI_API_KEY"})


@pytest.mark.parametrize("name", ["HOME", "TMPDIR", "LD_PRELOAD", "PYTHONPATH", "GH_TOKEN"])
def test_extra_environment_cannot_override_policy(tmp_path: Path, name: str) -> None:
    from evolution.core.execution import prepare_environment

    with pytest.raises(ValueError):
        prepare_environment(kind="candidate", parent={"PATH": "/bin"},
                            home=tmp_path / "home", tmpdir=tmp_path / "tmp",
                            extra_env={name: "hostile"})


def test_execution_request_snapshots_mutable_inputs(tmp_path: Path) -> None:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest

    argv, env, roots = ["/bin/true"], {"PATH": "/bin"}, [tmp_path]
    policy = ExecutionPolicy(read_roots=roots, write_roots=roots, network="deny", required=True)
    request = ExecutionRequest(argv=argv, cwd=tmp_path, env=env, policy=policy,
                               timeout_seconds=1, cleanup_timeout_seconds=1,
                               invocation_id="request-a")
    argv.append("injected")
    env["GH_TOKEN"] = "injected"
    roots.append(Path("/"))
    assert tuple(request.argv) == ("/bin/true",)
    assert dict(request.env) == {"PATH": "/bin"}
    assert tuple(request.policy.write_roots) == (tmp_path,)
    with pytest.raises(TypeError):
        request.env["PATH"] = "/hostile"


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_execution_deadlines_must_be_finite_and_positive(tmp_path: Path, timeout: float) -> None:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest

    with pytest.raises(ValueError):
        ExecutionRequest(argv=["/bin/true"], cwd=tmp_path, env={},
                         policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                                                network="deny", required=True),
                         timeout_seconds=timeout, cleanup_timeout_seconds=1,
                         invocation_id="invalid-timeout")


def test_policy_rejects_unenforceable_network_destination_allowlist(tmp_path: Path) -> None:
    from evolution.core.execution import ExecutionPolicy

    with pytest.raises(ValueError):
        ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                        network="allow:pypi.org", required=True)


@pytest.mark.parametrize("change", [{"argv": []}, {"cwd": Path("relative")},
                                     {"invocation_id": ""}, {"env": {"NESTED": {"value": "bad"}}}])
def test_invalid_execution_request_fails_before_launch(tmp_path: Path, change: dict) -> None:
    from evolution.core.execution import ExecutionPolicy, ExecutionRequest

    arguments = dict(argv=["/bin/true"], cwd=tmp_path, env={}, timeout_seconds=1,
                     cleanup_timeout_seconds=1, invocation_id="request-a",
                     policy=ExecutionPolicy(read_roots=[tmp_path], write_roots=[tmp_path],
                                            network="deny", required=True))
    arguments.update(change)
    with pytest.raises(ValueError):
        ExecutionRequest(**arguments)
