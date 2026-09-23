"""The check/decide/act loop.

Every cycle: reconcile with the resource manager (an admin resuming the
node manually always wins and resets our bookkeeping), run every check
whose hostmask matches this node, debounce failures, and drain -- with a
reason and recovery instructions -- only once a check has failed
`failure_threshold` consecutive cycles. chpc never auto-resumes a node on
its own unless a specific check name is explicitly opted into
`auto_resume_categories`; by default a human always closes the loop.
"""

from __future__ import annotations

import fnmatch
import logging
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from . import baseline as baseline_mod
from . import recovery
from .checks.base import CheckContext
from .checks.builtin import BUILTIN_CHECKS
from .checks.parser import parse_file
from .config import Config
from .cpuaffinity import pin_to_cores
from .state import State

log = logging.getLogger("chpc.daemon")


@dataclass
class Action:
    check_key: str
    check_name: str
    ok: bool
    detail: str
    consecutive_fails: int
    # ok | monitoring | drain | drain_failed | already_drained | resume | recovered_manual | error
    action: str
    reason: str = ""


class Daemon:
    def __init__(self, config: Config, backend, state: State, hostname: Optional[str] = None,
                 node: Optional[str] = None, ctx_overrides: Optional[dict] = None):
        self.config = config
        self.backend = backend
        self.state = state
        self.hostname = hostname or socket.gethostname()
        self.node = node or self.hostname
        self._ctx_overrides = ctx_overrides or {}

    def build_context(self, baseline: dict) -> CheckContext:
        kwargs = dict(hostname=self.hostname, baseline=baseline,
                       command_timeout=self.config.command_timeout)
        kwargs.update(self._ctx_overrides)
        return CheckContext(**kwargs)

    def load_specs(self):
        return parse_file(self.config.checks_file)

    def run_once(self, now: Optional[datetime] = None) -> List[Action]:
        now = now or datetime.utcnow()
        baseline_data = baseline_mod.load(self.config.baseline_file)
        ctx = self.build_context(baseline_data)

        rm_drained = self.backend.is_drained(self.node) if self.backend else None
        if rm_drained is False and self.state.active_drains():
            log.info("%s: resource manager shows node no longer drained; clearing chpc state",
                      self.node)
            self.state.clear_all_drained()

        actions: List[Action] = []
        try:
            specs = self.load_specs()
        except (OSError, ValueError) as exc:
            log.error("failed to load checks file %s: %s", self.config.checks_file, exc)
            return [Action("", "", False, str(exc), 0, "error")]

        for spec in specs:
            if not fnmatch.fnmatch(self.hostname.lower(), spec.hostmask.lower()):
                continue
            actions.append(self._evaluate(spec, ctx, now))

        return actions

    def _evaluate(self, spec, ctx: CheckContext, now: datetime) -> Action:
        checker = BUILTIN_CHECKS.get(spec.name)
        if checker is None:
            log.warning("unknown check %r (from %s); skipping", spec.name, spec.raw)
            return Action(spec.key, spec.name, False, f"unknown check {spec.name!r}", 0, "error")

        try:
            result = checker(spec.args, ctx)
            result_ok, result_detail = result.ok, result.detail
        except Exception as exc:  # a broken check must never take the daemon down with it
            log.exception("check %s raised", spec.key)
            result_ok, result_detail = False, f"check raised {exc!r}"

        consecutive = self.state.record_result(spec.key, spec.name, result_ok, result_detail, now)
        already_active = self.state.is_active(spec.key)

        if result_ok:
            if already_active:
                if spec.name in self.config.auto_resume_categories:
                    resumed = self.backend.resume(self.node) if self.backend else False
                    if resumed:
                        self.state.clear_drained(spec.key)
                        return Action(spec.key, spec.name, True, result_detail, 0, "resume")
                return Action(spec.key, spec.name, True, result_detail, consecutive, "recovered_manual")
            return Action(spec.key, spec.name, True, result_detail, consecutive, "ok")

        if already_active:
            return Action(spec.key, spec.name, False, result_detail, consecutive, "already_drained")

        if consecutive >= self.config.failure_threshold:
            reason = recovery.build_reason(spec.name, result_detail, consecutive, self.node)
            drained = self.backend.drain(self.node, reason) if self.backend else False
            self.state.mark_drained(spec.key, spec.name, reason, now)
            self._log_instructions(spec.name, result_detail)
            return Action(spec.key, spec.name, False, result_detail, consecutive,
                          "drain" if drained else "drain_failed", reason)

        return Action(spec.key, spec.name, False, result_detail, consecutive, "monitoring")

    def _log_instructions(self, check_name: str, detail: str) -> None:
        try:
            self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.log_file, "a") as f:
                f.write(f"\n=== {datetime.utcnow().isoformat()}Z DRAIN: {check_name} ===\n")
                f.write(recovery.build_instructions(check_name, detail))
                f.write("\n")
        except OSError as exc:
            log.warning("could not write instructions to %s: %s", self.config.log_file, exc)

    def run_forever(self) -> None:
        pin_to_cores(self.config.cpu_affinity)
        log.info("chpc daemon starting on %s (interval=%ss, threshold=%s, dry_run=%s)",
                  self.hostname, self.config.check_interval, self.config.failure_threshold,
                  self.config.dry_run)
        while True:
            try:
                for a in self.run_once():
                    if a.action != "ok":
                        log.info("%s: %s (%s)", a.check_name, a.action, a.detail)
            except Exception:
                log.exception("check cycle failed")
            time.sleep(self.config.check_interval)
