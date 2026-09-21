"""Classify a Slurm node Reason= string into a known problem Category.

The rules below encode the common-issue table the agent was designed around,
but classification is deliberately just a prioritized list of (regex,
category) pairs -- add a line here to teach the agent a new failure mode
without touching any other module. Anything that matches nothing falls back
to Category.UNKNOWN, which still goes through the full observe/diagnose/
recur-within-24h pipeline; it just gets a generic diagnostic pass and never
an automated fix.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .models import Category

# Order matters: first match wins, so put more specific patterns first.
_RULES: List[Tuple[re.Pattern, Category]] = [
    (re.compile(r"low\s+socket.*core.*thread|low\s+cpus", re.I), Category.LOW_CPU_TOPOLOGY),
    (re.compile(r"low\s+realmemory|memory.*insufficient", re.I), Category.LOW_REAL_MEMORY),
    (re.compile(r"gres/gpu|gres\s+mismatch|gres.*count", re.I), Category.GRES_MISMATCH),
    (re.compile(r"xid|ecc|nvrm|gpu.*(fail|error|fell off|lost)", re.I), Category.GPU_FAILURE),
    (re.compile(r"invalid\s+argument|registration\s+fail|node\s+config.*differ", re.I), Category.INVALID_REGISTRATION),
    (re.compile(r"not\s+responding|no\s+response|node\s+is\s+not\s+responding", re.I), Category.NOT_RESPONDING),
    (re.compile(r"kill\s+task\s+failed|unkillable\s+process", re.I), Category.KILL_TASK_FAILED),
    (re.compile(r"prolog", re.I), Category.PROLOG_FAILED),
    (re.compile(r"epilog", re.I), Category.EPILOG_FAILED),
    (re.compile(r"reboot", re.I), Category.UNEXPECTED_REBOOT),
    (re.compile(r"config.*differ|hardware.*differ|topology.*differ", re.I), Category.CONFIG_HARDWARE_MISMATCH),
    (re.compile(r"file\s*system|nfs|lustre|gpfs|mount", re.I), Category.FILESYSTEM),
    (re.compile(r"health\s*check|healthcheck", re.I), Category.HEALTH_CHECK),
    (re.compile(r"out\s+of\s+memory|oom", re.I), Category.OUT_OF_MEMORY),
    (re.compile(r"admin|by request|manually drain", re.I), Category.ADMIN_DRAIN),
]

# Metadata used both for diagnostics and for deciding whether an automated
# fix is even worth attempting. Anything hardware-adjacent is deliberately
# marked not auto-fixable: the agent should never silently paper over a
# potential hardware fault by resuming the node itself.
CATEGORY_INFO = {
    Category.LOW_CPU_TOPOLOGY: {
        "title": "CPU topology mismatch",
        "auto_fixable": False,
        "checks": ["lscpu", "slurmd -C"],
    },
    Category.LOW_REAL_MEMORY: {
        "title": "Low RealMemory",
        "auto_fixable": False,
        "checks": ["slurmd -C", "free -m", "grep MemTotal /proc/meminfo"],
    },
    Category.INVALID_REGISTRATION: {
        "title": "Invalid argument / registration failure",
        "auto_fixable": False,
        "checks": ["slurmd -C"],
    },
    Category.NOT_RESPONDING: {
        "title": "Node not responding",
        "auto_fixable": True,
        "checks": ["systemctl status slurmd", "munge -n | unmunge", "timedatectl"],
    },
    Category.KILL_TASK_FAILED: {
        "title": "Kill task failed / job cleanup failure",
        "auto_fixable": True,
        "checks": ["ps -ef", "systemd-cgls"],
    },
    Category.PROLOG_FAILED: {
        "title": "Prolog failed",
        "auto_fixable": False,
        "checks": ["journalctl -u slurmd --since -1hour"],
    },
    Category.EPILOG_FAILED: {
        "title": "Epilog failed",
        "auto_fixable": False,
        "checks": ["journalctl -u slurmd --since -1hour"],
    },
    Category.UNEXPECTED_REBOOT: {
        "title": "Node unexpectedly rebooted",
        "auto_fixable": False,
        "checks": ["last -x", "journalctl --list-boots", "ipmitool sel list"],
    },
    Category.CONFIG_HARDWARE_MISMATCH: {
        "title": "Node configuration differs from hardware",
        "auto_fixable": False,
        "checks": ["slurmd -C"],
    },
    Category.GRES_MISMATCH: {
        "title": "GPU/GRES mismatch",
        "auto_fixable": False,
        "checks": ["nvidia-smi -L", "slurmd -G"],
    },
    Category.GPU_FAILURE: {
        "title": "GPU failure",
        "auto_fixable": False,
        "checks": ["nvidia-smi", "dmesg -T | grep -i -E 'nvrm|xid'", "journalctl -k | grep -i xid"],
    },
    Category.FILESYSTEM: {
        "title": "Filesystem/storage problem",
        "auto_fixable": False,
        "checks": ["mount", "df -h", "df -i", "nfsstat"],
    },
    Category.HEALTH_CHECK: {
        "title": "Hardware/OS health check drain",
        "auto_fixable": False,
        "checks": ["journalctl -u slurmd --since -1hour"],
    },
    Category.OUT_OF_MEMORY: {
        "title": "Out of memory related failure",
        "auto_fixable": False,
        "checks": ["dmesg -T | grep -i 'out of memory'"],
    },
    Category.ADMIN_DRAIN: {
        "title": "Administrator-initiated drain",
        "auto_fixable": False,
        "checks": [],
    },
    Category.UNKNOWN: {
        "title": "Unclassified drain reason",
        "auto_fixable": False,
        "checks": ["scontrol show node"],
    },
}


def classify(reason: str) -> Category:
    """Map a raw Slurm Reason= string to a Category. Empty/blank -> UNKNOWN."""
    if not reason or not reason.strip():
        return Category.UNKNOWN
    for pattern, category in _RULES:
        if pattern.search(reason):
            return category
    return Category.UNKNOWN
