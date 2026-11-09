"""Unavailable preparation must produce explicit evidence without native claims."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from tests.code.verification_fixtures import component


REQUIRED_PROBES = frozenset(
    {
        "scratch_access",
        "host_read_denied",
        "host_write_denied",
        "snapshot_write_denied",
        "verifier_access_denied",
        "expectations_access_denied",
        "journal_access_denied",
        "authority_descriptors_closed",
        "host_tcp_denied",
        "host_udp_denied",
        "filesystem_unix_socket_denied",
        "abstract_unix_socket_denied",
        "private_process_visibility",
        "supervisor_signal_denied",
        "memory_limit",
        "process_limit",
        "scratch_limit",
        "cpu_limit",
        "stdin_bounded",
        "capture_bounded",
        "timeout_cleanup",
        "cancellation_cleanup",
        "double_fork_cleanup",
        "setsid_cleanup",
        "sigterm_ignoring_cleanup",
        "retained_output_cleanup",
        "runtime_mutation_denied",
        "import_injection_denied",
        "forged_evidence_rejected",
        "replayed_invocation_rejected",
        "identity_substitution_rejected",
        "source_mutation_rejected",
        "snapshot_substitution_rejected",
    }
)
REQUIRED_DEMONSTRATIONS = frozenset(
    {
        "known_good_accepted",
        "wrong_response_rejected",
        "exact_byte_mode_export",
        "consumed_authority_rejected",
    }
)


def test_missing_runtime_records_every_unavailable_guarantee_and_exits_two(tmp_path: Path, monkeypatch) -> None:
    module = component("evolution.code.native_evidence")
    monkeypatch.setattr(module, "collect_cleanup_probes", lambda: [])
    result = CliRunner().invoke(
        module.main,
        [
            "--verification-runtime-config",
            str(tmp_path / "missing-runtime.json"),
            "--runtime-id",
            "independent-python",
            "--output-dir",
            str(tmp_path / "evidence"),
            "--demo",
        ],
    )
    assert result.exit_code == 2
    evidence = json.loads((tmp_path / "evidence/native_evidence.json").read_bytes())
    assert set(evidence) == {
        "schema_version",
        "host",
        "framework_id",
        "runtime_id",
        "policy_id",
        "demo_requested",
        "probes",
        "demonstrations",
        "generic_cleanup",
        "collector_exit_code",
    }
    assert evidence["schema_version"] == "2" and evidence["demo_requested"] is True
    assert {probe["id"] for probe in evidence["probes"]} == REQUIRED_PROBES
    assert {demo["id"] for demo in evidence["demonstrations"]} == REQUIRED_DEMONSTRATIONS
    for observation in evidence["probes"] + evidence["demonstrations"]:
        assert observation["status"] == "unavailable"
        assert observation["exit_code"] is None and observation["receipt_ids"] == []
        assert set(observation) == {
            "id",
            "status",
            "command",
            "exit_code",
            "observation",
            "receipt_ids",
        }
    assert evidence["collector_exit_code"] == 2
    assert evidence["runtime_id"] is None and evidence["policy_id"] is None
