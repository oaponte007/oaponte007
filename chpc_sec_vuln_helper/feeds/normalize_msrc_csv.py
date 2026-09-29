"""Converts a CSV export from Microsoft's Security Update Guide
(https://msrc.microsoft.com/update-guide/ -> filter to Windows 10/11 ->
Export) into our normalized schema. There's no stable, documented
programmatic API for this the way Red Hat publishes OVAL files, so this
is deliberately a manual export -> import step (see README) rather
than something this tool tries to scrape automatically.

MSRC's portal has changed its exact export column names over time and
this could not be validated against a live export in the environment
it was written in (msrc.microsoft.com was blocked) -- so every column
is matched by a list of recognized aliases, case-insensitively, and
`parse_msrc_csv` raises a clear, actionable error naming exactly which
required column it couldn't find, rather than silently mismatching
data into the wrong fields.

Windows 10 and 11 both report an internal OS version of "10.0.*", so
the *build number itself* is what actually distinguishes them: builds
at 22000 or above are Windows 11, anything lower is Windows 10 -- a
documented heuristic (Microsoft has used this exact threshold in its
own tooling), not an assumption specific to this tool.
"""
from __future__ import annotations

import csv
import io
import re

from .schema import NormalizedVuln

_COLUMN_ALIASES = {
    "cve": ["cve", "cve number", "cve id", "cve numbers", "cve-id"],
    "title": ["details", "title", "description", "vulnerability"],
    "severity": ["max severity", "severity", "impact", "max impact"],
    "article": ["article", "kb article", "kb number", "article number", "kb"],
    "build_number": ["build number", "build", "affected build", "build_number"],
    "release_date": ["release date", "date", "release_date"],
    "product": ["product", "product family", "product name"],
}

_SEVERITY_MAP = {
    "critical": "critical",
    "important": "high",
    "moderate": "medium",
    "low": "low",
}

_WIN11_MIN_BUILD = 22000


class MsrcCsvError(ValueError):
    pass


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    lower_to_actual = {f.strip().lower(): f for f in fieldnames}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key, aliases in _COLUMN_ALIASES.items():
        found = next((lower_to_actual[a] for a in aliases if a in lower_to_actual), None)
        if found:
            resolved[key] = found
        else:
            missing.append(f"{key} (tried: {', '.join(aliases)})")
    if missing:
        raise MsrcCsvError(
            "Could not find these expected columns in the MSRC CSV export -- "
            "the portal's export format may have changed since this normalizer "
            "was written. Missing:\n  " + "\n  ".join(missing) +
            f"\nColumns actually present: {', '.join(fieldnames)}"
        )
    return resolved


def _extract_build(raw: str) -> str | None:
    """"10.0.22631.3737" or "22631.3737" or "22631" -> "22631.3737" form
    (the same "buildnumber.revision" convention the Windows collector
    reports), or None if nothing numeric is present.
    """
    numbers = re.findall(r"\d+", raw)
    if not numbers:
        return None
    if len(numbers) >= 2:
        return f"{numbers[-2]}.{numbers[-1]}"
    return f"{numbers[-1]}.0"


def parse_msrc_csv(csv_text: str) -> list[NormalizedVuln]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise MsrcCsvError("The CSV file has no header row -- is this really an MSRC export?")
    columns = _resolve_columns(reader.fieldnames)

    results: list[NormalizedVuln] = []
    for row in reader:
        build_raw = row.get(columns["build_number"], "")
        build = _extract_build(build_raw)
        if not build:
            continue  # nothing to compare against installed builds -- skip this row

        major_build = int(build.split(".")[0])
        os_major_version = 11 if major_build >= _WIN11_MIN_BUILD else 10

        cve_raw = row.get(columns["cve"], "").strip()
        cve_ids = [c.strip() for c in re.split(r"[,;\s]+", cve_raw) if c.strip().upper().startswith("CVE-")]

        severity_raw = row.get(columns["severity"], "").strip().lower()
        severity = _SEVERITY_MAP.get(severity_raw, "unknown")

        article = row.get(columns["article"], "").strip()
        kb = f"KB{article}" if article and not article.upper().startswith("KB") else (article or None)

        title = row.get(columns["title"], "").strip() or (cve_ids[0] if cve_ids else "Windows security update")
        vuln_id = cve_ids[0] if cve_ids else (kb or title)

        results.append(NormalizedVuln(
            id=vuln_id,
            title=title,
            severity=severity,
            description=title,
            os_family="windows",
            os_major_versions=[os_major_version],
            source="msrc-csv",
            cve_ids=cve_ids,
            published=row.get(columns["release_date"], "").strip(),
            resolved_by_build=build,
            resolved_by_kb=kb,
        ))

    return results
