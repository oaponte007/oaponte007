"""The normalized vulnerability-feed record every source (Red Hat OVAL,
MSRC's Security Update Guide export, or anything else added later)
gets converted into. The matcher (matcher.py) only ever looks at this
shape -- it never parses a vendor format directly -- so adding a new
feed source later means writing one more normalizer, not touching the
matching logic at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1

SEVERITIES = ("critical", "high", "medium", "low", "unknown")
_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def severity_sort_key(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, _SEVERITY_RANK["unknown"])


@dataclass
class AffectedPackage:
    """A Linux (RPM) package this advisory says is fixed at a given
    version -- anything strictly older is vulnerable.
    """
    name: str
    fixed_evr: str  # epoch:version-release, e.g. "1:3.0.7-27.el9_5"
    arch: str = "*"  # "*" matches any arch


@dataclass
class NormalizedVuln:
    id: str  # e.g. "RHSA-2024:1234" or "MSRC-CVE-2024-30080"
    title: str
    severity: str  # one of SEVERITIES
    description: str
    os_family: str  # "rhel" | "rocky" | "windows"
    os_major_versions: list[int]  # e.g. [8, 9] -- which major versions this applies to
    source: str  # "redhat-oval" | "msrc-csv"
    cve_ids: list[str] = field(default_factory=list)
    published: str = ""  # ISO date string, best-effort
    # exactly one of these is populated, depending on os_family
    affected_packages: list[AffectedPackage] = field(default_factory=list)  # linux
    # windows: cumulative updates make "is this KB installed?" fragile --
    # a later cumulative update supersedes an earlier KB number without
    # necessarily reporting it, so the actual comparison key is the OS
    # build/revision number (e.g. "22631.3805"); resolved_by_kb is kept
    # only as a human-readable label ("fixed by KB5031354 or later").
    resolved_by_build: str | None = None  # e.g. "22631.3805" -- dotted ints, compared as a tuple
    resolved_by_kb: str | None = None
    windows_release: str | None = None  # e.g. "23H2" -- which feature update this build number belongs to

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "description": self.description,
            "os_family": self.os_family,
            "os_major_versions": self.os_major_versions,
            "source": self.source,
            "cve_ids": self.cve_ids,
            "published": self.published,
            "affected_packages": [
                {"name": p.name, "fixed_evr": p.fixed_evr, "arch": p.arch}
                for p in self.affected_packages
            ],
            "resolved_by_build": self.resolved_by_build,
            "resolved_by_kb": self.resolved_by_kb,
            "windows_release": self.windows_release,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NormalizedVuln":
        return cls(
            id=data["id"],
            title=data["title"],
            severity=data["severity"],
            description=data["description"],
            os_family=data["os_family"],
            os_major_versions=list(data["os_major_versions"]),
            source=data["source"],
            cve_ids=list(data.get("cve_ids", [])),
            published=data.get("published", ""),
            affected_packages=[
                AffectedPackage(name=p["name"], fixed_evr=p["fixed_evr"], arch=p.get("arch", "*"))
                for p in data.get("affected_packages", [])
            ],
            resolved_by_build=data.get("resolved_by_build"),
            resolved_by_kb=data.get("resolved_by_kb"),
            windows_release=data.get("windows_release"),
        )
