"""Thin wrapper around the Slurm CLI (sinfo/scontrol).

All actual process invocation goes through `run()` so tests can monkeypatch
a single choke point, and so a --dry-run agent can log the exact command it
would have executed without ever touching a real cluster.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .models import NodeState

log = logging.getLogger("slurm_monitor.slurm_client")


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SlurmClient:
    """Executes Slurm CLI commands and parses their output into models."""

    def __init__(self, dry_run: bool = False, timeout: int = 20):
        self.dry_run = dry_run
        self.timeout = timeout

    def run(self, command: str, mutating: bool = False) -> CommandResult:
        """Run a shell command. Mutating commands (scontrol update ...) are
        skipped and logged when dry_run is set."""
        if mutating and self.dry_run:
            log.info("[dry-run] would run: %s", command)
            return CommandResult(command, 0, "", "")
        log.debug("running: %s", command)
        try:
            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return CommandResult(command, proc.returncode, proc.stdout, proc.stderr)
        except FileNotFoundError as exc:
            return CommandResult(command, 127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            return CommandResult(command, 124, "", str(exc))

    # -- reads -----------------------------------------------------------

    def get_node_states(self) -> List[NodeState]:
        """Return NodeState for every node, via `scontrol show node -o`."""
        result = self.run("scontrol show node -o")
        if not result.ok:
            log.error("scontrol show node failed: %s", result.stderr.strip())
            return []
        return [parse_node_line(line) for line in result.stdout.splitlines() if line.strip()]

    def get_node_state(self, node: str) -> Optional[NodeState]:
        result = self.run(f"scontrol show node -o {node}")
        if not result.ok or not result.stdout.strip():
            return None
        return parse_node_line(result.stdout.splitlines()[0])

    # -- writes ------------------------------------------------------------

    def drain_node(self, node: str, reason: str) -> CommandResult:
        quoted = shlex.quote(reason)
        cmd = f"scontrol update NodeName={node} State=DRAIN Reason={quoted}"
        return self.run(cmd, mutating=True)

    def resume_node(self, node: str, reason: Optional[str] = None) -> CommandResult:
        cmd = f"scontrol update NodeName={node} State=RESUME"
        if reason:
            cmd += f" Reason={shlex.quote(reason)}"
        return self.run(cmd, mutating=True)

    def reconfigure(self) -> CommandResult:
        return self.run("scontrol reconfigure", mutating=True)


# -- parsing ---------------------------------------------------------------

_KV_RE = re.compile(r"(\w+)=((?:\"[^\"]*\")|(?:\S+))")


def parse_node_line(line: str) -> NodeState:
    """Parse one line of `scontrol show node -o` output (space-separated
    Key=Value pairs, some values quoted) into a NodeState."""
    fields = {}
    for key, value in _KV_RE.findall(line):
        fields[key] = value.strip('"')

    # scontrol renders a set reason as: Reason=some text [root@2024-01-01T00:00:00]
    # The reason text itself can contain spaces, so it can't be captured by
    # the generic Key=Value regex above -- slice it out of the raw line.
    reason_time = None
    reason_set_by = None
    if "Reason=" in line:
        after = line[line.index("Reason=") + len("Reason=") :]
        m = re.search(r"\[([^@\]]*)@([^\]]+)\]\s*$", after)
        if m:
            reason_set_by = m.group(1) or None
            try:
                reason_time = datetime.strptime(m.group(2), "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                reason_time = None
            reason = after[: after.index(m.group(0))]
        else:
            # no bracket annotation; Reason= runs up to the next Key= token
            # (or end of line) since values here are never quoted.
            reason = re.split(r"\s+\w+=", after, maxsplit=1)[0]
    else:
        reason = ""
    reason = reason.strip()

    return NodeState(
        name=fields.get("NodeName", ""),
        state=fields.get("State", ""),
        reason=reason,
        reason_set_at=reason_time,
        reason_set_by=reason_set_by,
        cfg_tres=fields.get("CfgTRES", ""),
        alloc_tres=fields.get("AllocTRES", ""),
        raw=fields,
    )
