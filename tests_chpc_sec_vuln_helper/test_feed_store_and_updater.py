from pathlib import Path

from chpc_sec_vuln_helper.feeds import feed_store, updater
from chpc_sec_vuln_helper.feeds.normalize_rhel_oval import parse_oval

FIXTURE = Path(__file__).parent / "fixtures" / "sample_oval.xml"


def test_save_and_load_roundtrip(tmp_path):
    vulns = parse_oval(FIXTURE.read_text())
    feed_store.save_feed(tmp_path, "rhel", 9, vulns, "https://example.test/feed")
    loaded = feed_store.load_feed(tmp_path, "rhel", 9)
    assert len(loaded) == len(vulns)
    assert {v.id for v in loaded} == {v.id for v in vulns}


def test_load_nonexistent_feed_returns_empty_list(tmp_path):
    assert feed_store.load_feed(tmp_path, "rhel", 9) == []


def test_get_feed_info_and_age(tmp_path):
    vulns = parse_oval(FIXTURE.read_text())
    feed_store.save_feed(tmp_path, "rhel", 9, vulns, "https://example.test/feed")
    info = feed_store.get_feed_info(tmp_path, "rhel", 9)
    assert info is not None
    assert info.vuln_count == 2
    assert info.age_days() == 0  # just saved


def test_get_feed_info_missing_returns_none(tmp_path):
    assert feed_store.get_feed_info(tmp_path, "windows", 11) is None


def test_list_feeds(tmp_path):
    vulns = parse_oval(FIXTURE.read_text())
    feed_store.save_feed(tmp_path, "rhel", 9, vulns, "url1")
    feed_store.save_feed(tmp_path, "rocky", 9, vulns, "url2")
    infos = feed_store.list_feeds(tmp_path)
    assert len(infos) == 2
    assert {(i.os_family, i.os_major_version) for i in infos} == {("rhel", 9), ("rocky", 9)}


def test_import_rhel_oval_also_populates_rocky(tmp_path):
    vulns = parse_oval(FIXTURE.read_text())
    updater._save_rhel_and_rocky(tmp_path, 9, vulns, "https://example.test")
    rhel_info = feed_store.get_feed_info(tmp_path, "rhel", 9)
    rocky_info = feed_store.get_feed_info(tmp_path, "rocky", 9)
    assert rhel_info.vuln_count == 2
    assert rocky_info.vuln_count == 2
    rocky_loaded = feed_store.load_feed(tmp_path, "rocky", 9)
    assert all(v.os_family == "rocky" for v in rocky_loaded)


def test_check_network_false_for_unresolvable_host():
    assert updater.check_network("https://this-host-does-not-exist-xyz-12345.invalid/", timeout=3) is False


def test_prompt_update_offline_prints_manual_instructions(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "RHEL_OVAL_URL_TEMPLATE",
                         "https://this-host-does-not-exist-xyz-12345.invalid/RHEL{major}/rhel-{major}.oval.xml.bz2")
    printed = []
    updater.prompt_update_if_stale(
        tmp_path, "rhel", 9,
        input_func=lambda p: "y",
        print_func=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    full_text = "\n".join(printed)
    assert "No internet access detected" in full_text
    assert "curl -O" in full_text
    assert "Rocky Linux 9 reuses" in full_text


def test_prompt_update_declining_does_nothing(tmp_path):
    printed = []
    updater.prompt_update_if_stale(
        tmp_path, "rhel", 9,
        input_func=lambda p: "n",
        print_func=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    # should have asked, then done nothing further (no crash, no feed created)
    assert feed_store.get_feed_info(tmp_path, "rhel", 9) is None


def test_prompt_update_fresh_feed_says_nothing(tmp_path):
    vulns = parse_oval(FIXTURE.read_text())
    feed_store.save_feed(tmp_path, "rhel", 9, vulns, "url")
    printed = []
    updater.prompt_update_if_stale(
        tmp_path, "rhel", 9, stale_after_days=30,
        input_func=lambda p: (_ for _ in ()).throw(AssertionError("should not have prompted")),
        print_func=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    assert printed == []


def test_windows_prompt_finds_pending_import(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    csv_path = incoming / "msrc_export.csv"
    csv_path.write_text(
        "Release date,Product,Platform,Impact,Max Severity,Article,Article Link,Build Number,Details,Base Score,CVE\n"
        "2024-03-12,Windows 11 Version 23H2,x64,RCE,Critical,5035853,url,10.0.22631.3374,Kernel EoP,8.4,CVE-2024-9999\n"
    )
    printed = []
    updater.prompt_update_if_stale(
        tmp_path, "windows", 11,
        input_func=lambda p: "y",
        print_func=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
    )
    full_text = "\n".join(printed)
    assert "Found a waiting MSRC export" in full_text
    assert "Imported: windows 11" in full_text
    info = feed_store.get_feed_info(tmp_path, "windows", 11)
    assert info is not None
    assert info.vuln_count == 1
