import json
from pathlib import Path

from chpc_sec_vuln_helper.cli import build_parser


def _run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _write_collected(path: Path, **overrides):
    data = {
        "schema_version": 1,
        "hostname": "node042",
        "collected_at": "2026-09-29T18:00:00Z",
        "os": {"family": "rhel", "name": "Red Hat Enterprise Linux", "major_version": 9, "version_id": "9.4"},
        "packages": [
            {"name": "openssl", "epoch": "1", "version": "3.0.7", "release": "18.el9_4", "arch": "x86_64"},
        ],
        "selinux_status": "disabled",
        "firewall_active": False,
        "collector_warnings": [],
    }
    data.update(overrides)
    path.write_text(json.dumps(data))
    return path


def test_update_feed_import_rhel_oval(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample_oval.xml"
    feed_dir = tmp_path / "feeds"
    rc = _run(["update-feed", "--import-rhel-oval", str(fixture), "--os-version", "9", "--feed-dir", str(feed_dir)])
    assert rc == 0
    assert (feed_dir / "rhel9.json").exists()
    assert (feed_dir / "rocky9.json").exists()


def test_list_feeds_empty_and_populated(tmp_path, capsys):
    feed_dir = tmp_path / "feeds"
    rc = _run(["list-feeds", "--feed-dir", str(feed_dir)])
    assert rc == 0
    assert "No feeds found" in capsys.readouterr().out

    fixture = Path(__file__).parent / "fixtures" / "sample_oval.xml"
    _run(["update-feed", "--import-rhel-oval", str(fixture), "--os-version", "9", "--feed-dir", str(feed_dir)])
    rc = _run(["list-feeds", "--feed-dir", str(feed_dir)])
    out = capsys.readouterr().out
    assert "rhel" in out and "rocky" in out


def test_scan_end_to_end_writes_reports_and_matches_cve(tmp_path, capsys):
    feed_dir = tmp_path / "feeds"
    fixture = Path(__file__).parent / "fixtures" / "sample_oval.xml"
    _run(["update-feed", "--import-rhel-oval", str(fixture), "--os-version", "9", "--feed-dir", str(feed_dir)])

    collected_path = tmp_path / "collected.json"
    _write_collected(collected_path)

    out_base = tmp_path / "report"
    rc = _run([
        "scan", str(collected_path),
        "--feed-dir", str(feed_dir),
        "--out", str(out_base),
        "--format", "both",
        "--yes",
    ])
    assert rc == 0
    assert out_base.with_suffix(".docx").exists()
    assert out_base.with_suffix(".html").exists()

    out = capsys.readouterr().out
    assert "finding(s)" in out
    # selinux_not_enforcing, firewall_inactive (baseline) + openssl CVE match
    assert "high" in out.lower()


def test_scan_with_no_feed_only_reports_baseline_findings(tmp_path, capsys):
    collected_path = tmp_path / "collected.json"
    _write_collected(collected_path)
    out_base = tmp_path / "report"

    rc = _run([
        "scan", str(collected_path),
        "--feed-dir", str(tmp_path / "empty_feeds"),
        "--out", str(out_base),
        "--format", "html",
        "--yes",
    ])
    assert rc == 0
    text = out_base.with_suffix(".html").read_text()
    assert "No vulnerability feed is loaded" in text
    assert "SELinux" in text  # baseline finding still present
    assert "publicly documented security hole" not in text  # no CVE finding without a feed


def test_scan_reads_collected_json_with_utf8_bom(tmp_path, capsys):
    # Windows PowerShell 5.1's `Set-Content -Encoding UTF8` prepends a
    # UTF-8 byte-order-mark; make sure `scan` still parses a file like that
    # instead of raising json.JSONDecodeError("Expecting value", ...).
    collected_path = tmp_path / "collected.json"
    _write_collected(collected_path)
    raw = collected_path.read_bytes()
    collected_path.write_bytes(b"\xef\xbb\xbf" + raw)

    out_base = tmp_path / "report"
    rc = _run([
        "scan", str(collected_path),
        "--feed-dir", str(tmp_path / "feeds"),
        "--out", str(out_base),
        "--format", "html",
        "--yes",
    ])
    assert rc == 0
    assert out_base.with_suffix(".html").exists()


def test_scan_unsupported_os_produces_no_crash(tmp_path):
    collected_path = tmp_path / "collected.json"
    _write_collected(collected_path, os={"family": "ubuntu", "name": "Ubuntu", "major_version": 24, "version_id": "24.04"})
    out_base = tmp_path / "report"
    rc = _run([
        "scan", str(collected_path),
        "--feed-dir", str(tmp_path / "feeds"),
        "--out", str(out_base),
        "--format", "html",
        "--yes",
    ])
    assert rc == 0
    text = out_base.with_suffix(".html").read_text()
    assert "No findings" in text or "No baseline hardening issues" in text
