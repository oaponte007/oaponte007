from pathlib import Path

from chpc_sec_vuln_helper.feeds.matcher import match_linux
from chpc_sec_vuln_helper.feeds.normalize_rhel_oval import parse_oval

FIXTURE = Path(__file__).parent / "fixtures" / "sample_oval.xml"


def test_parses_two_definitions_with_correct_metadata():
    vulns = parse_oval(FIXTURE.read_text())
    assert len(vulns) == 2

    openssl_vuln = next(v for v in vulns if v.id == "RHSA-2024:2000")
    assert openssl_vuln.severity == "high"  # "Important" -> "high"
    assert openssl_vuln.os_major_versions == [9]
    assert openssl_vuln.cve_ids == ["CVE-2024-1111"]
    assert {p.name for p in openssl_vuln.affected_packages} == {"openssl", "openssl-libs"}
    assert all(p.fixed_evr == "1:3.0.7-27.el9_5" for p in openssl_vuln.affected_packages)

    httpd_vuln = next(v for v in vulns if v.id == "RHSA-2024:3000")
    assert httpd_vuln.severity == "medium"  # "Moderate" -> "medium"
    assert httpd_vuln.os_major_versions == [8, 9]


def test_matches_vulnerable_packages_only():
    vulns = parse_oval(FIXTURE.read_text())
    installed = [
        {"name": "openssl", "epoch": "1", "version": "3.0.7", "release": "18.el9_4", "arch": "x86_64"},
        {"name": "openssl-libs", "epoch": "1", "version": "3.0.7", "release": "18.el9_4", "arch": "x86_64"},
        {"name": "httpd", "epoch": "0", "version": "2.4.57", "release": "5.el9_4", "arch": "x86_64"},  # already fixed
    ]
    matches = match_linux(installed, vulns)
    matched_ids = {m.vuln.id for m in matches}
    assert matched_ids == {"RHSA-2024:2000"}
    assert len(matches) == 2  # openssl and openssl-libs, both matched separately by the matcher


def test_no_matches_when_everything_is_up_to_date():
    vulns = parse_oval(FIXTURE.read_text())
    installed = [
        {"name": "openssl", "epoch": "1", "version": "3.0.7", "release": "27.el9_5", "arch": "x86_64"},
        {"name": "openssl-libs", "epoch": "1", "version": "3.0.7", "release": "27.el9_5", "arch": "x86_64"},
        {"name": "httpd", "epoch": "0", "version": "2.4.57", "release": "5.el9_4", "arch": "x86_64"},
    ]
    assert match_linux(installed, vulns) == []


def test_uninstalled_package_never_matches():
    vulns = parse_oval(FIXTURE.read_text())
    installed = [{"name": "vim", "epoch": None, "version": "9.0", "release": "1.el9", "arch": "x86_64"}]
    assert match_linux(installed, vulns) == []
