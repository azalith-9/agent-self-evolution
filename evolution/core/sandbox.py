"""Capability-tested OS containment with explicit filesystem and network grants."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


class SandboxUnavailableError(RuntimeError):
    """Required OS containment cannot be enforced on this host."""


def _unavailable_reason() -> str:
    return (f"Required containment is unavailable on {sys.platform}: the native backend "
            "is absent or failed its behavioral probe. Refusing to run unconfined.")


def runtime_read_roots() -> list[Path]:
    """Runtime files needed by Python and native commands, excluding user stores."""
    roots = [Path(p).resolve() for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64") if Path(p).exists()]
    roots += [Path(sys.executable).resolve().parent.parent, Path(sys.prefix).resolve()]
    roots += [Path(p) for p in ("/etc/ld.so.cache", "/etc/localtime") if Path(p).exists()]
    if sys.platform == "darwin":
        roots += [Path("/System"), Path("/Library/Apple")]
    return list(dict.fromkeys(roots))


def _sbpl_path(path: Path) -> str:
    result = str(path.resolve())
    if any(ch in result for ch in '"()\\\n\r'):
        raise ValueError("sandbox paths cannot contain SBPL delimiters")
    return result


def macos_write_sandbox_profile(write_roots: list[Path], *, read_roots: list[Path] | None = None,
                                network: str = "deny") -> str:
    """Deny default access and permit only runtime reads and named writes."""
    reads = list(read_roots or runtime_read_roots()) + list(write_roots)
    read_rules = "\n".join(f'    (subpath "{_sbpl_path(p)}")' for p in reads)
    write_rules = "\n".join(f'    (subpath "{_sbpl_path(p)}")' for p in write_roots)
    return ("(version 1)\n(deny default)\n"
            "(allow process* sysctl-read mach-lookup signal file-read-metadata)\n"
            f"(allow file-read*\n{read_rules})\n"
            '(allow file-read* (literal "/dev/null") (literal "/dev/urandom"))\n'
            f"(allow file-write*\n{write_rules}\n    (literal \"/dev/null\"))\n"
            + ("(allow network*)\n" if network == "allow" else "(deny network*)\n"))


def _linux_argv(argv: list[str], *, reads: list[Path], writes: list[Path], network: str) -> list[str]:
    binary = shutil.which("bwrap")
    if not binary:
        raise SandboxUnavailableError(_unavailable_reason())
    command = [binary, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL"]
    if network == "allow":
        command += ["--share-net"]
        reads += [Path(p) for p in ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl/certs")
                  if Path(p).exists()]
    command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    # Parent mounts precede children so a broad read grant cannot hide a narrower write grant.
    mounts = {p.resolve(): False for p in reads}
    mounts.update({p.resolve(): True for p in writes})
    for path, writable in sorted(mounts.items(), key=lambda pair: len(pair[0].parts)):
        if path == Path("/"):
            raise ValueError("refusing a whole-host mount")
        if not path.exists():
            raise SandboxUnavailableError(f"required sandbox mount does not exist: {path}")
        command += ["--bind" if writable else "--ro-bind", str(path), str(path)]
    for path in writes:
        metadata = path / ".git"
        if metadata.exists():
            command += ["--ro-bind", str(metadata.resolve()), str(metadata)]
    result = [*command, "--", *argv]
    if network == "deny":
        if platform.machine() not in {"x86_64", "aarch64"} or not hasattr(os, "memfd_create"):
            raise SandboxUnavailableError("Linux socket containment is unavailable for this architecture")
        result = [sys.executable, "-I", str(Path(__file__).with_name("sandbox_worker.py")), *result]
    return result


def _wrap_native(argv: list[str], *, reads: list[Path], writes: list[Path], network: str) -> list[str]:
    if sys.platform.startswith("linux"):
        return _linux_argv(argv, reads=reads, writes=writes, network=network)
    binary = shutil.which("sandbox-exec")
    if sys.platform == "darwin" and binary:
        return [binary, "-p", macos_write_sandbox_profile(writes, read_roots=reads, network=network), *argv]
    raise SandboxUnavailableError(_unavailable_reason())


def sandbox_available() -> bool:
    """Probe denied reads/writes, host networking and sockets, plus permitted writes."""
    binary = "bwrap" if sys.platform.startswith("linux") else "sandbox-exec"
    if sys.platform not in {"linux", "darwin"} or not shutil.which(binary):
        return False
    try:
        with tempfile.TemporaryDirectory(prefix="ase-capability-") as directory:
            root = Path(directory)
            work = root / "work"
            work.mkdir()
            canary = root / "canary"
            canary.write_text("private")
            with socket.socket() as listener, socket.socket(socket.AF_UNIX) as unix:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                unix.bind(str(work / "host.sock"))
                unix.listen(1)
                script = '''import json,socket,sys
from pathlib import Path
canary,work,unix_path,port=sys.argv[1:]
checks=[]
for action in (lambda: Path(canary).read_text(),lambda: Path(canary).write_text('changed')):
    try: action(); checks.append(False)
    except OSError: checks.append(True)
for family,address in ((socket.AF_INET,('127.0.0.1',int(port))),(socket.AF_UNIX,unix_path)):
    with socket.socket(family) as client:
        client.settimeout(.1)
        try: client.connect(address); checks.append(False)
        except OSError: checks.append(True)
Path(work,'allowed').write_text('allowed')
print(json.dumps(checks))
'''
                command = _wrap_native([str(Path(sys.executable).resolve()), "-I", "-c", script,
                                        str(canary), str(work), str(work / "host.sock"),
                                        str(listener.getsockname()[1])],
                                       reads=runtime_read_roots(), writes=[work], network="deny")
                result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                        cwd=work, env={"PATH": os.defpath}, start_new_session=True)
                return (result.returncode == 0 and json.loads(result.stdout) == [True] * 4
                        and canary.read_text() == "private" and (work / "allowed").read_text() == "allowed")
    except (OSError, ValueError, subprocess.SubprocessError, SandboxUnavailableError):
        return False


def require_sandbox_or_fail(require: bool) -> None:
    if require and not sandbox_available():
        raise SandboxUnavailableError(_unavailable_reason())


def wrap_argv(argv: list[str], *, write_roots: list[Path], require: bool,
              available: bool | None = None, read_roots: list[Path] | None = None,
              network: str = "deny") -> tuple[list[str], bool]:
    """Prepare native containment; unavailable required policies always refuse."""
    if network not in {"allow", "deny"}:
        raise ValueError("unsupported network policy; destination allowlists cannot be enforced")
    if sandbox_available() if available is None else available:
        writes = [p.resolve() for p in write_roots]
        reads = [p.resolve() for p in (read_roots if read_roots is not None else runtime_read_roots())]
        return _wrap_native(argv, reads=reads, writes=writes, network=network), True
    if require:
        raise SandboxUnavailableError(_unavailable_reason())
    return list(argv), False
