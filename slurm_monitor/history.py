"""Persistent occurrence history for (node, category) problem events, plus
the full action audit log.

The `occurrences`/`quarantine` tables are what make the 24-hour recurrence
rule possible across restarts of the agent process: every time a node is
observed with a classified problem, we record it here, then ask "has this
exact node+category combination fired before within the trailing `window`?"
before deciding whether to attempt a fix again or force-drain the node
instead.

The `actions` table is a separate, append-only audit trail of *every*
decision the agent makes (ignore/resume/manual_review/force_drain), meant
for admins to review periodically via `slurm-monitor log`/`report` --
especially useful for spotting patterns across nodes that a single
in-the-moment log line would miss (e.g. "these three GPU nodes have all
needed manual review for GRES mismatches this week").
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional

from .models import ActionLogEntry, Occurrence

DEFAULT_WINDOW = timedelta(hours=24)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node TEXT NOT NULL,
    category TEXT NOT NULL,
    reason TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'observed'
);
CREATE INDEX IF NOT EXISTS idx_occurrences_node_category
    ON occurrences(node, category, detected_at);

CREATE TABLE IF NOT EXISTS quarantine (
    node TEXT NOT NULL,
    category TEXT NOT NULL,
    drained_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    cleared_at TEXT,
    PRIMARY KEY (node, category, drained_at)
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    node TEXT NOT NULL,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    note TEXT NOT NULL,
    success INTEGER,
    occurrences_in_window INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_actions_ts ON actions(ts);
CREATE INDEX IF NOT EXISTS idx_actions_node_ts ON actions(node, ts);
"""


@dataclass
class History:
    """SQLite-backed store. One row per observed problem event.

    A node/category pair is considered "recurring within the window" when
    there are at least 2 rows for it (this observation plus a prior one)
    whose detected_at values both fall inside [now - window, now].
    """

    db_path: Path
    window: timedelta = DEFAULT_WINDOW

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
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

    def record(self, node: str, category: str, reason: str, detected_at: datetime,
               action: str = "observed") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO occurrences (node, category, reason, detected_at, action) "
                "VALUES (?, ?, ?, ?, ?)",
                (node, category, reason, detected_at.isoformat(), action),
            )
            return cur.lastrowid

    def prior_occurrences(self, node: str, category: str, before: datetime) -> List[Occurrence]:
        """All occurrences of this node+category within `window` before `before`."""
        window_start = (before - self.window).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, node, category, reason, detected_at, action FROM occurrences "
                "WHERE node = ? AND category = ? AND detected_at >= ? AND detected_at < ? "
                "ORDER BY detected_at ASC",
                (node, category, window_start, before.isoformat()),
            ).fetchall()
        return [
            Occurrence(id=r[0], node=r[1], category=r[2], reason=r[3],
                       detected_at=datetime.fromisoformat(r[4]), action=r[5])
            for r in rows
        ]

    def is_recurring(self, node: str, category: str, now: datetime) -> bool:
        """True if this node+category has already fired at least once within
        the trailing window, i.e. this new observation would be occurrence #2+."""
        return len(self.prior_occurrences(node, category, now)) >= 1

    def mark_quarantined(self, node: str, category: str, reason: str, at: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quarantine (node, category, drained_at, reason) VALUES (?, ?, ?, ?)",
                (node, category, at.isoformat(), reason),
            )

    def is_quarantined_any(self, node: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM quarantine WHERE node = ? AND cleared_at IS NULL",
                (node,),
            ).fetchone()
        return row is not None

    def is_quarantined(self, node: str, category: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM quarantine WHERE node = ? AND category = ? AND cleared_at IS NULL",
                (node, category),
            ).fetchone()
        return row is not None

    def clear_quarantine(self, node: str, category: Optional[str] = None) -> None:
        """Called when an admin resumes the node -- lets the agent try again
        from a clean slate instead of immediately re-draining it."""
        with self._connect() as conn:
            if category:
                conn.execute(
                    "UPDATE quarantine SET cleared_at = ? WHERE node = ? AND category = ? AND cleared_at IS NULL",
                    (datetime.utcnow().isoformat(), node, category),
                )
            else:
                conn.execute(
                    "UPDATE quarantine SET cleared_at = ? WHERE node = ? AND cleared_at IS NULL",
                    (datetime.utcnow().isoformat(), node),
                )

    def recent_for_node(self, node: str, limit: int = 20) -> List[Occurrence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, node, category, reason, detected_at, action FROM occurrences "
                "WHERE node = ? ORDER BY detected_at DESC LIMIT ?",
                (node, limit),
            ).fetchall()
        return [
            Occurrence(id=r[0], node=r[1], category=r[2], reason=r[3],
                       detected_at=datetime.fromisoformat(r[4]), action=r[5])
            for r in rows
        ]

    # -- action audit log --------------------------------------------------

    def log_action(self, node: str, category: str, action: str, reason: str, note: str,
                    ts: datetime, success: Optional[bool] = None,
                    occurrences_in_window: int = 1) -> int:
        """Append one entry to the permanent audit trail. Called for every
        decision the agent makes, including "ignore" -- admins reviewing the
        log later want the full picture, not just the interesting rows."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO actions (ts, node, category, action, reason, note, success, "
                "occurrences_in_window) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts.isoformat(), node, category, action, reason, note,
                    None if success is None else int(success), occurrences_in_window,
                ),
            )
            return cur.lastrowid

    def query_actions(self, node: Optional[str] = None, category: Optional[str] = None,
                       action: Optional[str] = None, since: Optional[datetime] = None,
                       until: Optional[datetime] = None, limit: int = 200) -> List[ActionLogEntry]:
        """Filtered read of the audit trail, newest first -- backs both
        `slurm-monitor log` and `slurm-monitor report`."""
        clauses, params = [], []
        if node:
            clauses.append("node = ?")
            params.append(node)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if since:
            clauses.append("ts >= ?")
            params.append(since.isoformat())
        if until:
            clauses.append("ts < ?")
            params.append(until.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, ts, node, category, action, reason, note, success, "
                f"occurrences_in_window FROM actions {where} ORDER BY ts DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [
            ActionLogEntry(
                id=r[0], ts=datetime.fromisoformat(r[1]), node=r[2], category=r[3], action=r[4],
                reason=r[5], note=r[6], success=None if r[7] is None else bool(r[7]),
                occurrences_in_window=r[8],
            )
            for r in rows
        ]
