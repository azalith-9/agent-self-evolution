"""Private subprocess supervisor; invoked by process.py, never by candidate code."""

from __future__ import annotations

import base64
import ctypes
import selectors
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _descendants(root: int) -> set[int]:
    parents: dict[int, int] = {}
    if sys.platform.startswith("linux"):
        for item in Path("/proc").iterdir():
            if item.name.isdigit():
                try:
                    fields = (item / "stat").read_text().rsplit(") ", 1)[1].split()
                    parents[int(item.name)] = int(fields[1])
                except (OSError, IndexError, ValueError):
                    continue
    else:
        result = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True,
                                text=True, timeout=0.2)
        if result.returncode:
            raise RuntimeError("cannot inspect process descendants")
        for line in result.stdout.splitlines():
            pid, parent = line.split()
            parents[int(pid)] = int(parent)
    found = {root}
    while True:
        expanded = found | {pid for pid, parent in parents.items() if parent in found}
        if expanded == found:
            return found - {root}
        found = expanded


def _cleanup(proc: subprocess.Popen | None, deadline: float) -> bool:
    while time.monotonic() < deadline:
        for pid in _descendants(os.getpid()):
            try:
                if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                    descriptor = os.pidfd_open(pid)
                    try:
                        if pid in _descendants(os.getpid()):
                            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    finally:
                        os.close(descriptor)
                elif pid in _descendants(os.getpid()):
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc is not None:
            proc.poll()
        no_children = False
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                no_children = True
                break
        if no_children and not _descendants(os.getpid()):
            return True
        time.sleep(0.01)
    return False


def main() -> None:
    request = json.load(sys.stdin)
    status_fd = int(sys.argv[1])
    started = time.monotonic()
    status = {**request["bindings"], "exit_code": None, "timed_out": False,
              "cleanup_complete": False, "error": None, "launched": False,
              "cancelled": False, "capture_complete": False, "stdin_complete": False, "duration_seconds": 0.0}
    proc = None
    subreaper = False
    if sys.platform.startswith("linux"):
        subreaper = ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0

    def cancelled(signum: int, frame: object) -> None:
        raise InterruptedError("execution supervisor cancelled")

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        proc = subprocess.Popen(request["argv"], cwd=request["cwd"], env=request["env"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, close_fds=True)
        status["launched"] = True
        deadline = time.monotonic() + request["timeout_seconds"]
        payload = memoryview(base64.b64decode(request.get("stdin_base64", ""), validate=True))
        delivered = 0
        captures = {"stdout": bytearray(), "stderr": bytearray()}
        capture_complete = True
        eof = set()
        with selectors.DefaultSelector() as selector:
            for name in ("stdout", "stderr"):
                pipe = getattr(proc, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            os.set_blocking(proc.stdin.fileno(), False)
            if payload:
                selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                status["stdin_complete"] = True
                proc.stdin.close()
            while selector.get_map():
                if time.monotonic() >= deadline:
                    status["timed_out"] = True
                    break
                for key, mask in selector.select(min(.02, max(0, deadline - time.monotonic()))):
                    if key.data == "stdin":
                        try:
                            delivered += os.write(key.fd, payload[delivered:delivered + 65536])
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        if delivered == len(payload):
                            status["stdin_complete"] = True
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            eof.add(key.data)
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        name = key.data
                        room = request.get("max_" + name + "_bytes", 1048576) - len(captures[name])
                        captures[name].extend(chunk[:room])
                        if len(chunk) > room:
                            capture_complete = False
                if not capture_complete:
                    break
                if proc.poll() is not None:
                    # Cleanup descendants before waiting on their inherited output pipes.
                    if not _cleanup(proc, min(deadline, time.monotonic() + request["cleanup_timeout_seconds"])):
                        break
            if capture_complete and not status["timed_out"] and proc.poll() is None:
                try:
                    proc.wait(timeout=max(.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    status["timed_out"] = True
        for name in ("stdout", "stderr"):
            destination = getattr(sys, name).buffer
            destination.write(captures[name])
            destination.flush()
            pipe = getattr(proc, name)
            if not pipe.closed:
                pipe.close()
        if not proc.stdin.closed:
            proc.stdin.close()
        status["capture_complete"] = capture_complete and eof == {"stdout", "stderr"} and not status["timed_out"]
        status["exit_code"] = proc.returncode
    except (OSError, ValueError, RuntimeError, InterruptedError) as exc:
        status["cancelled"] = isinstance(exc, InterruptedError)
        status["error"] = "execution failed: " + type(exc).__name__
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            cleaned = _cleanup(proc, time.monotonic() + request["cleanup_timeout_seconds"])
            # Linux subreaping or a PID namespace is necessary to certify escaped sessions.
            certified = subreaper or request["pid_namespace"]
            status["containment"]["descendant_cleanup_certified"] = certified
            status["cleanup_complete"] = cleaned and certified
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            status["error"] = f"process cleanup failed: {exc}"
        if proc is not None and status["exit_code"] is None:
            status["exit_code"] = proc.poll()
        status["duration_seconds"] = time.monotonic() - started
        with os.fdopen(status_fd, "w") as destination:
            json.dump(status, destination)


if __name__ == "__main__":
    main()
