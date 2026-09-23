"""Slurm backend: drains/resumes via scontrol, the same well-known syntax
across every Slurm version chpc targets -- unaffected by RHEL/Rocky version,
since it depends only on which Slurm package is installed."""

from __future__ import annotations

import re
from typing import Optional

from .base import CommandRunner


class SlurmBackend:
    name = "slurm"

    def __init__(self, runner: CommandRunner, binary: str = "scontrol"):
        self.runner = runner
        self.binary = binary

    def drain(self, node: str, reason: str) -> bool:
        result = self.runner.run(
            [self.binary, "update", f"NodeName={node}", "State=DRAIN", f"Reason={reason}"],
            mutating=True,
        )
        return result.ok

    def resume(self, node: str) -> bool:
        result = self.runner.run(
            [self.binary, "update", f"NodeName={node}", "State=RESUME"], mutating=True
        )
        return result.ok

    def is_drained(self, node: str) -> Optional[bool]:
        result = self.runner.run([self.binary, "show", "node", "-o", node])
        if not result.ok:
            return None
        m = re.search(r"State=(\S+)", result.stdout)
        if not m:
            return None
        state = m.group(1).rstrip("*").upper()
        return state in {"DRAIN", "DRAINED", "DRAINING", "DOWN"}
