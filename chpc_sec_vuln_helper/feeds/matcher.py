"""Matches collected system state against a loaded list of
NormalizedVuln records. Two independent matching strategies, since
Linux and Windows patching work fundamentally differently:

- **Linux (RPM)**: an advisory names a package + the version that
  fixes it. A package is vulnerable if the installed EVR is strictly
  older than the fixed EVR (rpmver.is_vulnerable).
- **Windows**: cumulative updates make "is KB X installed?" fragile --
  a later cumulative update supersedes an earlier one without
  reporting its number. So this compares the installed OS build's
  revision number against the advisory's minimum fixing build,
  as a dotted-integer tuple, which is monotonic within a feature
  update level (e.g. 22631.3805 fixes something 22631.2861 doesn't).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import rpmver
from .schema import NormalizedVuln


@dataclass
class Match:
    vuln: NormalizedVuln
    matched_on: str  # human-readable: "openssl 1:3.0.7-18.el9 (fixed in 1:3.0.7-27.el9_5)"


def _build_tuple(build: str) -> tuple[int, ...]:
    parts = []
    for chunk in build.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def match_linux(installed_packages: list[dict], vulns: list[NormalizedVuln]) -> list[Match]:
    """installed_packages: [{"name", "epoch", "version", "release", "arch"}, ...]
    as produced by the Linux collector's rpm query.
    """
    by_name: dict[str, list[dict]] = {}
    for pkg in installed_packages:
        by_name.setdefault(pkg["name"], []).append(pkg)

    matches: list[Match] = []
    for vuln in vulns:
        for affected in vuln.affected_packages:
            for pkg in by_name.get(affected.name, []):
                if affected.arch != "*" and pkg.get("arch") not in (affected.arch, "*"):
                    continue
                epoch = pkg.get("epoch") or "0"
                installed_evr = f"{epoch}:{pkg['version']}-{pkg['release']}"
                if rpmver.is_vulnerable(installed_evr, affected.fixed_evr):
                    matches.append(Match(
                        vuln=vuln,
                        matched_on=(
                            f"{affected.name} {installed_evr} "
                            f"(fixed in {affected.fixed_evr})"
                        ),
                    ))
    return matches


def match_windows(installed_build: str, vulns: list[NormalizedVuln]) -> list[Match]:
    """installed_build: e.g. "22631.3737" (CurrentBuildNumber + "." + UBR,
    exactly what the Windows collector reports).
    """
    installed_tuple = _build_tuple(installed_build)
    matches: list[Match] = []
    for vuln in vulns:
        if not vuln.resolved_by_build:
            continue
        fixed_tuple = _build_tuple(vuln.resolved_by_build)
        # Only comparable within the same feature-update build family
        # (major build number matches) -- a build number from a
        # different Windows feature update isn't a valid "older/newer"
        # comparison against this one.
        if installed_tuple[:1] != fixed_tuple[:1]:
            continue
        if installed_tuple < fixed_tuple:
            kb_note = f", resolved by {vuln.resolved_by_kb}" if vuln.resolved_by_kb else ""
            matches.append(Match(
                vuln=vuln,
                matched_on=(
                    f"build {installed_build} is older than the fixed build "
                    f"{vuln.resolved_by_build}{kb_note}"
                ),
            ))
    return matches
