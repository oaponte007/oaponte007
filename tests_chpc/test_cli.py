from chpc.cli import build_parser


def _run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def test_install_writes_config_scaffolding(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("chpc.baseline._default_gpu_probe", lambda: [])
    config_path = tmp_path / "chpc.yaml"
    config_path.write_text(
        f"checks_file: {tmp_path / 'checks.conf'}\n"
        f"baseline_file: {tmp_path / 'baseline.yaml'}\n"
        f"state_db: {tmp_path / 'state.db'}\n"
        f"log_file: {tmp_path / 'chpc.log'}\n"
    )

    rc = _run(["--config", str(config_path), "install"])
    assert rc == 0
    assert (tmp_path / "baseline.yaml").exists()
    assert (tmp_path / "checks.conf").exists()
    out = capsys.readouterr().out
    assert "captured baseline" in out
    assert "Next steps" in out


def test_install_does_not_overwrite_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("chpc.baseline._default_gpu_probe", lambda: [])
    config_path = tmp_path / "chpc.yaml"
    checks_file = tmp_path / "checks.conf"
    config_path.write_text(
        f"checks_file: {checks_file}\n"
        f"baseline_file: {tmp_path / 'baseline.yaml'}\n"
        f"state_db: {tmp_path / 'state.db'}\n"
        f"log_file: {tmp_path / 'chpc.log'}\n"
    )
    _run(["--config", str(config_path), "install"])
    checks_file.write_text("* || check_disk_usage --path / --max-percent 50\n")

    _run(["--config", str(config_path), "install"])

    assert "check_disk_usage --path / --max-percent 50" in checks_file.read_text()


def test_check_command_runs_against_written_checks_file(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "chpc.yaml"
    checks_file = tmp_path / "checks.conf"
    checks_file.write_text("* || check_disk_usage --path / --max-percent 100\n")
    config_path.write_text(
        f"checks_file: {checks_file}\n"
        f"baseline_file: {tmp_path / 'baseline.yaml'}\n"
        f"state_db: {tmp_path / 'state.db'}\n"
        f"log_file: {tmp_path / 'chpc.log'}\n"
    )

    rc = _run(["--config", str(config_path), "check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "check_disk_usage" in out


def test_status_with_no_history(tmp_path, capsys):
    config_path = tmp_path / "chpc.yaml"
    config_path.write_text(f"state_db: {tmp_path / 'state.db'}\n")

    rc = _run(["--config", str(config_path), "status"])
    assert rc == 0
    assert "No check history" in capsys.readouterr().out


def test_baseline_show_and_recapture(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("chpc.baseline._default_gpu_probe", lambda: [])
    config_path = tmp_path / "chpc.yaml"
    config_path.write_text(f"baseline_file: {tmp_path / 'baseline.yaml'}\n")

    rc = _run(["--config", str(config_path), "baseline", "show"])
    assert rc == 1  # nothing captured yet

    rc = _run(["--config", str(config_path), "baseline", "recapture"])
    assert rc == 0

    rc = _run(["--config", str(config_path), "baseline", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cpu_count" in out


def test_resume_clears_state_even_without_backend(tmp_path, capsys):
    config_path = tmp_path / "chpc.yaml"
    config_path.write_text(
        f"state_db: {tmp_path / 'state.db'}\nresource_manager: none\n"
    )

    from chpc.state import State
    from datetime import datetime
    state = State(tmp_path / "state.db")
    state.mark_drained("k1", "check_disk_usage", "some reason", datetime(2026, 1, 1))
    assert state.active_drains() != []

    rc = _run(["--config", str(config_path), "resume", "--all"])
    assert rc == 0
    assert state.active_drains() == []
