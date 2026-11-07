"""Test the actual project fixtures under a synthetic developer configuration.

Only synthetic config/auth files are created; neither Path.home nor the actual
developer credential store is patched or read by the child process.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_project_fixtures_ignore_developer_hermes_config(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "developer"
    (home / ".hermes").mkdir(parents=True)
    (home / ".hermes/config.yaml").write_text("model:\n  provider: zai\n  default: synthetic-model\n")
    canary = home / ".hermes/auth.json"
    canary.write_text('{"credential_pool": {"zai": [{"api_key": "synthetic-canary"}]}}')
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(root / "tests/conftest.py", suite / "conftest.py")
    (suite / "test_isolation.py").write_text('''from pathlib import Path
import os
from evolution.core.hermes_provider import resolve_default_lm

def test_default_resolution(monkeypatch):
    assert str(Path.home()) == os.environ["HOME"]
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        assert not str(path).startswith(os.environ["HOME"] + "/.hermes/"), "developer config read"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded)
    resolved = resolve_default_lm(role="eval")
    assert resolved.model.startswith("openai/")
    assert resolved.lm_kwargs["api_key"] == "sk-fake-pytest-key-never-sent"
''')
    env = {"PATH": os.defpath, "HOME": str(home), "TMPDIR": str(tmp_path),
           "PYTHONPATH": str(root), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "LITELLM_LOCAL_MODEL_COST_MAP": "True", "DSPY_CACHEDIR": str(tmp_path / "dspy")}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(suite)], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
