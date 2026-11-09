"""The complete semantic case population and all resource bounds are explicit."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.code.verification_fixtures import (
    component,
    protected_json,
    request_case,
    semantic_spec,
)


def load(tmp_path: Path, document: dict) -> object:
    api = component("evolution.code.verification_contracts")
    return api.load_semantic_spec(protected_json(tmp_path / "spec.json", document))


def test_complete_spec_retains_exact_request_bytes(tmp_path: Path) -> None:
    spec = load(tmp_path, semantic_spec())
    assert spec.required_case_ids == ("positive", "negative")
    assert [case.request for case in spec.cases] == [b"[2,3]\n", b"[-2,3]\n"]


@pytest.mark.parametrize(
    "mutation",
    [
        "numeric_version",
        "unknown_field",
        "unknown_baseline_field",
        "wrong_kind",
        "missing_required_ids",
        "duplicate_id",
        "missing_case",
        "reordered_cases",
        "extra_case",
        "boolean_limit",
        "missing_limit",
        "excess_limit",
        "noncanonical_base64",
        "traversal",
        "non_python",
        "bad_digest",
        "empty_cases",
    ],
)
def test_invalid_specs_refuse_before_candidate_execution(tmp_path: Path, mutation: str) -> None:
    spec = semantic_spec()
    if mutation == "numeric_version":
        spec["schema_version"] = 1
    elif mutation == "unknown_field":
        spec["accepted"] = True
    elif mutation == "unknown_baseline_field":
        spec["baseline"]["target_path"] = "x.py"
    elif mutation == "wrong_kind":
        spec["kind"] = "pytest"
    elif mutation == "missing_required_ids":
        del spec["required_case_ids"]
    elif mutation == "duplicate_id":
        spec["required_case_ids"] = ["positive", "positive"]
    elif mutation == "missing_case":
        spec["cases"].pop()
    elif mutation == "reordered_cases":
        spec["cases"].reverse()
    elif mutation == "extra_case":
        spec["cases"].append(request_case(b"extra"))
    elif mutation == "boolean_limit":
        spec["limits"]["processes"] = True
    elif mutation == "missing_limit":
        del spec["limits"]["cpu_seconds"]
    elif mutation == "excess_limit":
        spec["limits"]["memory_bytes"] = 1073741825
    elif mutation == "noncanonical_base64":
        spec["cases"][0]["request_base64"] = "WzIsM10K\n"
    elif mutation == "traversal":
        spec["baseline"]["target"] = "../command.py"
    elif mutation == "non_python":
        spec["baseline"]["target"] = "command.so"
    elif mutation == "bad_digest":
        spec["baseline"]["source_sha256"] = "A" * 64
    elif mutation == "empty_cases":
        spec.update(cases=[], required_case_ids=[])
    with pytest.raises(ValueError, match="semantic_spec_invalid"):
        load(tmp_path, spec)


@pytest.mark.parametrize(
    "field,lower,upper",
    [
        ("wall_seconds", 1, 60),
        ("cleanup_seconds", 1, 30),
        ("cpu_seconds", 1, 30),
        ("memory_bytes", 67108864, 1073741824),
        ("processes", 1, 1),
        ("scratch_inodes", 16, 65536),
        ("scratch_bytes", 4096, 67108864),
        ("source_bytes", 1, 1048576),
        ("request_bytes", 1, 65536),
        ("stdout_bytes", 1, 1048576),
        ("stderr_bytes", 1, 1048576),
    ],
)
def test_limit_ranges_are_enforced_without_clamping(
    tmp_path: Path, field: str, lower: int, upper: int
) -> None:
    spec = semantic_spec()
    spec["cases"] = [request_case(b"x")]
    spec["required_case_ids"] = ["bytes"]
    for value in (lower, upper):
        spec["limits"][field] = value
        assert getattr(load(tmp_path, spec).limits, field) == value
    for value in (lower - 1, upper + 1):
        spec["limits"][field] = value
        with pytest.raises(ValueError, match="semantic_spec_invalid"):
            load(tmp_path, spec)


def test_maximum_request_survives_base64_without_added_newline(tmp_path: Path) -> None:
    spec = semantic_spec()
    spec["cases"] = [request_case(b"x" * 65536)]
    spec["required_case_ids"] = ["bytes"]
    assert load(tmp_path, spec).cases[0].request == b"x" * 65536
    spec["cases"] = [request_case(b"x" * 65537)]
    with pytest.raises(ValueError, match="semantic_spec_invalid"):
        load(tmp_path, spec)


def test_spec_bound_is_checked_before_parsing(tmp_path: Path) -> None:
    api = component("evolution.code.verification_contracts")
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="semantic_spec_invalid"):
        api.load_semantic_spec(path)
