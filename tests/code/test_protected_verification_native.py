"""Opt-in supported-host evidence through the production CLI, never fake proof.

Set ASE_NATIVE_RUNTIME_CONFIG and ASE_NATIVE_RUNTIME_ID only after independent
runtime provisioning. Missing configuration is a skip, not native validation.
Run this file detached; credential-free probes may take several minutes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.code.test_native_evidence import REQUIRED_DEMONSTRATIONS, REQUIRED_PROBES


@pytest.fixture(scope="module")
def native_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict:
    config = os.environ.get("ASE_NATIVE_RUNTIME_CONFIG")
    runtime_id = os.environ.get("ASE_NATIVE_RUNTIME_ID")
    if not config or not runtime_id:
        pytest.skip("independently provisioned native verification runtime not configured")
    destination = tmp_path_factory.mktemp("protected-native")
    command = [
        sys.executable,
        "-m",
        "evolution.code.native_evidence",
        "--verification-runtime-config",
        config,
        "--runtime-id",
        runtime_id,
        "--output-dir",
        str(destination),
        "--demo",
    ]
    # The trusted probe tool, not a candidate, receives these explicit inputs.
    env = {"PATH": os.defpath, "HOME": str(destination), "TMPDIR": str(destination)}
    result = subprocess.run(command, env=env, capture_output=True, timeout=240, check=False)
    assert result.returncode == 0, (
        "Native enforcement was requested but not demonstrated: "
        + result.stderr.decode(errors="replace")[-2000:]
    )
    evidence = json.loads((destination / "native_evidence.json").read_bytes())
    assert evidence["host"]["platform"].startswith("linux")
    assert evidence["host"]["backend"] == "bubblewrap"
    return evidence


@pytest.mark.parametrize("probe_id", sorted(REQUIRED_PROBES))
def test_actual_policy_enforces_each_required_guarantee(
    native_evidence: dict, probe_id: str
) -> None:
    probes = {probe["id"]: probe for probe in native_evidence["probes"]}
    assert set(probes) == REQUIRED_PROBES
    assert probes[probe_id]["status"] == "enforced"
    assert probes[probe_id]["receipt_ids"], "candidate assertions are not supervisor observations"


@pytest.mark.parametrize("demo_id", sorted(REQUIRED_DEMONSTRATIONS))
def test_native_acceptance_rejection_and_single_use_export(
    native_evidence: dict, demo_id: str
) -> None:
    demonstrations = {demo["id"]: demo for demo in native_evidence["demonstrations"]}
    assert set(demonstrations) == REQUIRED_DEMONSTRATIONS
    assert demonstrations[demo_id]["status"] == "enforced"
    assert demonstrations[demo_id]["receipt_ids"]
