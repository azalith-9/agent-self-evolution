"""A container shell failure cannot masquerade as Python tool source."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code.swebench.env import SWEbenchEnv


def test_container_read_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    env = SWEbenchEnv.__new__(SWEbenchEnv)
    env._container = object()
    monkeypatch.setattr("evolution.code.swebench.env._exec", Mock(return_value=(1, "cat: missing file")))
    with pytest.raises((OSError, RuntimeError)):
        env.read_tool("src/module.py")


@pytest.mark.parametrize("relative", ["../outside", "/etc/passwd"])
def test_container_file_reads_reject_escape(monkeypatch: pytest.MonkeyPatch, relative: str) -> None:
    env = SWEbenchEnv.__new__(SWEbenchEnv)
    env._container = object()
    execute = Mock(return_value=(0, "source"))
    monkeypatch.setattr("evolution.code.swebench.env._exec", execute)
    with pytest.raises(ValueError):
        env.read_tool(relative)
    execute.assert_not_called()


def test_container_reads_quote_shell_metacharacters(monkeypatch: pytest.MonkeyPatch) -> None:
    env = SWEbenchEnv.__new__(SWEbenchEnv)
    env._container = object()
    execute = Mock(return_value=(0, "source"))
    monkeypatch.setattr("evolution.code.swebench.env._exec", execute)
    assert env.read_tool("src/x.py; echo injected") == "source"
    assert shlex.split(execute.call_args.args[1]) == ["cat", "/testbed/src/x.py; echo injected"]


def test_container_setup_logger_receives_exclusively_created_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = SimpleNamespace(instance_id="synthetic-instance", is_remote_image=True)
    container = SimpleNamespace(start=lambda: None)
    paths = []

    def logger(instance_id: str, path: Path) -> object:
        paths.append(path)
        assert path.is_file(), "a name from mktemp does not reserve a private log file"
        assert path.stat().st_mode & 0o077 == 0
        return Mock()

    definitions = {
        "docker": {"from_env": lambda: object()},
        "swebench.harness.docker_build": {"build_container": lambda *args, **kwargs: container,
                                            "setup_logger": logger},
        "swebench.harness.test_spec.test_spec": {"make_test_spec": lambda *args, **kwargs: spec},
    }
    for name in ("swebench", "swebench.harness", "swebench.harness.test_spec", *definitions):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in definitions.get(name, {}).items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    instance = SimpleNamespace(instance_id="synthetic-instance", raw={}, fail_to_pass=(),
                                pass_to_pass=(), repo="synthetic/repo", gold_file="src/x.py")
    try:
        SWEbenchEnv.create(instance, run_id="synthetic")
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
