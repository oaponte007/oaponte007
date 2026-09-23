"""Pin the running process to a fixed set of CPU cores.

This is the real enforcement mechanism -- a plain `sched_setaffinity()`
syscall, which behaves identically on RHEL/Rocky 8, 9, and 10 regardless of
systemd version or cgroup hierarchy. Child processes chpc spawns (df,
nvidia-smi, scontrol, pbsnodes, a `command` check's shell) inherit the same
affinity mask across fork/exec, so the whole daemon -- checks included --
stays on the configured core(s).

We deliberately do NOT depend on systemd's cgroup-based `AllowedCPUs=` as
the primary mechanism: it needs the unified (v2) cgroup hierarchy and
systemd >= 244, and RHEL/Rocky 8 ships systemd 239 on cgroup v1 by default,
where `AllowedCPUs=` is silently ineffective. `CPUAffinity=` in the systemd
unit (see systemd/chpc.service) is a second, independent layer using the
same syscall systemd-side, supported on all three targets.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Set

log = logging.getLogger("chpc.cpuaffinity")


def pin_to_cores(cores: Iterable[int]) -> bool:
    """Best-effort pin of the current process to `cores`. Returns True if
    the affinity was actually applied. Never raises -- a node health checker
    that crashes on startup because pinning failed defeats its own purpose."""
    core_set: Set[int] = set(cores)
    if not core_set:
        log.warning("no cpu_affinity cores configured; running unpinned")
        return False

    if not hasattr(os, "sched_setaffinity"):
        log.warning("os.sched_setaffinity unavailable on this platform; running unpinned")
        return False

    try:
        available = os.sched_getaffinity(0)
    except OSError as exc:
        log.warning("could not read current CPU affinity: %s; running unpinned", exc)
        return False

    invalid = core_set - available
    if invalid:
        log.warning("requested core(s) %s not present on this host (available: %s); "
                     "falling back to the intersection", sorted(invalid), sorted(available))
        core_set &= available
    if not core_set:
        log.error("no requested cpu_affinity core is available on this host; running unpinned")
        return False

    try:
        os.sched_setaffinity(0, core_set)
    except OSError as exc:
        log.warning("sched_setaffinity failed (%s); running unpinned. On some containers "
                     "this needs no special capability, but a restrictive seccomp profile "
                     "can still block it.", exc)
        return False

    log.info("pinned to CPU core(s): %s", sorted(core_set))
    return True
