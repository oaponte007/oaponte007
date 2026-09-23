from pathlib import Path

from chpc.config import Config


def test_defaults():
    config = Config()
    assert config.dry_run is True
    assert config.cpu_affinity == [0]
    assert config.resource_manager == "auto"
    assert config.failure_threshold == 3


def test_load_none_path_returns_defaults():
    config = Config.load(None)
    assert config.dry_run is True


def test_load_from_yaml_overrides_defaults(tmp_path):
    p = tmp_path / "chpc.yaml"
    p.write_text(
        "dry_run: false\n"
        "cpu_affinity: [2]\n"
        "failure_threshold: 5\n"
        "checks_file: /tmp/custom_checks.conf\n"
        "resource_manager: pbs\n"
    )
    config = Config.load(str(p))
    assert config.dry_run is False
    assert config.cpu_affinity == [2]
    assert config.failure_threshold == 5
    assert config.checks_file == Path("/tmp/custom_checks.conf")
    assert config.resource_manager == "pbs"


def test_load_ignores_unknown_keys(tmp_path):
    p = tmp_path / "chpc.yaml"
    p.write_text("dry_run: false\nsome_future_field: 123\n")
    config = Config.load(str(p))
    assert config.dry_run is False


def test_ensure_dirs_creates_parents(tmp_path):
    config = Config(
        checks_file=tmp_path / "a" / "checks.conf",
        baseline_file=tmp_path / "b" / "baseline.yaml",
        state_db=tmp_path / "c" / "state.db",
        log_file=tmp_path / "d" / "chpc.log",
    )
    config.ensure_dirs()
    assert (tmp_path / "a").is_dir()
    assert (tmp_path / "b").is_dir()
    assert (tmp_path / "c").is_dir()
    assert (tmp_path / "d").is_dir()
