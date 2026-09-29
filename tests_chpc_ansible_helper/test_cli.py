import yaml

from chpc_ansible_helper.cli import CONFIG, build_parser
from chpc_ansible_helper.library import get_template
from chpc_helper_core import wizard


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


def test_build_non_interactive_writes_valid_yaml(tmp_path):
    out_path = tmp_path / "drain.yml"
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
    assert "scontrol" in text
    assert "{{NODE_LIST}}" not in text  # our own placeholder resolved; "{{ node_list }}" (Jinja) is expected to remain

    docs = list(yaml.safe_load_all(text))
    assert docs[0][0]["hosts"] == "localhost"


def test_build_command_with_special_chars_is_safely_quoted(tmp_path):
    """The whole point of _prepare_variables: a value containing YAML-
    significant characters (colon, quotes) must not corrupt the
    generated playbook's structure.
    """
    out_path = tmp_path / "retry.yml"
    tricky_reason = 'weird: value "with" quotes'
    rc = _run([
        "build", "retry_wrapper",
        "--var", f"COMMAND_DESCRIPTION={tricky_reason}",
        "--var", "COMMAND_TO_RUN=echo hi",
        "--yes",
        "--out", str(out_path),
    ])
    assert rc == 0
    docs = list(yaml.safe_load_all(out_path.read_text()))
    task_name = docs[0][0]["tasks"][0]["name"]
    assert task_name == tricky_reason


def test_build_non_interactive_defaults_via_yes(tmp_path):
    out_path = tmp_path / "wait.yml"
    rc = _run(["build", "wait_for_condition", "--yes", "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()
    # ansible playbooks aren't chmod +x'd/run directly
    assert not (out_path.stat().st_mode & 0o111)


def test_interactive_wizard_end_to_end(tmp_path):
    tmpl = get_template("lockfile_singleton")
    answers = iter([
        "/tmp/test.lock",
        "nightly sync",
        "echo hi",
        "all",
        "wait",
        "y",
    ])
    out_path = tmp_path / "lock.yml"
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
    docs = list(yaml.safe_load_all(out_path.read_text()))
    assert "flock" in str(docs)
