"""Automated remediation actions.

Only categories marked auto_fixable in classifier.CATEGORY_INFO get here
(currently: transient "not responding" and "kill task failed" cases). Every
hardware-adjacent or configuration-adjacent category is intentionally left
to a human -- this module resumes a node on the agent's own authority only
when the underlying fix is itself low-risk and reversible.
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import Category, DiagnosticReport
from .slurm_client import SlurmClient

log = logging.getLogger("slurm_monitor.remediation")


class RemediationResult:
    def __init__(self, attempted: bool, succeeded: bool, detail: str):
        self.attempted = attempted
        self.succeeded = succeeded
        self.detail = detail


def attempt_fix(report: DiagnosticReport, client: SlurmClient,
                 remote_exec: Optional[str] = None) -> RemediationResult:
    """Try a safe, category-specific fix. Returns whether a fix was even
    attempted and whether it appears to have worked, but never resumes the
    node itself -- that decision belongs to the caller (agent.py), which
    also has to consult the 24h recurrence history first."""

    if not report.auto_fixable:
        return RemediationResult(False, False, "category is not eligible for automated remediation")

    def run(cmd: str):
        full = remote_exec.format(node=report.node, command=cmd) if remote_exec else cmd
        return client.run(full)

    if report.category is Category.NOT_RESPONDING:
        result = run("systemctl restart slurmd")
        if result.ok:
            return RemediationResult(True, True, "restarted slurmd")
        return RemediationResult(True, False, f"systemctl restart slurmd failed: {result.stderr.strip()}")

    if report.category is Category.KILL_TASK_FAILED:
        # Best-effort: ask slurmd to re-sync, which reaps cgroups it can
        # safely reap. We deliberately do NOT kill -9 arbitrary processes
        # here -- that's exactly the kind of blind auto-fix that causes
        # data loss, so it stays a human action per the diagnostic report.
        result = run("scontrol reconfigure")
        if result.ok:
            return RemediationResult(True, True, "triggered scontrol reconfigure to help reap stale cgroups")
        return RemediationResult(True, False, f"reconfigure failed: {result.stderr.strip()}")

    return RemediationResult(False, False, "no remediation implemented for this category")


def resume(client: SlurmClient, node: str, note: str) -> bool:
    result = client.resume_node(node, reason=note)
    if not result.ok:
        log.error("failed to resume %s: %s", node, result.stderr.strip())
    return result.ok


def force_drain(client: SlurmClient, node: str, note: str) -> bool:
    result = client.drain_node(node, note)
    if not result.ok:
        log.error("failed to drain %s: %s", node, result.stderr.strip())
    return result.ok
