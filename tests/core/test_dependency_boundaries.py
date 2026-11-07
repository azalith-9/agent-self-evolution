"""Keep shared infrastructure independent of tier adapters at import time."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
TIERS = {"skills", "tools", "prompts", "code", "monitor"}


def test_core_does_not_import_tier_packages() -> None:
    violations = []
    for path in (ROOT / "evolution/core").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([node.module] if isinstance(node, ast.ImportFrom)
                     else [entry.name for entry in node.names] if isinstance(node, ast.Import)
                     else [])
            for name in names:
                parts = (name or "").split(".")
                if len(parts) >= 2 and parts[0] == "evolution" and parts[1] in TIERS:
                    violations.append(f"{path.name}:{node.lineno}: {name}")
    assert not violations, violations


def test_importing_feedback_does_not_load_tier_sources(tmp_path: Path) -> None:
    script = """import sys
import evolution.core.closed_loop_feedback
import evolution.core.dataset_builder
assert not any(name.startswith(('evolution.tools.', 'evolution.prompts.')) for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True,
        timeout=20, env={"PATH": os.defpath, "HOME": str(tmp_path),
                         "LITELLM_LOCAL_MODEL_COST_MAP": "True"},
    )
    assert result.returncode == 0, result.stderr
