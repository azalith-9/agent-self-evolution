"""Task parsing and fixture writes must enforce the same filesystem boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolution.validation.task import TaskSuite
from evolution.validation.validator import _materialize_fixture


def _suite(tmp_path: Path, *rows: dict) -> Path:
    path = tmp_path / "suite.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


@pytest.mark.parametrize("relative", ["../escape", "nested/../../escape", "/tmp/escape"])
def test_suite_rejects_fixture_paths_outside_root(tmp_path: Path, relative: str) -> None:
    path = _suite(tmp_path, {"task_id": "t", "user_message": "m",
                             "fixture_setup": {relative: "payload"}})
    with pytest.raises(ValueError):
        TaskSuite.from_jsonl(path)


@pytest.mark.parametrize("setup", [{"x": 3}, {"x": None}, [], "bad"])
def test_suite_rejects_malformed_fixture_data(tmp_path: Path, setup: object) -> None:
    path = _suite(tmp_path, {"task_id": "t", "user_message": "m", "fixture_setup": setup})
    with pytest.raises(ValueError):
        TaskSuite.from_jsonl(path)


def test_duplicate_task_ids_cannot_collapse_validation_evidence(tmp_path: Path) -> None:
    path = _suite(tmp_path, {"task_id": "same", "user_message": "first"},
                  {"task_id": "same", "user_message": "second"})
    with pytest.raises(ValueError, match="duplicate"):
        TaskSuite.from_jsonl(path)


@pytest.mark.parametrize("relative", ["../host-skills", "/host/skills"])
def test_suite_rejects_uncontained_skill_source(tmp_path: Path, relative: str) -> None:
    path = _suite(tmp_path, {"task_id": "t", "user_message": "m", "skills_src": relative})
    with pytest.raises(ValueError):
        TaskSuite.from_jsonl(path)


@pytest.mark.parametrize("relative", ["../sentinel", "nested/../../sentinel"])
def test_programmatic_fixture_cannot_escape_root(tmp_path: Path, relative: str) -> None:
    root = tmp_path / "fixture"
    root.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("original")
    with pytest.raises(ValueError):
        _materialize_fixture(root, {relative: "#!/bin/sh\necho changed\n"})
    assert sentinel.read_text() == "original"


def test_fixture_refuses_escaping_symlink_without_chmodding_target(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    root.mkdir()
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("original")
    sentinel.chmod(0o600)
    (root / "linked").symlink_to(sentinel)
    with pytest.raises(ValueError):
        _materialize_fixture(root, {"linked": "#!/bin/sh\nexit 0\n"})
    assert (sentinel.read_text(), sentinel.stat().st_mode & 0o777) == ("original", 0o600)


def test_valid_nested_fixture_remains_executable(tmp_path: Path) -> None:
    _materialize_fixture(tmp_path, {"bin/check": "#!/bin/sh\nexit 0\n", "data/x": "é"})
    assert (tmp_path / "bin/check").stat().st_mode & 0o100
    assert (tmp_path / "data/x").read_text() == "é"
