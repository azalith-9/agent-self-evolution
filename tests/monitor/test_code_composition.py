"""Monitor composition stays lazy and exposes explicit optional journal storage."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from evolution.monitor import attempt
from evolution.monitor.__main__ import main


@pytest.mark.parametrize("module", ["attempt", "sentinel"])
def test_monitor_domain_has_no_concrete_code_tier_imports(module: str) -> None:
    source = Path(__file__).resolve().parents[2] / "evolution" / "monitor" / f"{module}.py"
    tree = ast.parse(source.read_text())
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("evolution.code"):
            forbidden.append(node.module)
        elif isinstance(node, ast.Import):
            forbidden.extend(alias.name for alias in node.names if alias.name.startswith("evolution.code"))
    assert forbidden == [], f"route concrete adapters through evolution.composition.monitor_code: {forbidden}"


def test_fresh_monitor_import_does_not_load_repair_implementation() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import evolution.monitor.sentinel, evolution.monitor.attempt; "
        "loaded=sorted(m for m in sys.modules if m.startswith('evolution.code.')); "
        "assert not loaded, loaded"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(root)],
        cwd=root, env={}, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_attempt_api_exposes_optional_keyword_only_progress_root() -> None:
    parameter = inspect.signature(attempt.attempt_candidates).parameters.get("progress_root")
    assert parameter is not None, "monitor attempts cannot receive durable progress storage"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None


def test_monitor_cli_exposes_optional_progress_root() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--progress-root" in result.output
