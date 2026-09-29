import subprocess
import sys
from pathlib import Path

from chpc_helper_core import wizard
from chpc_python_helper.cli import CONFIG, build_parser
from chpc_python_helper.library import get_template


def _run(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def test_list_and_show_and_describe_smoke(capsys):
    assert _run(["list"]) == 0
    out = capsys.readouterr().out
    assert "node_drain_resume" in out

    assert _run(["show", "retry_wrapper"]) == 0
    out = capsys.readouterr().out
    assert "COMMAND_TO_RUN" in out

    assert _run(["describe", "drain a node"]) == 0
    out = capsys.readouterr().out
    assert "node_drain_resume" in out


def test_build_non_interactive_writes_valid_python(tmp_path):
    out_path = tmp_path / "drain.py"
    rc = _run([
        "build", "node_drain_resume",
        "--var", "NODE_LIST=node007 node008",
        "--var", "REASON=Testing",
        "--toggle", "REQUIRE_CONFIRMATION=off",
        "--toggle-group", "SCHEDULER=slurm",
        "--toggle-group", "ACTION=drain",
        "--out", str(out_path),
    ])
    assert rc == 0
    text = out_path.read_text()
    assert "node007 node008" in text
    assert '"scontrol"' in text
    assert "{{" not in text

    result = subprocess.run([sys.executable, "-m", "py_compile", str(out_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_build_command_with_quotes_is_safely_escaped(tmp_path):
    """The whole point of _prepare_variables: a command containing a
    double quote must not corrupt the generated Python source.
    """
    out_path = tmp_path / "retry.py"
    tricky_command = 'echo "hello \\"world\\"" && exit 1'
    rc = _run([
        "build", "retry_wrapper",
        "--var", f"COMMAND_TO_RUN={tricky_command}",
        "--var", "COMMAND_DESCRIPTION=a tricky command",
        "--yes",
        "--out", str(out_path),
    ])
    assert rc == 0
    result = subprocess.run([sys.executable, "-m", "py_compile", str(out_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    # actually import/run the generated COMMAND assignment to prove the
    # round-trip is exact, not just "didn't crash the parser"
    namespace = {}
    exec(compile(out_path.read_text(), str(out_path), "exec"), namespace)
    assert namespace["COMMAND"] == tricky_command


def test_build_non_interactive_defaults_via_yes(tmp_path):
    out_path = tmp_path / "wait.py"
    rc = _run(["build", "wait_for_condition", "--yes", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()


def test_interactive_wizard_end_to_end(tmp_path):
    tmpl = get_template("lockfile_singleton")
    answers = iter([
        "/tmp/test.lock",
        "nightly sync",
        "echo hi",
        "wait",
        "y",
    ])
    out_path = tmp_path / "lock.py"
    result_path = wizard.build_interactive(
        tmpl, out_path,
        input_func=lambda prompt: next(answers),
        print_func=lambda *a, **k: None,
        syntax_checker=CONFIG.syntax_checker,
        executable=CONFIG.executable,
        syntax_check_label=CONFIG.syntax_check_label,
        prepare_variables=CONFIG.prepare_variables,
    )
    assert result_path == out_path
    text = out_path.read_text()
    assert "/tmp/test.lock" in text
    assert "fcntl.LOCK_EX)" in text  # LOCK_WAIT branch, not LOCK_SKIP
    assert "echo hi" in text
    result = subprocess.run([sys.executable, "-m", "py_compile", str(out_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
