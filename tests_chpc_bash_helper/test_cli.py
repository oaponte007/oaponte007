import subprocess
from pathlib import Path

from chpc_bash_helper import wizard
from chpc_bash_helper.cli import build_parser
from chpc_bash_helper.library import get_template


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


def test_build_non_interactive_writes_valid_script(tmp_path):
    out_path = tmp_path / "drain.sh"
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
    assert "scontrol update NodeName=" in text
    assert "{{" not in text

    result = subprocess.run(["bash", "-n", str(out_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_build_non_interactive_defaults_via_yes(tmp_path):
    out_path = tmp_path / "wait.sh"
    rc = _run(["build", "wait_for_condition", "--yes", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    assert out_path.stat().st_mode & 0o111  # executable bit set


def test_build_bad_var_flag_errors_cleanly():
    try:
        _run(["build", "retry_wrapper", "--var", "NO_EQUALS_SIGN", "--yes"])
        assert False, "expected SystemExit"
    except SystemExit:
        pass


def test_interactive_wizard_end_to_end(tmp_path):
    tmpl = get_template("lockfile_singleton")
    # Answers in declared order: LOCK_FILE_PATH, COMMAND_DESCRIPTION,
    # COMMAND_TO_RUN (variables), then LOCK_MODE (toggle_group), then the
    # final "write it now?" confirmation from build_interactive.
    answers = iter([
        "/tmp/test.lock",
        "nightly sync",
        "echo hi",
        "wait",
        "y",
    ])
    printed = []
    out_path = tmp_path / "lock.sh"
    result_path = wizard.build_interactive(
        tmpl, out_path,
        input_func=lambda prompt: next(answers),
        print_func=lambda *a, **k: printed.append(a),
    )
    assert result_path == out_path
    text = out_path.read_text()
    assert "/tmp/test.lock" in text
    assert "flock 200" in text  # LOCK_WAIT branch, not LOCK_SKIP
    assert "echo hi" in text


def test_interactive_wizard_abort_on_no_confirmation(tmp_path):
    tmpl = get_template("retry_wrapper")
    answers = iter([
        "a command",       # COMMAND_DESCRIPTION
        "echo hi",          # COMMAND_TO_RUN
        "3",                 # MAX_ATTEMPTS
        "2",                 # INITIAL_DELAY_SECONDS
        "exponential",       # BACKOFF_MODE
        "n",                 # decline the final "write it now?" prompt
    ])
    out_path = tmp_path / "retry.sh"
    try:
        wizard.build_interactive(
            tmpl, out_path,
            input_func=lambda prompt: next(answers),
            print_func=lambda *a, **k: None,
        )
        assert False, "expected WizardAbort"
    except wizard.WizardAbort:
        pass
    assert not out_path.exists()
