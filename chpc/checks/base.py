"""Shared types for the checks engine."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class CommandOutput:
    argv: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def default_runner(argv: List[str], timeout: int = 20, shell: bool = False) -> CommandOutput:
    try:
        proc = subprocess.run(
            argv if not shell else " ".join(argv),
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandOutput(argv, proc.returncode, proc.stdout, proc.stderr)
    except FileNotFoundError as exc:
        return CommandOutput(argv, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandOutput(argv, 124, "", str(exc))


@dataclass
class CheckSpec:
    """One parsed line from checks.conf."""

    hostmask: str
    name: str            # builtin check name, or "command"
    args: List[str]      # for "command", args == [the raw shell command line]
    raw: str

    @property
    def key(self) -> str:
        """Stable identity for debounce/state tracking -- same check+args on
        this node always maps to the same key, even across daemon restarts
        and checks.conf reloads (as long as the line itself doesn't change)."""
        return f"{self.name}:{' '.join(self.args)}"


@dataclass
class CheckResult:
    ok: bool
    detail: str
    measured: Optional[str] = None
    expected: Optional[str] = None


@dataclass
class CheckContext:
    """Everything a builtin check needs, injected so tests never have to
    touch the real /proc, /sys, or spawn real subprocesses."""

    hostname: str
    baseline: dict = field(default_factory=dict)
    run: Callable[..., CommandOutput] = default_runner
    proc_meminfo: str = "/proc/meminfo"
    proc_mounts: str = "/proc/mounts"
    proc_root: str = "/proc"
    sys_class_net: str = "/sys/class/net"
    command_timeout: int = 20
    cpu_count: Optional[int] = None  # override for os.cpu_count() in tests
    loadavg: Optional[Callable[[], tuple]] = None  # override for os.getloadavg()
