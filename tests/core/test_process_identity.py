"""Never signal a cached numeric PID after its descendant identity is gone."""

import os
import signal
import time
from unittest.mock import Mock

import pytest

from evolution.core import process_worker


@pytest.mark.skipif(not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"),
                    reason="requires Linux PID descriptors")
def test_cleanup_rechecks_ancestry_after_opening_process_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    ancestry = iter(({700}, set(), set()))
    monkeypatch.setattr(process_worker, "_descendants", lambda root: next(ancestry))
    opened, closed = [], []
    monkeypatch.setattr(os, "pidfd_open", lambda pid: opened.append(pid) or 19)
    monkeypatch.setattr(os, "close", lambda descriptor: closed.append(descriptor))
    signal_process = Mock()
    monkeypatch.setattr(signal, "pidfd_send_signal", signal_process)

    def no_children(*args: object) -> None:
        raise ChildProcessError

    monkeypatch.setattr(os, "waitpid", no_children)
    assert process_worker._cleanup(None, time.monotonic() + 1)
    assert opened == [700] and closed == [19]
    signal_process.assert_not_called()
