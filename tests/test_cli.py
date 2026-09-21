import json
from datetime import datetime, timedelta

import pytest

from slurm_monitor.cli import build_parser, parse_since
from slurm_monitor.history import History


def test_parse_since_duration_forms():
    now_before = datetime.utcnow()
    result = parse_since("24h")
    now_after = datetime.utcnow()
    assert now_before - timedelta(hours=24) - timedelta(seconds=1) <= result
    assert result <= now_after - timedelta(hours=24) + timedelta(seconds=1)


def test_parse_since_days_and_weeks():
    result_d = parse_since("7d")
    result_w = parse_since("1w")
    assert abs((result_d - result_w).total_seconds()) < 2


def test_parse_since_iso_timestamp():
    result = parse_since("2026-01-01T09:00:00")
    assert result == datetime(2026, 1, 1, 9, 0, 0)


def test_parse_since_rejects_garbage():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        parse_since("not-a-time")


def test_log_command_json_output(tmp_path, capsys):
    db_path = tmp_path / "history.db"
    history = History(db_path)
    history.log_action(node="node047", category="low_real_memory", action="manual_review",
                        reason="Low RealMemory", note="diagnostic text",
                        ts=datetime(2026, 1, 1, 9, 0, 0))

    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"db_path: {db_path}\n")

    parser = build_parser()
    args = parser.parse_args(["--config", str(config_path), "log", "--format", "json"])
    rc = args.func(args)
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["node"] == "node047"
    assert out[0]["action"] == "manual_review"


def test_report_command_summarizes_actions(tmp_path, capsys):
    db_path = tmp_path / "history.db"
    history = History(db_path)
    now = datetime.utcnow()
    history.log_action(node="node047", category="low_real_memory", action="force_drain",
                        reason="Low RealMemory", note="", ts=now, success=True,
                        occurrences_in_window=2)
    history.log_action(node="node012", category="not_responding", action="resume",
                        reason="Node is not responding", note="", ts=now, success=True)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"db_path: {db_path}\n")

    parser = build_parser()
    args = parser.parse_args(["--config", str(config_path), "report", "--since", "24h"])
    rc = args.func(args)
    assert rc == 0

    out = capsys.readouterr().out
    assert "force_drain" in out
    assert "node047" in out


def test_log_command_empty_history_reports_none(tmp_path, capsys):
    db_path = tmp_path / "history.db"
    History(db_path)  # create empty db

    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"db_path: {db_path}\n")

    parser = build_parser()
    args = parser.parse_args(["--config", str(config_path), "log"])
    rc = args.func(args)
    assert rc == 0
    assert "No matching actions" in capsys.readouterr().out
