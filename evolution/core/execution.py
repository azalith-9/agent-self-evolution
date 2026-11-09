"""Immutable requests and least-authority child environments."""

from __future__ import annotations

import math
import os
import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ExecutionPolicy:
    read_roots: Sequence[Path]
    write_roots: Sequence[Path]
    network: str = "deny"
    required: bool = True

    def __post_init__(self) -> None:
        if self.network not in {"deny", "allow"}:
            raise ValueError("network policy must be 'deny' or 'allow'; destination filtering is unavailable")
        for name in ("read_roots", "write_roots"):
            roots = tuple(Path(p) for p in getattr(self, name))
            if any(not p.is_absolute() for p in roots):
                raise ValueError("execution roots must be absolute")
            roots = tuple(p.resolve() for p in roots)
            if self.required and Path("/") in roots:
                raise ValueError("the entire host filesystem cannot be an execution root")
            object.__setattr__(self, name, roots)


@dataclass(frozen=True)
class ExecutionRequest:
    argv: Sequence[str] = field(repr=False)
    cwd: Path
    env: Mapping[str, str] = field(repr=False)
    policy: ExecutionPolicy
    timeout_seconds: float
    cleanup_timeout_seconds: float
    invocation_id: str

    stdin_bytes: bytes = field(default=b"", repr=False)
    max_stdout_bytes: int = 1048576
    max_stderr_bytes: int = 1048576

    _runtime: tuple[str, str] | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if type(self.stdin_bytes) is not bytes:
            raise ValueError("stdin_bytes must be bytes")
        for limit in (self.max_stdout_bytes, self.max_stderr_bytes):
            if type(limit) is not int or not 1 <= limit <= 16777216:
                raise ValueError("capture bounds must be positive integers up to 16 MiB")
        if not self.argv or not self.argv[0] or any(not isinstance(x, str) or "\0" in x for x in self.argv):
            raise ValueError("argv must contain nonempty strings without NUL bytes")
        if not Path(self.cwd).is_absolute():
            raise ValueError("execution cwd must be absolute")
        if not isinstance(self.invocation_id, str) or not self.invocation_id.strip() or "\0" in self.invocation_id:
            raise ValueError("execution invocation identity is required")
        for value in (self.timeout_seconds, self.cleanup_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("execution deadlines must be finite and positive")
        for key, value in self.env.items():
            if not isinstance(key, str) or not key or "=" in key or "\0" in key:
                raise ValueError("invalid environment variable name")
            if not isinstance(value, str) or "\0" in value:
                raise ValueError("environment values must be strings without NUL bytes")
        object.__setattr__(self, "argv", tuple(self.argv))
        object.__setattr__(self, "cwd", Path(self.cwd).resolve())
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        selected = select_executable(self.argv[0], cwd=self.cwd, env=self.env)
        if selected is not None:
            runtime = Path(os.path.abspath(selected))
            object.__setattr__(self, "_runtime", (str(runtime), runtime_digest(runtime)))
            object.__setattr__(self, "argv", (str(runtime), *self.argv[1:]))


def select_executable(command: str, *, cwd: Path, env: Mapping[str, str]) -> str | None:
    """Select once using the child's cwd and explicit PATH, preserving venv links."""
    if "/" in command:
        candidate = Path(command)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return shutil.which(str(candidate))
    search = os.pathsep.join(str(Path(p) if Path(p).is_absolute() else cwd / p)
                             for p in env.get("PATH", os.defpath).split(os.pathsep))
    return shutil.which(command, path=search)


def runtime_digest(path: Path) -> str:
    """Observe runtime bytes and identity; this is drift detection, not isolation."""
    metadata = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{metadata.st_dev}:{metadata.st_ino}:{metadata.st_mode}:{digest}"



_LOCALE = {"LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ"}
_CREDENTIALS = {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "NOUS_API_KEY",
                "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GLM_API_KEY", "ZAI_API_KEY",
                "GITHUB_TOKEN", "KIMI_API_KEY", "MOONSHOT_API_KEY", "MINIMAX_API_KEY", "HF_TOKEN",
                "HUGGINGFACE_API_KEY", "NVIDIA_API_KEY", "XIAOMI_API_KEY", "ARCEEAI_API_KEY",
                "OLLAMA_API_KEY", "KILOCODE_API_KEY", "AI_GATEWAY_API_KEY", "LM_API_KEY",
                "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION",
                "AWS_DEFAULT_REGION"}
_EXTRA_ALLOWED = {"TERM", "NO_COLOR", "CLICOLOR", "MAX_THINKING_TOKENS", "ANTHROPIC_MODEL",
                  "HERMES_MODEL", "HERMES_MAX_ITERATIONS"}


def prepare_environment(*, kind: str, parent: Mapping[str, str], home: Path,
                        tmpdir: Path, credential_name: str | None = None,
                        extra_env: Mapping[str, str] | None = None,
                        credential_names: tuple[str, ...] = ()) -> Mapping[str, str]:
    """Build a fresh environment; extras cannot replace authority-bearing values."""
    if kind not in {"candidate", "agent"}:
        raise ValueError("execution kind must be candidate or agent")
    if not home.is_absolute() or not tmpdir.is_absolute():
        raise ValueError("private HOME and TMPDIR must be absolute")
    result = {key: value for key, value in parent.items() if key in _LOCALE or key == "PATH"}
    result.setdefault("PATH", os.defpath)
    result.update(HOME=str(home), TMPDIR=str(tmpdir), PYTHONDONTWRITEBYTECODE="1",
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    if credential_name and credential_names:
        raise ValueError("select one credential arrangement")
    names = (credential_name,) if credential_name else credential_names
    aws = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION", "AWS_DEFAULT_REGION"}
    if len(names) > 1 and (not set(names) <= aws or not {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"} <= set(names)):
        raise ValueError("unsupported multi-field credential arrangement")
    for name in names:
        if kind != "agent" or name not in _CREDENTIALS:
            raise ValueError("only an agent may receive an explicitly supported credential")
        if parent.get(name):
            result[name] = parent[name]
    for key, value in (extra_env or {}).items():
        if key not in _EXTRA_ALLOWED or not isinstance(value, str) or "\0" in value:
            raise ValueError("unauthorized execution environment override")
        result[key] = value
    return MappingProxyType(result)
