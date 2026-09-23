"""Builds the two things chpc always attaches to a drain: a short Reason=
string for the resource manager, and a longer set of recovery clues for a
human. This is the part that makes a chpc drain self-explanatory instead of
a mystery someone has to reverse-engineer from a raw check name.
"""

from __future__ import annotations

from typing import List

# name -> (title, [ordered recovery steps])
RECOVERY_INFO = {
    "check_real_memory": (
        "Memory reported by the kernel no longer matches the install-time baseline",
        [
            "Compare live vs baseline: `chpc explain check_real_memory` shows both numbers.",
            "Check physical memory: `dmidecode --type memory` (look for a failed/disabled DIMM).",
            "Check for a kernel/BIOS memory-reservation change: `cat /proc/meminfo`, `dmesg | grep -i memory`.",
            "If the hardware change was deliberate (RAM added/removed), run "
            "`chpc baseline recapture` to accept the new baseline instead of resuming forever "
            "against a stale one.",
            "Once resolved: `chpc resume check_real_memory`.",
        ],
    ),
    "check_cpu_count": (
        "Visible CPU count no longer matches the install-time baseline",
        [
            "Compare: `lscpu` vs the baseline (`chpc baseline show`).",
            "Check for a BIOS/firmware change disabling cores, or a hypervisor vCPU change on a VM.",
            "Check kernel boot args for an accidental `nosmp`/`maxcpus=` limit: `cat /proc/cmdline`.",
            "If the change was deliberate, `chpc baseline recapture`.",
            "Once resolved: `chpc resume check_cpu_count`.",
        ],
    ),
    "check_load_average": (
        "Load average per core exceeds the configured ceiling",
        [
            "Find what's running: `top`, `ps aux --sort=-%cpu | head`.",
            "Check for a runaway or stuck process (see check_zombie_processes too).",
            "If this is expected under real job load, raise --max-per-core in checks.conf "
            "rather than resuming repeatedly.",
            "Once resolved: `chpc resume check_load_average`.",
        ],
    ),
    "check_disk_usage": (
        "A monitored filesystem is above its configured usage or inode threshold",
        [
            "Find what's using space: `du -xh --max-depth=2 <path> | sort -rh | head`.",
            "If the detail mentions inodes: find directories with huge file counts instead of "
            "size -- `find <path> -xdev -type d | while read d; do echo $(ls -1 \"$d\" | wc -l) "
            "\"$d\"; done | sort -rn | head` (an inode table can fill even with free bytes, "
            "usually from a job leaving millions of small files behind).",
            "Check for orphaned job scratch data, core dumps, or runaway logs.",
            "Clear space (or inodes) or extend the filesystem, then verify: `df -h <path>` / "
            "`df -i <path>`.",
            "Once resolved: `chpc resume check_disk_usage`.",
        ],
    ),
    "check_dir_size": (
        "A specific directory's own footprint (not just its filesystem) exceeded its configured limit",
        [
            "Find the biggest offenders inside it: `du -xh --max-depth=1 <path> | sort -rh | head`.",
            "This check walks the tree itself, so it also catches a directory outgrowing its "
            "budget on a shared filesystem where the filesystem's overall percent-full wouldn't "
            "isolate it -- e.g. one user's job scratch subdirectory.",
            "Clean up or archive the offending files, or raise the threshold in checks.conf if "
            "the new size is actually expected going forward.",
            "Once resolved: `chpc resume check_dir_size`.",
        ],
    ),
    "check_swap_usage": (
        "Swap usage is above its configured threshold",
        [
            "Check for memory-pressured jobs: `free -h`, `ps aux --sort=-%mem | head`.",
            "A job that should have been OOM-killed instead of swapping usually means "
            "cgroup memory limits aren't applied to it -- check the scheduler's memory cgroup config.",
            "Once resolved: `chpc resume check_swap_usage`.",
        ],
    ),
    "check_mount_present": (
        "An expected filesystem mount is missing or of the wrong type",
        [
            "Check current mounts: `mount | grep <path>`, `cat /proc/mounts`.",
            "For NFS: `showmount -e <server>`, check the server is reachable and exporting.",
            "Check `/etc/fstab` / autofs maps for this mount, then `mount -a` or `systemctl restart autofs`.",
            "Once resolved: `chpc resume check_mount_present`.",
        ],
    ),
    "check_zombie_processes": (
        "Too many zombie (defunct) processes accumulated",
        [
            "Identify them: `ps -eo pid,ppid,state,cmd | awk '$3==\"Z\"'`.",
            "Zombies are cleaned up when their parent reaps them -- find and, if safe, restart "
            "the parent process rather than killing the zombie itself (it's already dead).",
            "If the parent is slurmd/pbs_mom itself, check its logs for a job-cleanup bug.",
            "Once resolved: `chpc resume check_zombie_processes`.",
        ],
    ),
    "check_gpu_count": (
        "Number of GPUs visible to nvidia-smi no longer matches the install-time baseline",
        [
            "Check visibility: `nvidia-smi -L`, `lspci | grep -i nvidia`.",
            "Check for a driver/Xid fault: `dmesg -T | grep -i -E 'nvrm|xid'`.",
            "Check the PCIe link/power state hasn't dropped a card: `nvidia-smi -q | grep -A2 'GPU Link Info'`.",
            "If a GPU was deliberately added/removed, `chpc baseline recapture`.",
            "Once resolved: `chpc resume check_gpu_count`.",
        ],
    ),
    "check_network_interface": (
        "A required network interface is missing or down",
        [
            "Check link state: `ip link show <iface>`, `ethtool <iface>`.",
            "Check the switch port / cable, and NetworkManager or systemd-networkd status: "
            "`nmcli device status` or `networkctl status <iface>`.",
            "Once resolved: `chpc resume check_network_interface`.",
        ],
    ),
    "command": (
        "A site-defined command check failed",
        [
            "Re-run the exact command by hand to see the current output: "
            "`chpc explain command` shows the command line that failed.",
            "This check's recovery steps are whatever your own script documents -- consider "
            "having it print a one-line hint on failure, which chpc will capture in its detail.",
            "Once resolved: `chpc resume command`.",
        ],
    ),
}

DEFAULT_INFO = (
    "Unrecognized check",
    ["Inspect the check definition in checks.conf and its detail output via `chpc explain`."],
)


def title_for(check_name: str) -> str:
    return RECOVERY_INFO.get(check_name, DEFAULT_INFO)[0]


def steps_for(check_name: str) -> List[str]:
    return RECOVERY_INFO.get(check_name, DEFAULT_INFO)[1]


def build_reason(check_name: str, detail: str, consecutive_fails: int, node: str,
                  source: str = "chpc") -> str:
    """Short string for the resource manager's Reason=/note field."""
    title = title_for(check_name)
    return (
        f"[{source}] {check_name}: {title} "
        f"({consecutive_fails}x consecutive). {detail[:160]} "
        f"Run `chpc explain {check_name}` on {node} for recovery steps."
    )


def build_instructions(check_name: str, detail: str) -> str:
    """Full recovery text for `chpc explain` / the local log file."""
    title = title_for(check_name)
    steps = steps_for(check_name)
    lines = [f"CHECK: {check_name}", f"WHY:   {title}", f"LATEST DETAIL: {detail}", "", "RECOVERY STEPS:"]
    lines += [f"  {i}. {s}" for i, s in enumerate(steps, 1)]
    return "\n".join(lines)
