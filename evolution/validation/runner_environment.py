"""Private runner homes and explicit credential selection for agent children."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from evolution.core.sandbox import runtime_read_roots

def agent_environment(
    home: Path, overrides: Mapping[str, str], *, credential_keys: tuple[str, ...] = ()
) -> dict[str, str]:
    """Use the shared allowlist and an explicitly selected provider arrangement."""
    from evolution.core.execution import prepare_environment

    return dict(prepare_environment(
        kind="agent", parent=os.environ, home=home.resolve(), tmpdir=home.resolve(),
        credential_names=credential_keys, extra_env=overrides,
    ))


def agent_read_roots(command: str) -> list[Path]:
    """Add the explicitly selected agent installation to the common runtime."""
    import shutil

    roots = runtime_read_roots()
    executable = shutil.which(command)
    if executable is not None:
        path = Path(executable).resolve()
        installation = path.parent.parent if path.parent.name in {"bin", "Scripts"} else path.parent
        roots.append(path if installation == Path("/") else installation)
    return list(dict.fromkeys(roots))


def copy_skills(source: Path, destination: Path) -> None:
    """Stage regular files without following any source symlink."""
    from evolution.core.paths import read_contained, write_contained

    if source.is_symlink():
        raise ValueError("skill source cannot be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for directory, directories, files in os.walk(source, followlinks=False):
        current = Path(directory)
        for name in directories:
            if (current / name).is_symlink():
                raise ValueError("skill source contains a symlink directory")
        for name in files:
            relative = (current / name).relative_to(source)
            write_contained(destination, relative, read_contained(source, relative))


def hermes_credential_keys(config_path: Path) -> tuple[str, ...]:
    """Select supported environment authentication without opening developer auth stores."""
    import yaml
    from evolution.core.hermes_provider import _PROVIDER_ENV_KEYS, _PROVIDER_ALIASES

    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict) or not isinstance(config.get("model", {}), dict):
        raise ValueError("Hermes model configuration must be an object")
    provider = config.get("model", {}).get("provider", "auto")
    if not isinstance(provider, str):
        raise ValueError("Hermes provider must be a string")
    provider = provider.strip().lower()
    if provider in {"", "auto"}:
        from evolution.core.hermes_provider import _auto_detect
        provider = _auto_detect({}, [])[0] or ""
    if provider in {"aws", "aws-bedrock", "amazon", "amazon-bedrock"}:
        provider = "bedrock"
    if provider == "bedrock":
        keys = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION", "AWS_DEFAULT_REGION")
        selected = tuple(k for k in keys if os.environ.get(k))
        if not {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"} <= set(selected):
            raise ValueError("Hermes Bedrock requires an explicit environment credential pair")
        return selected
    # Local providers retain their own no-auth policy before alias normalization.
    keys = _PROVIDER_ENV_KEYS.get(provider)
    if keys is None:
        keys = _PROVIDER_ENV_KEYS.get(_PROVIDER_ALIASES.get(provider, provider))
    if keys is None:
        raise ValueError("Hermes provider has no supported private credential arrangement")
    return next(((key,) for key in keys if os.environ.get(key)), ())
