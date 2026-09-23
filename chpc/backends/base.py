"""Command execution + the resource-manager backend interface.

Every backend takes the reason as a single argv element -- it is never
interpolated into a shell string -- so an admin-supplied reason (or an
`explain` blob quoted into it) can contain spaces, quotes, or anything else
without any escaping/injection concern.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Protocol

log = logging.getLogger("chpc.backends")


@dataclass
class CommandResult:
    argv: List[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """The single choke point for process execution, so dry-run and test
    fakes only have to override one method."""

    def __init__(self, dry_run: bool = False, timeout: int = 15):
        self.dry_run = dry_run
        self.timeout = timeout

    def run(self, argv: List[str], mutating: bool = False) -> CommandResult:
        if mutating and self.dry_run:
            log.info("[dry-run] would run: %s", " ".join(shlex.quote(a) for a in argv))
            return CommandResult(argv, 0, "", "")
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
            return CommandResult(argv, proc.returncode, proc.stdout, proc.stderr)
        except FileNotFoundError as exc:
            return CommandResult(argv, 127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            return CommandResult(argv, 124, "", str(exc))


class ResourceManagerBackend(Protocol):
    name: str

    def drain(self, node: str, reason: str) -> bool: ...

    def resume(self, node: str) -> bool: ...

    def is_drained(self, node: str) -> Optional[bool]:
        """True/False if determinable, None if the backend couldn't tell
        (command failed, node unknown, output didn't parse)."""
        ...
