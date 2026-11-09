"""Authority prerequisites and runtime inventory; no native acceptance claims."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evolution.code import semantic_verifier as verifier
from evolution.code import strict_json as js
from evolution.code import verification_runtime as runtimes
from evolution.code.verification_contracts import load_semantic_spec
from evolution.code.verified_snapshot import ProtectedSnapshot
from tests.code.test_verified_snapshot import environment
from tests.code.verification_fixtures import SOURCE, TARGET, protected_json, semantic_spec


def test_legacy_spec_without_aggregate_inode_bound_cannot_authorize(tmp_path: Path) -> None:
    document = semantic_spec()
    document["schema_version"] = "1"
    document["limits"].pop("scratch_inodes")
    document["limits"]["processes"] = 1
    with pytest.raises(ValueError, match="semantic_spec_invalid"):
        load_semantic_spec(protected_json(tmp_path / "legacy.json", document))


def test_version_two_spec_retains_aggregate_inode_bound(tmp_path: Path) -> None:
    document = semantic_spec()
    document["schema_version"] = "2"
    document["limits"].update(processes=1, scratch_inodes=4096)
    spec = load_semantic_spec(protected_json(tmp_path / "current.json", document))
    assert spec.limits.scratch_inodes == 4096


def test_matching_registry_hashes_under_replaceable_ancestor_cannot_establish_trust(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "replaceable"
    ancestor.mkdir(mode=0o777)
    ancestor.chmod(0o700)
    bundle = ancestor / "runtime"
    bundle.mkdir(mode=0o700)
    interpreter = bundle / "python"
    interpreter.write_bytes(b"untrusted interpreter fixture\n")
    interpreter.chmod(0o500)
    entry = {
        "interpreter": str(interpreter),
        "interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
        "runtime_roots": [str(bundle)],
        "runtime_manifest_sha256": hashlib.sha256(
            js.canonical_bytes(runtimes.runtime_manifest((bundle,)))
        ).hexdigest(),
        "backend": "bubblewrap", "policy": "python-json-command-v1",
    }
    config = protected_json(tmp_path / "authority" / "registry.json", {
        "schema_version": "1", "runtimes": {"fixture": entry},
    })
    ancestor.chmod(0o777)
    runtime = None
    try:
        with pytest.raises(ValueError, match="verification_runtime_untrusted"):
            runtime = runtimes.resolve_runtime(config, runtime_id="fixture")
    finally:
        if runtime is not None:
            runtime.close()


def test_diagnostic_dictionary_cannot_register_unreplayed_prerequisites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = environment(tmp_path)
    env.require_sandbox = True
    monkeypatch.setattr(env, "changed_files", Mock(return_value=[TARGET]))
    monkeypatch.setattr("evolution.code.worktree._run", Mock(return_value=SimpleNamespace(
        returncode=0, stdout="a" * 40,
    )))
    context = verifier.VerificationContext()
    context.spec_path = tmp_path / "authority" / "spec.json"
    context.runtime = SimpleNamespace(
        config=tmp_path / "authority" / "registry.json",
        entry={"runtime_roots": (str(tmp_path / "runtime"),)},
    )
    context.spec = SimpleNamespace(baseline={
        "repository_id": str(env.repo_root.resolve()), "commit": "a" * 40,
        "target": TARGET, "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
    })
    verifier._CONTEXTS.add(context)
    monkeypatch.setattr(context, "current", lambda: True)
    decision = {
        "diagnostic_comparison": {"status": "passed"},
        "full_suite": {"passed": True},
    }
    try:
        with ProtectedSnapshot.capture(env, tool_relpath=TARGET) as snapshot:
            with pytest.raises(ValueError):
                verifier._gate_prerequisites(
                    snapshot, base_source=SOURCE.decode(), decision=decision, context=context,
                )
    finally:
        verifier._CONTEXTS.discard(context)


def test_runtime_inventory_never_combines_old_metadata_with_replacement_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "runtime"
    bundle.mkdir(mode=0o700)
    target = bundle / "python"
    target.write_bytes(b"before")
    target.chmod(0o500)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"after!")
    replacement.chmod(0o400)
    original_lstat = Path.lstat
    swapped = False

    def lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal swapped
        metadata = original_lstat(path, *args, **kwargs)
        if path == target and not swapped:
            os.replace(replacement, target)
            swapped = True
        return metadata

    monkeypatch.setattr(Path, "lstat", lstat)
    try:
        inventory = runtimes.runtime_manifest((bundle,))
    except ValueError:
        return
    row = next(entry for entry in inventory if entry["path"] == "python")
    assert swapped, "inventory did not exercise metadata/byte substitution"
    assert (row["mode"], row["source_sha256"]) == (
        0o400, hashlib.sha256(b"after!").hexdigest(),
    ), "accepted runtime inventory combines metadata and bytes from different objects"


def test_inventory_refuses_directory_substitution_before_descent(tmp_path, monkeypatch):
    root = tmp_path / 'bundle'
    package = root / 'package'
    package.mkdir(parents=True, mode=0o700)
    (package / 'module.py').write_bytes(b'original')
    replacement = tmp_path / 'replacement'
    replacement.mkdir(mode=0o750)
    (replacement / 'module.py').write_bytes(b'replacement')
    original_open = os.open
    substituted = False

    def opening(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal substituted
        if path == 'package' and flags & os.O_DIRECTORY and not substituted:
            substituted = True
            package.rename(root / 'old-package')
            replacement.rename(package)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, 'open', opening)
    with pytest.raises(ValueError, match='runtime directory changed'):
        runtimes.runtime_manifest((root,))
    assert substituted
