"""Auto-detect which resource manager's client tools are on this node."""

from __future__ import annotations

import shutil


def detect_resource_manager(preferred: str = "auto") -> str:
    """Returns "slurm", "pbs", or "none". `preferred` overrides detection
    when set to "slurm"/"pbs"/"none" explicitly in chpc.yaml."""
    if preferred in ("slurm", "pbs", "none"):
        return preferred
    if shutil.which("scontrol"):
        return "slurm"
    if shutil.which("pbsnodes"):
        return "pbs"
    return "none"
