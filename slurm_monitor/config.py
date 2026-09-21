"""YAML configuration loading with sane, safe-by-default values."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_DB_PATH = Path("/var/lib/slurm-monitor/history.db")


@dataclass
class Config:
    dry_run: bool = True
    poll_interval: int = 60
    recurrence_window_hours: int = 24
    recurrence_threshold: int = 2
    db_path: Path = DEFAULT_DB_PATH
    webhook_url: Optional[str] = None
    remote_exec: Optional[str] = None  # e.g. "ssh {node} -- {command}"
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: Optional[str]) -> "Config":
        if not path:
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        if "db_path" in filtered:
            filtered["db_path"] = Path(filtered["db_path"])
        return cls(**filtered)
