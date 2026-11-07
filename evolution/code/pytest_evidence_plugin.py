"""Cooperative lifecycle diagnostics, independent of terminal summary formatting."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("harness-evidence")
    group.addoption("--evidence-path", default=None)
    group.addoption("--evidence-invocation-id", default=None)


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--evidence-path"):
        config.pluginmanager.register(_Evidence(config), "harness-completion")


class _Evidence:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.collected: list[str] = []
        self.deselected: list[str] = []
        self.executed: list[str] = []
        self.collection_finished = False
        self.collection_errors: list[str] = []
        self.items: dict[str, dict] = {}

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]):
        self.collection_order = [item.nodeid for item in items]
        yield

    def pytest_runtest_logstart(self, nodeid: str, location: tuple) -> None:
        self.executed.append(nodeid)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_errors.append(report.nodeid)

    def pytest_deselected(self, items: list[pytest.Item]) -> None:
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.collected = [item.nodeid for item in session.items] + self.deselected
        order = {item.nodeid: index for index, item in enumerate(session.items)}
        # Collection order is captured before selection by the collection hook.
        self.collected = getattr(self, "collection_order", sorted(self.collected, key=lambda n: order.get(n, len(order))))
        self.collection_finished = True
        self.items = {item.nodeid: {"nodeid": item.nodeid} for item in session.items}
        if len(self.items) != len(session.items):
            self.collection_errors.append("duplicate nodeids")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        item = self.items.setdefault(report.nodeid, {"nodeid": report.nodeid})
        item[report.when] = {"outcome": report.outcome, "wasxfail": bool(getattr(report, "wasxfail", False))}
        if report.when == "setup" and report.outcome != "passed":
            item["call"] = {"outcome": "not_run", "wasxfail": False}

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        payload = {
            "schema_version": "2",
            "invocation_id": self.config.getoption("--evidence-invocation-id"),
            "collected": self.collected,
            "selected": list(self.items),
            "executed": self.executed,
            "skipped": [n for n, item in self.items.items() if any(
                isinstance(v, dict) and (v["outcome"] == "skipped" or v["wasxfail"]) for v in item.values())],
            "failures": [n for n, item in self.items.items() if any(
                isinstance(v, dict) and v["outcome"] == "failed" for v in item.values())],
            "collection_finished": self.collection_finished,
            "deselected": self.deselected,
            "collection_errors": self.collection_errors,
            "session_finished": True,
            "exit_code": int(exitstatus),
            "items": list(self.items.values()),
        }
        path = Path(self.config.getoption("--evidence-path"))
        fd, name = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
