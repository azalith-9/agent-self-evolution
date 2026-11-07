"""Strict cooperative pytest diagnostics; these records confer no deployment authority."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TestEvidence:
    complete: bool
    failures: frozenset[str] = frozenset()
    error: str | None = None
    missing: frozenset[str] = frozenset()
    unexpected: frozenset[str] = frozenset()
    duplicates: frozenset[str] = frozenset()
    selected: frozenset[str] = frozenset()
    skipped: frozenset[str] = frozenset()
    unexecuted: frozenset[str] = frozenset()


def _object(pairs: list[tuple[str, object]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate diagnostic field")
        obj[key] = value
    return obj


def read_test_evidence(
    path: Path, *, invocation_id: str, exit_code: int | None,
    cleanup_complete: bool, required_nodeids: tuple[str, ...] = (),
) -> TestEvidence:
    """Read complete observations, separating required passing coverage from accounting."""
    required = set(required_nodeids)
    selected: set[str] = set()
    skipped: set[str] = set()
    duplicates: set[str] = set()
    passed: set[str] = set()
    called: set[str] = set()
    failures: set[str] = set()
    unexpected: set[str] = set()
    try:
        payload = json.loads(path.read_text(), object_pairs_hook=_object)
        common = {"schema_version", "invocation_id", "collected", "deselected", "items",
                  "collection_errors", "session_finished", "exit_code"}
        schema = payload.get("schema_version")
        expected = common | ({"selected", "executed", "skipped", "failures", "collection_finished"}
                             if schema == "2" else set())
        if schema not in {"1", "2"} or set(payload) != expected:
            raise ValueError("unknown diagnostic schema or fields")
        if payload["invocation_id"] != invocation_id:
            raise ValueError("diagnostic invocation mismatch")
        if (cleanup_complete is not True or type(exit_code) is not int or exit_code not in (0, 1)
                or type(payload["exit_code"]) is not int or payload["exit_code"] != exit_code
                or payload["session_finished"] is not True or payload["collection_errors"] != []):
            raise ValueError("session did not complete with matching status and cleanup")
        items = payload["items"]
        if not isinstance(items, list):
            raise ValueError("invalid diagnostic items")
        nodes = [item.get("nodeid") for item in items if isinstance(item, dict)]
        if len(nodes) != len(items) or any(not isinstance(n, str) or not n for n in nodes):
            raise ValueError("invalid item identity")
        selected = set(nodes)
        duplicates.update(n for n, count in Counter(nodes).items() if count > 1)
        unexpected = selected - required if required else set()
        if schema == "2":
            populations: dict[str, list[str]] = {}
            for key in ("collected", "selected", "deselected", "executed", "skipped", "failures"):
                values = payload[key]
                if not isinstance(values, list) or any(not isinstance(n, str) or not n for n in values):
                    raise ValueError("invalid identity population")
                populations[key] = values
                duplicates.update(n for n, count in Counter(values).items() if count > 1)
            if payload["collection_finished"] is not True:
                raise ValueError("collection did not finish")
            collected, chosen, excluded = (set(populations[k]) for k in ("collected", "selected", "deselected"))
            unexpected = collected - required if required else set()
            if (chosen != selected or chosen & excluded or collected != chosen | excluded
                    or set(populations["executed"]) != chosen):
                raise ValueError("inconsistent collection or execution accounting")
        else:
            collected, deselected = payload["collected"], payload["deselected"]
            if (type(collected) is not int or type(deselected) is not int
                    or collected < 1 or not 0 <= deselected < collected
                    or len(items) != collected - deselected):
                raise ValueError("incomplete legacy accounting")
        if duplicates:
            raise ValueError("duplicate diagnostic identities")
        for item in items:
            if set(item) != {"nodeid", "setup", "call", "teardown"}:
                raise ValueError("invalid item fields")
            phases: dict[str, str] = {}
            xfail = False
            for name in ("setup", "call", "teardown"):
                value = item[name]
                if schema == "2":
                    if (not isinstance(value, dict) or set(value) != {"outcome", "wasxfail"}
                            or type(value["wasxfail"]) is not bool):
                        raise ValueError("invalid phase fields")
                    xfail |= value["wasxfail"]
                    value = value["outcome"]
                if value not in ("passed", "failed", "skipped", "not_run"):
                    raise ValueError("invalid phase outcome")
                phases[name] = value
            setup, call, teardown = (phases[k] for k in ("setup", "call", "teardown"))
            if (setup == "not_run" or teardown == "not_run"
                    or (setup == "passed" and call == "not_run")
                    or (setup != "passed" and call != "not_run")):
                raise ValueError("contradictory test lifecycle")
            node = item["nodeid"]
            if "failed" in phases.values():
                failures.add(node)
            if "skipped" in phases.values() or xfail:
                skipped.add(node)
            if setup == "passed" and call in {"passed", "failed"} and not xfail:
                called.add(node)
            if set(phases.values()) == {"passed"} and not xfail:
                passed.add(node)
        if schema == "2" and (set(payload["failures"]) != failures or set(payload["skipped"]) != skipped):
            raise ValueError("outcomes contradict phase observations")
        if bool(failures) != (exit_code == 1):
            raise ValueError("failures contradict process exit status")
        return TestEvidence(True, frozenset(failures), missing=frozenset(required - passed),
                            unexpected=frozenset(unexpected), selected=frozenset(selected),
                            skipped=frozenset(skipped), unexecuted=frozenset(required - called))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return TestEvidence(False, error=f"incomplete pytest diagnostics: {exc}",
                            missing=frozenset(required - passed), unexpected=frozenset(unexpected),
                            duplicates=frozenset(duplicates), selected=frozenset(selected),
                            skipped=frozenset(skipped), unexecuted=frozenset(required - called))
