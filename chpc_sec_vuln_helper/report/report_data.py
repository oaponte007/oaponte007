"""Turns baseline rule findings (rules/engine.Finding) and CVE matches
(feeds/matcher.Match) into one common shape the report generators
render -- so docx_report.py and html_report.py don't need to know the
difference between the two finding sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..feeds.matcher import Match
from ..feeds.schema import severity_sort_key
from ..rules.engine import Finding


@dataclass
class ReportFinding:
    kind: str  # "baseline" | "cve"
    severity: str
    title: str
    description: str
    danger: str
    fix_steps: list[str]
    evidence: str = ""
    cve_ids: list[str] = field(default_factory=list)
    advisory_id: str | None = None


def _cve_fix_steps(os_family: str, package_or_kb: str) -> list[str]:
    if os_family in ("rhel", "rocky"):
        return [
            "Open a terminal with admin access.",
            f"Type: sudo dnf update {package_or_kb}",
            "This downloads and installs the fixed version.",
            "Some fixes need a restart of the affected program, or the whole computer, to fully take effect.",
        ]
    return [
        "Click the Start button and open Settings.",
        "Click 'Windows Update'.",
        "Click 'Check for updates' and install everything offered.",
        f"This specific issue is fixed by {package_or_kb}. If it doesn't show up right away, restart the computer and check again.",
    ]


def from_baseline_findings(findings: list[Finding]) -> list[ReportFinding]:
    return [
        ReportFinding(
            kind="baseline",
            severity=f.rule.severity,
            title=f.rule.title,
            description=f.rule.description,
            danger=f.rule.danger,
            fix_steps=list(f.rule.fix_steps),
            evidence=f.evidence,
        )
        for f in findings
    ]


def from_cve_matches(matches: list[Match], os_family: str) -> list[ReportFinding]:
    """One finding per *advisory*, not per matched package -- an RHSA
    that lists both `openssl` and `openssl-libs` as affected is one
    real-world problem (update openssl), not two, and showing it twice
    with near-identical text would just look like a duplicate to a
    reader who doesn't already know how OVAL groups packages.
    """
    grouped: dict[str, list[Match]] = {}
    for m in matches:
        grouped.setdefault(m.vuln.id, []).append(m)

    results = []
    for advisory_id, group in grouped.items():
        vuln = group[0].vuln
        cve_list = ", ".join(vuln.cve_ids) if vuln.cve_ids else advisory_id
        if os_family in ("rhel", "rocky"):
            pkg_names = sorted({p.name for p in vuln.affected_packages})
            fix_target = " ".join(pkg_names) if pkg_names else "*"
        else:
            fix_target = vuln.resolved_by_kb or "the latest cumulative update"
        results.append(ReportFinding(
            kind="cve",
            severity=vuln.severity,
            title=vuln.title,
            description=(
                f"This is a publicly documented security hole ({cve_list}), officially described as:\n"
                f"{vuln.description or '(no further description provided by the advisory)'}"
            ),
            danger=(
                "Because this is a known, published vulnerability, the exact way to exploit it is "
                "public information -- anyone can look it up, including attackers running automated "
                "scans that specifically look for computers that haven't installed this fix yet."
            ),
            fix_steps=_cve_fix_steps(os_family, fix_target),
            evidence="; ".join(m.matched_on for m in group),
            cve_ids=list(vuln.cve_ids),
            advisory_id=advisory_id,
        ))
    return results


def sort_findings(findings: list[ReportFinding]) -> list[ReportFinding]:
    return sorted(findings, key=lambda f: (severity_sort_key(f.severity), f.title))


def summarize_by_severity(findings: list[ReportFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts
