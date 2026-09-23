"""chpc (Coastal HPC Node Health Checker): a lightweight, single-core-pinned
daemon that runs on each compute node, evaluates an NHC-style checks file
against a baseline captured at install time, and drains the node through
Slurm or PBS/PBS Pro -- with a reason and concrete recovery instructions --
when a check fails past its debounce threshold.

Targets RHEL/Rocky 8, 9, and 10. See CHPC_MANUAL.md for the OS compatibility
notes (Python version sourcing, cgroup v1 vs v2, SELinux).
"""

__version__ = "0.1.0"
