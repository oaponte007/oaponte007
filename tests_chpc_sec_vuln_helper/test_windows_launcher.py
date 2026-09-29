from pathlib import Path

from chpc_sec_vuln_helper import windows_launcher


def test_bundled_collector_script_found_when_unfrozen():
    # Not frozen by PyInstaller in this test -- should fall back to the
    # real package path rather than sys._MEIPASS.
    path = windows_launcher._bundled_collector_script()
    assert path.name == "windows_collector.ps1"
    assert path.exists()


def test_main_menu_quit_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "5")
    rc = windows_launcher.main()
    assert rc == 0
    assert "Coastal HPC" in capsys.readouterr().out


def test_main_menu_invalid_choice_then_quit(monkeypatch, capsys):
    answers = iter(["nope", "5"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))
    rc = windows_launcher.main()
    assert rc == 0
    assert "Please enter one of the numbers above" in capsys.readouterr().out


def test_do_scan_runs_end_to_end(tmp_path, monkeypatch, capsys):
    import json
    collected = tmp_path / "collected.json"
    collected.write_text(json.dumps({
        "schema_version": 1,
        "hostname": "node042",
        "collected_at": "2026-09-29T18:00:00Z",
        "os": {"family": "rhel", "name": "Red Hat Enterprise Linux", "major_version": 9, "version_id": "9.4"},
        "packages": [],
        "selinux_status": "enforcing",
        "firewall_active": True,
        "collector_warnings": [],
    }))
    out_base = tmp_path / "report"
    # do_scan's args.yes=False, so cmd_scan also asks the interactive
    # "check for an updated feed now?" prompt -- answer "n" to it too.
    answers = iter([str(collected), str(out_base), "html", "n"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: next(answers))
    monkeypatch.setattr(
        "chpc_sec_vuln_helper.windows_launcher.feed_store.DEFAULT_FEED_DIR",
        tmp_path / "feeds",
    )
    windows_launcher.do_scan()
    assert out_base.with_suffix(".html").exists()


def test_do_list_feeds_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "chpc_sec_vuln_helper.windows_launcher.feed_store.DEFAULT_FEED_DIR",
        tmp_path / "feeds",
    )
    windows_launcher.do_list_feeds()
    assert "No feeds loaded yet" in capsys.readouterr().out
