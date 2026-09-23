"""chpc daemon configuration.

Loaded from /etc/chpc/chpc.yaml (see config/chpc.example.yaml). Every path
defaults under /etc/chpc, /var/lib/chpc, /var/log/chpc -- standard FHS
locations that behave the same on RHEL/Rocky 8, 9, and 10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

DEFAULT_CONFIG_DIR = Path("/etc/chpc")
DEFAULT_STATE_DIR = Path("/var/lib/chpc")
DEFAULT_LOG_DIR = Path("/var/log/chpc")


@dataclass
class Config:
    dry_run: bool = True
    check_interval: int = 60
    # consecutive failed cycles required before chpc actually drains the
    # node -- debounces a single transient blip (a momentary disk spike, a
    # flaky mount) so it doesn't trigger an unnecessary drain.
    failure_threshold: int = 3

    # Cores this process (and everything it shells out to) is pinned to.
    # See cpuaffinity.py for why this is a syscall, not a cgroup setting.
    cpu_affinity: List[int] = field(default_factory=lambda: [0])

    # auto | slurm | pbs | none
    resource_manager: str = "auto"

    checks_file: Path = DEFAULT_CONFIG_DIR / "checks.conf"
    baseline_file: Path = DEFAULT_CONFIG_DIR / "baseline.yaml"
    state_db: Path = DEFAULT_STATE_DIR / "state.db"
    log_file: Path = DEFAULT_LOG_DIR / "chpc.log"
    log_level: str = "INFO"

    # Categories (check names) chpc is allowed to auto-resume once the check
    # passes again, with NO human involved. Empty by default -- chpc always
    # tells you how to fix it and lets you clear it (`chpc resume`); it
    # never quietly declares a node healthy again unless you opt a specific,
    # low-risk check into this list.
    auto_resume_categories: List[str] = field(default_factory=list)

    # Backend command overrides. These are argv fragments, never a shell
    # string -- the reason text is always passed as a single argv element
    # (never interpolated into a shell string), so there is no quoting/
    # injection concern regardless of what an admin puts in these fields.
    slurm_binary: str = "scontrol"
    pbs_binary: str = "pbsnodes"
    pbs_offline_flag: str = "-o"
    pbs_note_flag: str = "-N"
    pbs_clear_flag: str = "-c"

    command_timeout: int = 20

    @classmethod
    def load(cls, path: Optional[str]) -> "Config":
        if not path:
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        for path_field in ("checks_file", "baseline_file", "state_db", "log_file"):
            if path_field in filtered:
                filtered[path_field] = Path(filtered[path_field])
        return cls(**filtered)

    def ensure_dirs(self) -> None:
        for p in (self.checks_file, self.baseline_file, self.state_db, self.log_file):
            p.parent.mkdir(parents=True, exist_ok=True)
