"""Builds a self-contained HTML report -- zero dependencies (Python
standard library only, unlike docx_report.py), so it's always
available even on a machine with no python-docx installed. Opens in
any browser; "Print... -> Save as PDF" is the zero-install path to a
PDF, satisfying the ".docx and/or PDF" ask without needing a PDF
library or a Word/LibreOffice install to automate.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

from . import branding
from .report_data import ReportFinding, sort_findings, summarize_by_severity

_CSS = """
  body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color: #1a1a1a;
         max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; line-height: 1.5; }
  .logo { display: block; margin: 0 auto 12px; max-width: 220px; }
  h1 { text-align: center; color: %(primary)s; margin-bottom: 4px; }
  .slogan { text-align: center; font-style: italic; color: %(primary)s; margin: 0; }
  .website { text-align: center; color: %(accent)s; font-size: 0.85em; margin-top: 2px; }
  table.info { width: 100%%; border-collapse: collapse; margin: 20px 0; }
  table.info td { border: 1px solid #ccc; padding: 8px 10px; }
  table.info td:first-child { font-weight: bold; width: 220px; background: #f5f5f5; }
  .summary-table { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
  .summary-badge { color: #fff; border-radius: 6px; padding: 10px 18px; text-align: center; min-width: 90px; }
  .summary-badge .count { font-size: 1.6em; font-weight: bold; display: block; }
  .finding { border-left: 4px solid #ccc; padding: 4px 16px; margin: 18px 0; page-break-inside: avoid; }
  .finding-title { font-weight: bold; font-size: 1.05em; }
  .badge { color: #fff; border-radius: 4px; padding: 1px 8px; font-size: 0.75em; font-weight: bold; margin-right: 6px; }
  .reference { font-style: italic; font-size: 0.8em; color: #555; }
  .why-matters strong { color: %(primary)s; }
  .evidence { font-style: italic; font-size: 0.8em; color: #666; margin-top: 6px; }
  .notes-list { background: %(accent_tint)s; padding: 12px 20px; border-radius: 6px; }
  footer { text-align: center; color: #888; font-size: 0.8em; margin-top: 48px; }
  @media print { body { padding: 0; } .finding { break-inside: avoid; } }
"""


def _severity_span(severity: str) -> str:
    color = branding.SEVERITY_COLORS[severity]
    label = branding.SEVERITY_LABELS[severity]
    return f'<span class="badge" style="background:#{color}">{label}</span>'


def _logo_data_uri() -> str | None:
    logo_path = branding.ensure_logo()
    if not logo_path:
        return None
    data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _finding_html(finding: ReportFinding) -> str:
    color = branding.SEVERITY_COLORS[finding.severity]
    reference = ""
    if finding.cve_ids:
        reference = f'<div class="reference">Reference: {html.escape(finding.advisory_id or "")} ({html.escape(", ".join(finding.cve_ids))})</div>'
    fix_items = "".join(f"<li>{html.escape(step)}</li>" for step in finding.fix_steps)
    evidence = f'<div class="evidence">What was found: {html.escape(finding.evidence)}</div>' if finding.evidence else ""
    description = html.escape(finding.description).replace("\n", "<br>")
    return f"""
    <div class="finding" style="border-left-color:#{color}">
      <div class="finding-title">{_severity_span(finding.severity)}{html.escape(finding.title)}</div>
      {reference}
      <p>{description}</p>
      <p class="why-matters"><strong>Why this matters:</strong> {html.escape(finding.danger)}</p>
      <p><strong>How to fix it:</strong></p>
      <ol>{fix_items}</ol>
      {evidence}
    </div>
    """


def build_html_report(
    hostname: str,
    os_label: str,
    scan_date: str,
    findings: list[ReportFinding],
    feed_notes: list[str],
    output_path: Path,
) -> Path:
    sorted_findings = sort_findings(findings)
    counts = summarize_by_severity(sorted_findings)
    total = len(sorted_findings)

    logo_uri = _logo_data_uri()
    logo_html = f'<img class="logo" src="{logo_uri}" alt="{branding.COMPANY_NAME} logo">' if logo_uri else ""

    summary_html = ""
    if total:
        badges = "".join(
            f'<div class="summary-badge" style="background:#{branding.SEVERITY_COLORS[s]}">'
            f'<span class="count">{counts[s]}</span>{branding.SEVERITY_LABELS[s]}</div>'
            for s in branding.SEVERITY_ORDER if counts.get(s)
        )
        summary_html = f'<p>{total} finding(s) were identified on this host, summarized by severity below.</p><div class="summary-table">{badges}</div>'
    else:
        summary_html = (
            "<p>No baseline hardening issues or known vulnerabilities were found against the data "
            "available at scan time. Keep this computer's updates and settings current -- this is "
            "a snapshot, not a permanent guarantee.</p>"
        )

    notes_html = ""
    if feed_notes:
        items = "".join(f"<li>{html.escape(n)}</li>" for n in feed_notes)
        notes_html = f'<p><strong>Notes on data currency:</strong></p><ul class="notes-list">{items}</ul>'

    findings_html = ""
    if sorted_findings:
        findings_html += (
            "<h2>Detailed Findings</h2>"
            "<p>Findings are listed from most to least urgent. Each one explains what it is, why it "
            "matters, and exactly how to fix it -- written so anyone can follow the steps, not just "
            "an IT professional. Fixing these is left up to you and your team; nothing on this "
            "computer was changed by running this scan.</p>"
        )
        current_severity = None
        for finding in sorted_findings:
            if finding.severity != current_severity:
                current_severity = finding.severity
                findings_html += f"<h3>{branding.SEVERITY_LABELS[current_severity]} severity</h3>"
            findings_html += _finding_html(finding)

    css = _CSS % {"primary": f"#{branding.PRIMARY_HEX}", "accent": f"#{branding.ACCENT_HEX}", "accent_tint": f"#{branding.ACCENT_TINT_HEX}"}

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Security Baseline &amp; Vulnerability Report -- {html.escape(hostname)}</title>
<style>{css}</style>
</head>
<body>
{logo_html}
<h1>Security Baseline &amp; Vulnerability Report</h1>
<p class="slogan">{html.escape(branding.COMPANY_NAME)} &mdash; {html.escape(branding.SLOGAN)}</p>
<p class="website">{html.escape(branding.WEBSITE)}</p>

<table class="info">
  <tr><td>Host</td><td>{html.escape(hostname)}</td></tr>
  <tr><td>Operating System</td><td>{html.escape(os_label)}</td></tr>
  <tr><td>Report generated</td><td>{html.escape(scan_date)}</td></tr>
</table>

<h2>Executive Summary</h2>
{summary_html}
{notes_html}

{findings_html}

<footer>{html.escape(branding.COMPANY_NAME)} &mdash; {html.escape(branding.SLOGAN)} &nbsp;|&nbsp; {html.escape(branding.WEBSITE)}</footer>
</body>
</html>
"""
    output_path = Path(output_path)
    output_path.write_text(document, encoding="utf-8")
    return output_path
