"""Run the per-category diagnostic commands from classifier.CATEGORY_INFO and
turn the results into a human-readable DiagnosticReport -- the same shape as
the `coastal-hpc diagnose node047` example this agent is modeled on.

Diagnostics never mutate cluster state; they only run read-only commands
(lscpu, slurmd -C, free -m, nvidia-smi, journalctl, ...) on the node itself
(or the controller, for cluster-wide checks). Missing tools/binaries are
recorded as findings, not fatal errors, since a monitoring box won't have
nvidia-smi and a compute node might not have ipmitool.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from .classifier import CATEGORY_INFO
from .models import Category, DiagnosticReport, NodeState
from .slurm_client import SlurmClient

log = logging.getLogger("slurm_monitor.diagnostics")

RunnerFn = Callable[[str, str], "object"]  # (node, command) -> CommandResult-like


def _default_runner(client: SlurmClient, remote_exec: Optional[str]):
    """Build a function that runs a diagnostic command, optionally over SSH
    onto the target node when the agent isn't running on the node itself."""

    def run(node: str, command: str):
        if remote_exec:
            full = remote_exec.format(node=node, command=command)
        else:
            full = command
        return client.run(full)

    return run


def diagnose(node_state: NodeState, category: Category, client: SlurmClient,
             remote_exec: Optional[str] = None) -> DiagnosticReport:
    """Execute the diagnostic checks for `category` against `node_state.name`
    and assemble a report with a probable cause + recommended actions."""
    info = CATEGORY_INFO[category]
    runner = _default_runner(client, remote_exec)

    checks = {}
    for cmd in info["checks"]:
        result = runner(node_state.name, cmd)
        output = getattr(result, "stdout", "") or getattr(result, "stderr", "")
        checks[cmd] = output.strip() or "(no output / command unavailable)"

    probable_cause, actions, confidence = _analyze(category, node_state, checks)

    return DiagnosticReport(
        node=node_state.name,
        category=category,
        reason=node_state.reason,
        checks=checks,
        probable_cause=probable_cause,
        recommended_actions=actions,
        confidence=confidence,
        auto_fixable=info["auto_fixable"],
    )


def _analyze(category: Category, node_state: NodeState, checks: dict):
    """Very small rule engine turning raw check output into a probable cause
    and a numbered action list. Deliberately conservative: when signal is
    thin it says so at LOW confidence rather than guessing."""

    if category is Category.LOW_REAL_MEMORY:
        slurmd_c = checks.get("slurmd -C", "")
        m = re.search(r"RealMemory=(\d+)", slurmd_c)
        detected = m.group(1) if m else None
        cfg = node_state.raw.get("RealMemory")
        cause = "Configured RealMemory exceeds the memory reported by slurmd."
        if detected and cfg:
            cause += f" Configured={cfg} MB vs detected={detected} MB."
        return cause, [
            "Verify with: slurmd -C",
            "Check physical memory: dmidecode --type memory",
            "If hardware is healthy, lower RealMemory in slurm.conf (leave headroom, "
            "don't configure right up to the detected boundary).",
            "scontrol reconfigure",
            "Verify node health, then: scontrol update NodeName=<node> State=RESUME",
        ], "HIGH" if detected else "MEDIUM"

    if category is Category.LOW_CPU_TOPOLOGY:
        return (
            "CPU topology (sockets/cores/threads) reported by slurmd does not match "
            "the NodeName definition in slurm.conf.",
            [
                "Compare: lscpu vs slurmd -C vs the NodeName= line in slurm.conf",
                "Correct CPUs/Sockets/CoresPerSocket/ThreadsPerCore in slurm.conf",
                "scontrol reconfigure",
                "scontrol update NodeName=<node> State=RESUME",
            ],
            "MEDIUM",
        )

    if category is Category.NOT_RESPONDING:
        slurmd_status = checks.get("systemctl status slurmd", "")
        down = "inactive" in slurmd_status.lower() or "dead" in slurmd_status.lower()
        cause = "slurmd is not answering the controller (service down, network, or auth issue)."
        return cause, [
            "systemctl status slurmd ; journalctl -u slurmd",
            "Check network/DNS/firewall between node and controller",
            "systemctl status munge ; munge -n | unmunge",
            "timedatectl / chronyc tracking (clock skew breaks munge auth)",
            "systemctl restart slurmd once the underlying issue is fixed",
        ], "MEDIUM" if down else "LOW"

    if category is Category.KILL_TASK_FAILED:
        return (
            "slurmd could not clean up a job's processes/cgroup after completion.",
            [
                "ps -ef ; systemd-cgls to find leftover processes",
                "Manually kill leftovers and clear the stale cgroup",
                "Investigate task/cgroup plugin config and job's own cleanup behavior",
                "Do not repeatedly resume without finding the root process -- it will just recur.",
            ],
            "LOW",
        )

    if category in (Category.PROLOG_FAILED, Category.EPILOG_FAILED):
        which = "Prolog" if category is Category.PROLOG_FAILED else "Epilog"
        return (
            f"{which} script exited non-zero.",
            [
                "Inspect slurmctld.log and node journalctl -u slurmd around the failure time",
                f"Run the {which} script by hand on the node to reproduce",
                "Check for permissions, missing directories, failed mounts, or hung commands",
            ],
            "LOW",
        )

    if category is Category.UNEXPECTED_REBOOT:
        return (
            "Node rebooted without being told to by Slurm.",
            [
                "last -x ; journalctl --list-boots ; journalctl -b -1",
                "ipmitool sel list for CATERR/ECC/thermal/power/watchdog events",
                "Do not resume until the reboot cause is understood -- it may hide a hardware fault.",
            ],
            "LOW",
        )

    if category is Category.GRES_MISMATCH:
        return (
            "Number/type of GPUs Slurm expects (gres.conf) does not match what slurmd/nvidia-smi report.",
            [
                "nvidia-smi -L ; slurmd -G",
                "lspci | grep -i nvidia ; dmesg | grep -i -E 'nvrm|xid'",
                "Reconcile gres.conf device mapping with actual hardware",
            ],
            "MEDIUM",
        )

    if category is Category.GPU_FAILURE:
        xid = checks.get("journalctl -k | grep -i xid", "")
        return (
            "GPU driver/hardware fault (Xid/ECC event) detected." if xid else
            "Possible GPU fault; no Xid events captured in this pass.",
            [
                "nvidia-smi ; dmesg -T | grep -i -E 'nvrm|xid'",
                "Classify the Xid code severity before resuming",
                "Reset/reload the GPU driver, or reboot/RMA depending on fault class",
                "Do not resume purely because nvidia-smi currently runs clean.",
            ],
            "MEDIUM" if xid else "LOW",
        )

    if category is Category.FILESYSTEM:
        return (
            "A required mount (NFS/Lustre/GPFS/local) is degraded or unavailable.",
            [
                "mount ; df -h ; df -i",
                "ps axo stat,pid,user,comm,wchan:40 | awk '$1 ~ /^D/'  (stuck-I/O processes)",
                "Restore the filesystem/mount before resuming",
            ],
            "LOW",
        )

    if category is Category.OUT_OF_MEMORY:
        return (
            "Kernel OOM killer fired, likely from a job exceeding its memory request.",
            [
                "dmesg -T | grep -i 'out of memory'",
                "Correct the offending job's --mem request, or investigate system memory pressure",
            ],
            "LOW",
        )

    if category is Category.HEALTH_CHECK:
        return (
            "HealthCheckProgram intentionally drained the node -- treat as a real hardware/OS finding.",
            ["Inspect the health-check script's own log output on the node"],
            "LOW",
        )

    if category is Category.ADMIN_DRAIN:
        return (
            "Node was drained explicitly by an administrator, not by an automated condition.",
            ["Leave as-is; this agent will not touch admin-initiated drains."],
            "HIGH",
        )

    return (
        f"Reason text did not match a known pattern: {node_state.reason!r}",
        ["scontrol show node " + node_state.name, "Investigate manually; consider adding a classifier rule."],
        "LOW",
    )
