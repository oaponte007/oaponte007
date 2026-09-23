"""Install-time hardware/config discovery.

This is the "requirements set at the beginning of the install" the daemon
was asked for: `chpc install` probes the node once, and the numbers it
finds become the ongoing contract that `check_real_memory`, `check_cpu_count`,
and `check_gpu_count` hold the node to for the rest of its life (until
someone runs `chpc baseline recapture`, e.g. after a deliberate hardware
change).

Every probe reads a real Linux interface (/proc, /sys) rather than shelling
out where possible, which is both faster and behaves identically across
RHEL/Rocky 8, 9, and 10 -- these files have been stable ABI for decades.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

PSEUDO_FSTYPES = {
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
    "pstore", "securityfs", "debugfs", "tracefs", "configfs", "bpf",
    "autofs", "mqueue", "hugetlbfs", "fusectl", "binfmt_misc", "selinuxfs",
}


def _read_mem_total_kb(proc_meminfo: str) -> Optional[int]:
    try:
        for line in Path(proc_meminfo).read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_mounts(proc_mounts: str) -> List[Dict[str, str]]:
    mounts = []
    try:
        for line in Path(proc_mounts).read_text().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            _device, mountpoint, fstype = parts[0], parts[1], parts[2]
            if fstype in PSEUDO_FSTYPES:
                continue
            mounts.append({"path": mountpoint, "fstype": fstype})
    except OSError:
        pass
    return mounts


def _read_interfaces(sys_class_net: str) -> List[str]:
    try:
        return sorted(p.name for p in Path(sys_class_net).iterdir() if p.name != "lo")
    except OSError:
        return []


def _default_gpu_probe() -> List[str]:
    try:
        proc = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def capture(
    proc_meminfo: str = "/proc/meminfo",
    proc_mounts: str = "/proc/mounts",
    sys_class_net: str = "/sys/class/net",
    cpu_count: Optional[int] = None,
    gpu_probe: Optional[Callable[[], List[str]]] = None,
) -> dict:
    """Probe this node and return a baseline dict, ready to serialize."""
    gpu_probe = gpu_probe or _default_gpu_probe
    gpus = gpu_probe()
    return {
        "cpu_count": cpu_count if cpu_count is not None else (os.cpu_count() or 1),
        "real_memory_kb": _read_mem_total_kb(proc_meminfo),
        "gpu_count": len(gpus),
        "gpus": gpus,
        "mounts": _read_mounts(proc_mounts),
        "interfaces": _read_interfaces(sys_class_net),
    }


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# chpc baseline -- captured at install time by `chpc install` /\n"
        "# `chpc baseline recapture`. This is what check_real_memory,\n"
        "# check_cpu_count, and check_gpu_count compare live state against.\n"
        "# Only recapture after a deliberate hardware/config change.\n"
    )
    path.write_text(header + yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def load(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text()) or {}
