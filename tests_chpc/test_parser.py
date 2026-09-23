import pytest

from chpc.checks.parser import parse_file, parse_line


def test_parse_simple_builtin_check():
    spec = parse_line("*  || check_real_memory --tolerance-percent 2")
    assert spec.hostmask == "*"
    assert spec.name == "check_real_memory"
    assert spec.args == ["--tolerance-percent", "2"]


def test_parse_hostmask_glob():
    spec = parse_line("gpu* || check_gpu_count")
    assert spec.hostmask == "gpu*"
    assert spec.name == "check_gpu_count"
    assert spec.args == []


def test_parse_command_check_preserves_embedded_double_pipes():
    spec = parse_line("*  || command || /usr/local/bin/check.sh --arg || echo fallback")
    assert spec.name == "command"
    assert spec.args == ["/usr/local/bin/check.sh --arg || echo fallback"]


def test_parse_command_check_with_shell_and_and():
    spec = parse_line("*  || command || test -f /scratch/.mounted && df -h /scratch")
    assert spec.args == ["test -f /scratch/.mounted && df -h /scratch"]


def test_check_key_is_stable():
    spec1 = parse_line("*  || check_disk_usage --path / --max-percent 90")
    spec2 = parse_line("*  || check_disk_usage --path / --max-percent 90")
    assert spec1.key == spec2.key


def test_check_key_differs_by_args():
    spec1 = parse_line("*  || check_disk_usage --path / --max-percent 90")
    spec2 = parse_line("*  || check_disk_usage --path /tmp --max-percent 90")
    assert spec1.key != spec2.key


def test_missing_separator_raises():
    with pytest.raises(ValueError):
        parse_line("check_real_memory --tolerance-percent 2")


def test_empty_hostmask_raises():
    with pytest.raises(ValueError):
        parse_line(" || check_real_memory")


def test_command_with_no_body_raises():
    with pytest.raises(ValueError):
        parse_line("* || command ||   ")


def test_parse_file_skips_comments_and_blank_lines(tmp_path):
    p = tmp_path / "checks.conf"
    p.write_text(
        "# a comment\n"
        "\n"
        "*  || check_disk_usage --path / --max-percent 90\n"
        "   \n"
        "gpu*  || check_gpu_count\n"
    )
    specs = parse_file(p)
    assert len(specs) == 2
    assert specs[0].name == "check_disk_usage"
    assert specs[1].hostmask == "gpu*"


def test_parse_file_reports_line_number_on_error(tmp_path):
    p = tmp_path / "checks.conf"
    p.write_text("*  || check_disk_usage --path / --max-percent 90\nbroken line no separator\n")
    with pytest.raises(ValueError) as exc_info:
        parse_file(p)
    assert ":2:" in str(exc_info.value)
