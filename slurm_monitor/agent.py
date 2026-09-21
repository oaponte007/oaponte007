"""The monitoring/remediation orchestration loop.

On every poll cycle, for each node currently in a DRAIN/DOWN-like state:

  1. Classify its Reason= text into a Category (classifier.py).
  2. Admin-initiated drains are left completely alone.
  3. If this exact node+category is already quarantined (we force-drained it
     for this reason and nobody has resumed it since), do nothing further.
  4. Otherwise, check whether this node+category has already fired within
     the trailing 24h window (history.py):
       - Yes  -> this is a RECURRENCE. Force the node into DRAIN with an
                 explanatory Reason= note, quarantine it, and notify. No
                 further automated fix attempts happen for this category
                 until a human resumes the node.
       - No   -> this is a first sighting. Run read-only diagnostics
                 (diagnostics.py). If the category is one of the small set
                 considered safe to self-heal (transient "not responding" /
                 "kill task failed" cases), attempt the fix and, if it
                 succeeds, resume the node with a note describing what was
                 done. Otherwise leave the node exactly as Slurm left it and
                 surface the diagnostic report for a human.
  5. For nodes that are no longer in a problem state, clear any quarantine
     -- an admin resuming the node resets the recurrence tracking for it.

This is deliberately conservative: the only actions the agent ever takes
without a human in the loop are (a) resuming a node it just fixed itself for
a known-transient issue, and (b) force-draining a node that has proven,
by recurring, that whatever already happened to it (an admin's own fix, the
agent's own fix, or Slurm's health check) did not actually resolve the
problem.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List, Optional

from . import diagnostics, remediation
from .classifier import CATEGORY_INFO, classify
from .history import History
from .models import Category, Decision, DiagnosticReport, NodeState
from .notify import Notifier
from .slurm_client import SlurmClient

log = logging.getLogger("slurm_monitor.agent")


def format_report(report: DiagnosticReport) -> str:
    lines = [
        f"NODE DIAGNOSTIC: {report.node}",
        "-" * 34,
        f"Category:    {report.category.value}",
        f"Reason:      {report.reason}",
        "",
        "Probable Cause",
        "-" * 34,
        report.probable_cause,
        "",
        "Recommended Actions",
        "-" * 34,
    ]
    for i, action in enumerate(report.recommended_actions, 1):
        lines.append(f"{i}. {action}")
    lines.append("")
    lines.append(f"Confidence: {report.confidence}")
    return "\n".join(lines)


def build_drain_note(category: Category, reason: str, occurrence_count: int,
                      first_seen: datetime, now: datetime, source: str = "slurm-monitor") -> str:
    title = CATEGORY_INFO[category]["title"]
    return (
        f"AUTO-DRAIN by {source}: recurring '{title}' detected {occurrence_count}x "
        f"within 24h (first={first_seen.isoformat()}Z latest={now.isoformat()}Z). "
        f"Last raw reason: '{reason[:120]}'. Automated remediation suspended pending "
        f"manual investigation; run `slurm-monitor diagnose {'{node}'}` for details, "
        f"then `scontrol update NodeName={'{node}'} State=RESUME` once resolved."
    )


class Agent:
    def __init__(
        self,
        client: SlurmClient,
        history: History,
        notifier: Optional[Notifier] = None,
        remote_exec: Optional[str] = None,
        poll_interval: int = 60,
        recurrence_threshold: int = 2,
    ):
        self.client = client
        self.history = history
        self.notifier = notifier or Notifier(None)
        self.remote_exec = remote_exec
        self.poll_interval = poll_interval
        # number of occurrences within the window (this one included) that
        # triggers a force-drain; 2 = "seen this exact problem twice in 24h"
        self.recurrence_threshold = recurrence_threshold

    def poll_once(self, now: Optional[datetime] = None) -> List[Decision]:
        now = now or datetime.utcnow()
        states = self.client.get_node_states()
        decisions: List[Decision] = []

        for node_state in states:
            decisions.append(self._handle_node(node_state, now))

        return [d for d in decisions if d is not None]

    def _handle_node(self, node_state: NodeState, now: datetime) -> Optional[Decision]:
        node = node_state.name

        if not node_state.is_problem:
            if self.history.is_quarantined_any(node):
                self.history.clear_quarantine(node)
                log.info("node %s recovered; cleared quarantine", node)
            return None

        category = classify(node_state.reason)

        if category is Category.ADMIN_DRAIN:
            log.debug("node %s: admin-initiated drain, leaving alone", node)
            return Decision(node, category, "ignore", "admin-initiated drain; agent does not act on these")

        if self.history.is_quarantined(node, category.value):
            return Decision(
                node, category, "manual_review",
                "already force-drained for this recurring issue; awaiting manual `State=RESUME`",
            )

        prior = self.history.prior_occurrences(node, category.value, now)
        occurrence_count = len(prior) + 1

        if occurrence_count >= self.recurrence_threshold:
            first_seen = prior[0].detected_at if prior else now
            note = build_drain_note(category, node_state.reason, occurrence_count, first_seen, now)
            note = note.replace("{node}", node)
            self.history.record(node, category.value, node_state.reason, now, action="auto_drained")
            self.history.mark_quarantined(node, category.value, note, now)
            drained = remediation.force_drain(self.client, node, note)
            self.notifier.notify(
                f"[slurm-monitor] force-drained {node}",
                note if drained else f"{note}\n\n(WARNING: scontrol drain command failed, check logs)",
            )
            return Decision(node, category, "force_drain", note, occurrences_in_window=occurrence_count)

        # first sighting within the window: record, diagnose, maybe self-heal
        self.history.record(node, category.value, node_state.reason, now, action="observed")
        report = diagnostics.diagnose(node_state, category, self.client, self.remote_exec)

        if report.auto_fixable:
            fix = remediation.attempt_fix(report, self.client, self.remote_exec)
            if fix.attempted and fix.succeeded:
                note = f"auto-resumed by slurm-monitor after applying fix: {fix.detail}"
                remediation.resume(self.client, node, note)
                return Decision(node, category, "resume", note)
            if fix.attempted:
                log.warning("auto-fix attempted but failed for %s/%s: %s", node, category.value, fix.detail)

        self.notifier.notify(f"[slurm-monitor] {node} needs review: {CATEGORY_INFO[category]['title']}",
                              format_report(report))
        return Decision(node, category, "manual_review", format_report(report))

    def run_forever(self) -> None:
        log.info("slurm-monitor agent starting (poll_interval=%ss, recurrence_threshold=%s, dry_run=%s)",
                  self.poll_interval, self.recurrence_threshold, self.client.dry_run)
        while True:
            try:
                decisions = self.poll_once()
                for d in decisions:
                    if d.action != "ignore":
                        log.info("%s: %s (%s)", d.node, d.action, d.category.value)
            except Exception:
                log.exception("poll cycle failed")
            time.sleep(self.poll_interval)
