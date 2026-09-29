"""Manages the local directory of normalized vulnerability-feed files.
One file per (os_family, major_version) -- e.g. `rhel9.json`,
`windows11.json` -- each carrying its own fetch date and source URL,
so `list_feeds()`/`age_days()` can tell you (and the interactive
update prompt can decide) how stale each one is without needing a
separate manifest that could drift out of sync with the files
themselves.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .schema import SCHEMA_VERSION, NormalizedVuln

DEFAULT_FEED_DIR = Path(__file__).resolve().parent.parent / "feed_data"


@dataclass
class FeedInfo:
    os_family: str
    os_major_version: int
    fetched_at: str
    source_url: str
    vuln_count: int
    path: Path

    def age_days(self) -> int:
        fetched = datetime.fromisoformat(self.fetched_at)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - fetched).days


def _feed_filename(os_family: str, os_major_version: int) -> str:
    return f"{os_family}{os_major_version}.json"


def save_feed(
    feed_dir: Path,
    os_family: str,
    os_major_version: int,
    vulns: list[NormalizedVuln],
    source_url: str,
) -> Path:
    feed_dir.mkdir(parents=True, exist_ok=True)
    path = feed_dir / _feed_filename(os_family, os_major_version)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "os_family": os_family,
        "os_major_version": os_major_version,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "vulns": [v.to_dict() for v in vulns],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_feed(feed_dir: Path, os_family: str, os_major_version: int) -> list[NormalizedVuln]:
    path = feed_dir / _feed_filename(os_family, os_major_version)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [NormalizedVuln.from_dict(v) for v in data.get("vulns", [])]


def get_feed_info(feed_dir: Path, os_family: str, os_major_version: int) -> FeedInfo | None:
    path = feed_dir / _feed_filename(os_family, os_major_version)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return FeedInfo(
        os_family=data["os_family"],
        os_major_version=data["os_major_version"],
        fetched_at=data["fetched_at"],
        source_url=data.get("source_url", ""),
        vuln_count=len(data.get("vulns", [])),
        path=path,
    )


def list_feeds(feed_dir: Path) -> list[FeedInfo]:
    if not feed_dir.exists():
        return []
    infos = []
    for path in sorted(feed_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            infos.append(FeedInfo(
                os_family=data["os_family"],
                os_major_version=data["os_major_version"],
                fetched_at=data["fetched_at"],
                source_url=data.get("source_url", ""),
                vuln_count=len(data.get("vulns", [])),
                path=path,
            ))
        except (json.JSONDecodeError, KeyError):
            continue  # not one of ours / corrupt -- skip rather than fail the whole listing
    return infos
