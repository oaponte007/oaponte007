"""Shared dataclasses passed between the collector, classifier, history and
remediation layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Category(str, Enum):
    LOW_CPU_TOPOLOGY = "low_cpu_topology"
    LOW_REAL_MEMORY = "low_real_memory"
    INVALID_REGISTRATION = "invalid_registration"
    NOT_RESPONDING = "not_responding"
    KILL_TASK_FAILED = "kill_task_failed"
    PROLOG_FAILED = "prolog_failed"
    EPILOG_FAILED = "epilog_failed"
    UNEXPECTED_REBOOT = "unexpected_reboot"
    CONFIG_HARDWARE_MISMATCH = "config_hardware_mismatch"
    GRES_MISMATCH = "gres_mismatch"
    GPU_FAILURE = "gpu_failure"
    FILESYSTEM = "filesystem"
    HEALTH_CHECK = "health_check"
    OUT_OF_MEMORY = "out_of_memory"
    ADMIN_DRAIN = "admin_drain"
    UNKNOWN = "unknown"


@dataclass
class NodeState:
    """A single point-in-time reading of a node's Slurm state."""

    name: str
    state: str  # raw State= value, e.g. "DRAINED", "DOWN*", "IDLE"
    reason: str  # raw Reason= value (may be empty)
    reason_set_at: Optional[datetime] = None
    reason_set_by: Optional[str] = None
    cfg_tres: str = ""
    alloc_tres: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def is_problem(self) -> bool:
        base = self.state.rstrip("*").upper()
        return base in {"DRAIN", "DRAINED", "DRAINING", "DOWN", "FAIL", "FAILING"}


@dataclass
class Occurrence:
    """One recorded (node, category) problem event, persisted to history."""

    node: str
    category: str
    reason: str
    detected_at: datetime
    action: str = "observed"  # observed | auto_fixed | auto_drained | already_drained
    id: Optional[int] = None


@dataclass
class DiagnosticReport:
    node: str
    category: Category
    reason: str
    checks: dict = field(default_factory=dict)  # command -> output/error
    probable_cause: str = ""
    recommended_actions: list = field(default_factory=list)
    confidence: str = "LOW"  # LOW | MEDIUM | HIGH
    auto_fixable: bool = False


@dataclass
class Decision:
    """What the agent decided to do about a node, and why."""

    node: str
    category: Category
    action: str  # "ignore" | "attempt_fix" | "resume" | "force_drain" | "manual_review"
    note: str = ""
    occurrences_in_window: int = 1


@dataclass
class ActionLogEntry:
    """One row of the persistent audit trail -- every decision the agent
    ever made, for admins to review periodically (`slurm-monitor log`)."""

    ts: datetime
    node: str
    category: str
    action: str
    reason: str
    note: str
    success: Optional[bool]
    occurrences_in_window: int
    id: Optional[int] = None
