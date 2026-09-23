"""Local SQLite state: per-check debounce counters and which checks chpc
currently believes it has drained the node for. Survives daemon restarts,
same rationale as slurm_monitor's history.py -- debounce counts must not
reset just because the process restarted mid-streak.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS check_state (
    check_key TEXT PRIMARY KEY,
    check_name TEXT NOT NULL,
    consecutive_fails INTEGER NOT NULL DEFAULT 0,
    last_ok INTEGER NOT NULL,
    last_detail TEXT NOT NULL,
    last_checked TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drain_state (
    check_key TEXT PRIMARY KEY,
    check_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    drained_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
"""


@dataclass
class CheckStateRow:
    check_key: str
    check_name: str
    consecutive_fails: int
    last_ok: bool
    last_detail: str
    last_checked: datetime


@dataclass
class DrainStateRow:
    check_key: str
    check_name: str
    reason: str
    drained_at: datetime
    active: bool


class State:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record_result(self, check_key: str, check_name: str, ok: bool, detail: str,
                       ts: datetime) -> int:
        """Upserts the result and returns the resulting consecutive_fails count."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_fails FROM check_state WHERE check_key = ?", (check_key,)
            ).fetchone()
            consecutive = 0 if ok else (row[0] + 1 if row else 1)
            conn.execute(
                "INSERT INTO check_state (check_key, check_name, consecutive_fails, last_ok, "
                "last_detail, last_checked) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(check_key) DO UPDATE SET check_name=excluded.check_name, "
                "consecutive_fails=excluded.consecutive_fails, last_ok=excluded.last_ok, "
                "last_detail=excluded.last_detail, last_checked=excluded.last_checked",
                (check_key, check_name, consecutive, int(ok), detail, ts.isoformat()),
            )
            return consecutive

    def get(self, check_key: str) -> Optional[CheckStateRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT check_key, check_name, consecutive_fails, last_ok, last_detail, "
                "last_checked FROM check_state WHERE check_key = ?", (check_key,)
            ).fetchone()
        if not row:
            return None
        return CheckStateRow(row[0], row[1], row[2], bool(row[3]), row[4], datetime.fromisoformat(row[5]))

    def all_check_states(self) -> List[CheckStateRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT check_key, check_name, consecutive_fails, last_ok, last_detail, "
                "last_checked FROM check_state ORDER BY check_key"
            ).fetchall()
        return [CheckStateRow(r[0], r[1], r[2], bool(r[3]), r[4], datetime.fromisoformat(r[5])) for r in rows]

    def mark_drained(self, check_key: str, check_name: str, reason: str, ts: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO drain_state (check_key, check_name, reason, drained_at, active) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(check_key) DO UPDATE SET reason=excluded.reason, "
                "drained_at=excluded.drained_at, active=1",
                (check_key, check_name, reason, ts.isoformat()),
            )

    def clear_drained(self, check_key: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE drain_state SET active = 0 WHERE check_key = ?", (check_key,))
            conn.execute("UPDATE check_state SET consecutive_fails = 0 WHERE check_key = ?", (check_key,))

    def clear_all_drained(self) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE drain_state SET active = 0")
            conn.execute("UPDATE check_state SET consecutive_fails = 0")

    def is_active(self, check_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM drain_state WHERE check_key = ? AND active = 1", (check_key,)
            ).fetchone()
        return row is not None

    def active_drains(self) -> List[DrainStateRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT check_key, check_name, reason, drained_at, active FROM drain_state "
                "WHERE active = 1 ORDER BY drained_at"
            ).fetchall()
        return [DrainStateRow(r[0], r[1], r[2], datetime.fromisoformat(r[3]), bool(r[4])) for r in rows]

    def get_drain(self, check_key: str) -> Optional[DrainStateRow]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT check_key, check_name, reason, drained_at, active FROM drain_state "
                "WHERE check_key = ?", (check_key,)
            ).fetchone()
        if not row:
            return None
        return DrainStateRow(row[0], row[1], row[2], datetime.fromisoformat(row[3]), bool(row[4]))
