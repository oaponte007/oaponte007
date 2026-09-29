"""Command-line entry point.

    chpc-sec-vuln-helper collect [-o collected.json]
    chpc-sec-vuln-helper update-feed [--os-family rhel|rocky --os-version N]
    chpc-sec-vuln-helper update-feed --import-rhel-oval FILE.xml.bz2 --os-version N
    chpc-sec-vuln-helper update-feed --import-msrc-csv FILE.csv
    chpc-sec-vuln-helper scan collected.json [--out report] [--format docx|html|both] [--yes]

`collect` only works on Linux (RHEL/Rocky) -- on Windows, run
collectors/windows_collector.ps1 directly instead; its JSON output is
exactly what `scan` expects either way.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .feeds import feed_store, updater
from .feeds.matcher import match_linux, match_windows
from .report import report_data
from .rules.engine import evaluate
from .rules.linux_rules import LINUX_RULES
from .rules.windows_rules import WINDOWS_RULES

DEFAULT_FEED_DIR = feed_store.DEFAULT_FEED_DIR


def cmd_collect(args: argparse.Namespace) -> int:
    from .collectors import linux_collector
    return linux_collector.main(["-o", args.output] if args.output else [])


def cmd_update_feed(args: argparse.Namespace) -> int:
    feed_dir = Path(args.feed_dir)

    if args.import_rhel_oval:
        if not args.os_version:
            print("--os-version is required with --import-rhel-oval", file=sys.stderr)
            return 1
        import bz2
        from .feeds.normalize_rhel_oval import parse_oval
        path = Path(args.import_rhel_oval)
        raw = path.read_bytes()
        xml_text = bz2.decompress(raw).decode("utf-8") if path.suffix == ".bz2" else raw.decode("utf-8")
        vulns = parse_oval(xml_text)
        info = updater._save_rhel_and_rocky(feed_dir, args.os_version, vulns, f"manual import: {path.name}")
        print(f"Imported: rhel {args.os_version} and rocky {args.os_version} -- {info.vuln_count} advisories.")
        return 0

    if args.import_msrc_csv:
        infos = updater.import_msrc_csv_file(Path(args.import_msrc_csv), feed_dir)
        for i in infos:
            print(f"Imported: windows {i.os_major_version} -- {i.vuln_count} advisories.")
        if not infos:
            print("No usable rows found in that CSV.", file=sys.stderr)
            return 1
        return 0

    if not args.os_family or not args.os_version:
        print("Provide --os-family and --os-version (e.g. --os-family rhel --os-version 9), or use --import-rhel-oval/--import-msrc-csv.", file=sys.stderr)
        return 1

    updater.prompt_update_if_stale(feed_dir, args.os_family, args.os_version, stale_after_days=0)
    return 0


def cmd_list_feeds(args: argparse.Namespace) -> int:
    feed_dir = Path(args.feed_dir)
    infos = feed_store.list_feeds(feed_dir)
    if not infos:
        print(f"No feeds found in {feed_dir}.")
        return 0
    for info in infos:
        print(f"{info.os_family:8s} {info.os_major_version:<4} {info.vuln_count:5d} advisories  "
              f"fetched {info.fetched_at}  ({info.age_days()}d old)")
    return 0


def _load_collected(path: Path) -> dict:
    import json
    # utf-8-sig transparently strips a leading UTF-8 BOM if present (e.g.
    # from Windows PowerShell 5.1's `-Encoding UTF8`) and behaves exactly
    # like plain utf-8 when there isn't one -- safe either way.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def cmd_scan(args: argparse.Namespace) -> int:
    collected = _load_collected(Path(args.collected_json))
    os_info = collected.get("os", {})
    os_family = os_info.get("family")
    os_major = os_info.get("major_version")
    hostname = collected.get("hostname", "unknown-host")
    os_label = f"{os_info.get('name', os_family)} {os_info.get('version_id', '')}".strip()

    feed_dir = Path(args.feed_dir)
    feed_notes: list[str] = []

    if os_family in ("rhel", "rocky", "windows") and os_major:
        if not args.no_feed_prompt:
            answer_source = (lambda p: "n") if args.yes else input
            updater.prompt_update_if_stale(feed_dir, os_family, os_major, input_func=answer_source, print_func=print)

        info = feed_store.get_feed_info(feed_dir, os_family, os_major)
        if info is None:
            feed_notes.append(
                f"No vulnerability feed is loaded for {os_family} {os_major} -- only baseline "
                "hardening checks are included below. Run 'update-feed' to add CVE matching."
            )
        else:
            feed_notes.append(
                f"CVE data: {info.vuln_count} advisories for {os_family} {os_major}, "
                f"fetched {info.fetched_at} ({info.age_days()} day(s) ago)."
            )
    else:
        feed_notes.append("Unrecognized or unsupported OS -- no baseline checks or CVE matching apply.")

    baseline_findings = []
    cve_matches = []
    if os_family in ("rhel", "rocky"):
        baseline_findings = evaluate(LINUX_RULES, collected)
        vulns = feed_store.load_feed(feed_dir, os_family, os_major) if os_major else []
        if vulns and collected.get("packages"):
            relevant = [v for v in vulns if os_major in v.os_major_versions]
            cve_matches = match_linux(collected["packages"], relevant)
    elif os_family == "windows":
        baseline_findings = evaluate(WINDOWS_RULES, collected)
        vulns = feed_store.load_feed(feed_dir, os_family, os_major) if os_major else []
        build = os_info.get("build")
        if vulns and build:
            relevant = [v for v in vulns if os_major in v.os_major_versions]
            cve_matches = match_windows(build, relevant)

    findings = report_data.from_baseline_findings(baseline_findings) + report_data.from_cve_matches(cve_matches, os_family)

    if collected.get("collector_warnings"):
        feed_notes.append(f"{len(collected['collector_warnings'])} check(s) were skipped during collection (insufficient privilege or missing tool) -- see collector_warnings in the collected JSON for details.")

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out_base = Path(args.out)
    fmt = args.format

    written = []
    if fmt in ("docx", "both"):
        from .report.docx_report import build_docx_report
        try:
            written.append(build_docx_report(hostname, os_label, scan_date, findings, feed_notes, out_base.with_suffix(".docx")))
        except ImportError:
            print("python-docx is not installed -- skipped the .docx report (pip install python-docx). Writing HTML instead.", file=sys.stderr)
            fmt = "html"
    if fmt in ("html", "both"):
        from .report.html_report import build_html_report
        written.append(build_html_report(hostname, os_label, scan_date, findings, feed_notes, out_base.with_suffix(".html")))

    counts = report_data.summarize_by_severity(findings)
    print(f"\n{len(findings)} finding(s): " + ", ".join(f"{counts[s]} {s}" for s in counts) if counts else "\nNo findings.")
    for path in written:
        print(f"Wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chpc-sec-vuln-helper",
        description="Audit RHEL/Rocky/Windows hosts for security weaknesses on an airgapped machine, and produce a branded report.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="collect this Linux host's security-relevant state to JSON")
    p_collect.add_argument("-o", "--output", help="output path (default: stdout)")
    p_collect.set_defaults(func=cmd_collect)

    p_update = sub.add_parser("update-feed", help="fetch or import a vulnerability feed")
    p_update.add_argument("--os-family", choices=["rhel", "rocky"])
    p_update.add_argument("--os-version", type=int)
    p_update.add_argument("--import-rhel-oval", metavar="FILE", help="normalize and import an already-downloaded RHEL OVAL .xml or .xml.bz2 file")
    p_update.add_argument("--import-msrc-csv", metavar="FILE", help="normalize and import an MSRC Security Update Guide CSV export")
    p_update.add_argument("--feed-dir", default=str(DEFAULT_FEED_DIR))
    p_update.set_defaults(func=cmd_update_feed)

    p_list = sub.add_parser("list-feeds", help="show every locally stored vulnerability feed and its age")
    p_list.add_argument("--feed-dir", default=str(DEFAULT_FEED_DIR))
    p_list.set_defaults(func=cmd_list_feeds)

    p_scan = sub.add_parser("scan", help="evaluate a collected JSON file and write a branded report")
    p_scan.add_argument("collected_json")
    p_scan.add_argument("--feed-dir", default=str(DEFAULT_FEED_DIR))
    p_scan.add_argument("--out", default="security_report", help="output path without extension (default: security_report)")
    p_scan.add_argument("--format", choices=["docx", "html", "both"], default="both")
    p_scan.add_argument("--no-feed-prompt", action="store_true", help="never prompt about updating the feed")
    p_scan.add_argument("--yes", action="store_true", help="answer 'no' to the feed-update prompt automatically (non-interactive)")
    p_scan.set_defaults(func=cmd_scan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
