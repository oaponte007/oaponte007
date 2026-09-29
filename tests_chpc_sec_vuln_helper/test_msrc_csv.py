import pytest

from chpc_sec_vuln_helper.feeds.matcher import match_windows
from chpc_sec_vuln_helper.feeds.normalize_msrc_csv import MsrcCsvError, parse_msrc_csv

SAMPLE_CSV = """Release date,Product,Platform,Impact,Max Severity,Article,Article Link,Build Number,Details,Base Score,CVE
2024-03-12,Windows 11 Version 23H2,x64,Remote Code Execution,Critical,5035853,https://support.microsoft.com/kb5035853,10.0.22631.3374,Windows Kernel Elevation of Privilege Vulnerability,8.4,CVE-2024-9999
2024-02-13,Windows 10 Version 22H2,x64,Denial of Service,Important,5034441,https://support.microsoft.com/kb5034441,10.0.19045.4046,Windows DNS Denial of Service,7.5,CVE-2024-8888
"""


def test_parses_and_distinguishes_windows_10_vs_11_by_build():
    vulns = parse_msrc_csv(SAMPLE_CSV)
    assert len(vulns) == 2

    win11 = next(v for v in vulns if v.os_major_versions == [11])
    assert win11.resolved_by_build == "22631.3374"
    assert win11.resolved_by_kb == "KB5035853"
    assert win11.severity == "critical"
    assert win11.cve_ids == ["CVE-2024-9999"]

    win10 = next(v for v in vulns if v.os_major_versions == [10])
    assert win10.resolved_by_build == "19045.4046"
    assert win10.severity == "high"  # "Important" -> "high"


def test_matches_older_build_only():
    vulns = parse_msrc_csv(SAMPLE_CSV)
    matches = match_windows("22631.3007", vulns)
    assert len(matches) == 1
    assert matches[0].vuln.cve_ids == ["CVE-2024-9999"]


def test_no_match_when_already_patched():
    vulns = parse_msrc_csv(SAMPLE_CSV)
    assert match_windows("22631.3374", vulns) == []
    assert match_windows("22631.9999", vulns) == []  # newer than the fix


def test_different_build_family_never_cross_matches():
    """A Windows 10 build number must never be compared against a
    Windows 11 advisory's fixed build, even though both share "10.0."
    as an OS version prefix internally.
    """
    vulns = parse_msrc_csv(SAMPLE_CSV)
    matches = match_windows("19045.1000", vulns)  # old Win10 build
    # only the Win10 DNS advisory should be relevant, never the Win11 one
    assert all(m.vuln.os_major_versions == [10] for m in matches)


def test_unrecognized_columns_raise_clear_error():
    bad_csv = "Foo,Bar\n1,2\n"
    with pytest.raises(MsrcCsvError) as exc_info:
        parse_msrc_csv(bad_csv)
    assert "cve" in str(exc_info.value).lower()
