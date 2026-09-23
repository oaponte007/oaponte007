from datetime import datetime, timedelta

import pytest

from chpc.checks.base import CommandOutput
from chpc.config import Config
from chpc.daemon import Daemon
from chpc.state import State


class FakeBackend:
    name = "fake"

    def __init__(self, is_drained_return=None):
        self.drain_calls = []
        self.resume_calls = []
        self.is_drained_return = is_drained_return

    def drain(self, node, reason):
        self.drain_calls.append((node, reason))
        return True

    def resume(self, node):
        self.resume_calls.append(node)
        return True

    def is_drained(self, node):
        return self.is_drained_return


def make_daemon(tmp_path, command_ok, failure_threshold=2, auto_resume=None,
                 backend=None, hostmask="*"):
    checks_file = tmp_path / "checks.conf"
    checks_file.write_text(f"{hostmask} || command || true\n")
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text("{}\n")

    config = Config(
        checks_file=checks_file,
        baseline_file=baseline_file,
        state_db=tmp_path / "state.db",
        log_file=tmp_path / "chpc.log",
        failure_threshold=failure_threshold,
        auto_resume_categories=auto_resume or [],
    )
    state = State(config.state_db)
    backend = backend if backend is not None else FakeBackend()

    holder = {"ok": command_ok}

    def fake_run(argv, timeout=20, shell=False):
        return CommandOutput(argv, 0 if holder["ok"] else 1, "", "")

    daemon = Daemon(config, backend, state, hostname="node047",
                     ctx_overrides={"run": fake_run})
    return daemon, holder, backend, state


def test_failing_check_under_threshold_only_monitors(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=3)

    actions = daemon.run_once(now=datetime(2026, 1, 1))
    assert actions[0].action == "monitoring"
    assert actions[0].consecutive_fails == 1
    assert backend.drain_calls == []


def test_failing_check_reaching_threshold_drains_with_reason(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=2)

    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))
    actions = daemon.run_once(now=datetime(2026, 1, 1, 9, 1))

    assert actions[0].action == "drain"
    assert len(backend.drain_calls) == 1
    node, reason = backend.drain_calls[0]
    assert node == "node047"
    assert "command" in reason
    assert "chpc explain command" in reason


def test_already_drained_check_is_not_redrained(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=2)

    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))
    daemon.run_once(now=datetime(2026, 1, 1, 9, 1))  # drains here
    assert len(backend.drain_calls) == 1

    actions = daemon.run_once(now=datetime(2026, 1, 1, 9, 2))
    assert actions[0].action == "already_drained"
    assert len(backend.drain_calls) == 1  # still just one


def test_recovered_check_without_auto_resume_stays_marked_active(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=2)
    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))
    daemon.run_once(now=datetime(2026, 1, 1, 9, 1))  # drains
    assert len(backend.drain_calls) == 1

    holder["ok"] = True
    actions = daemon.run_once(now=datetime(2026, 1, 1, 9, 2))

    assert actions[0].action == "recovered_manual"
    assert backend.resume_calls == []  # chpc never resumes on its own by default


def test_recovered_check_with_auto_resume_opt_in_clears_and_resumes(tmp_path):
    daemon, holder, backend, state = make_daemon(
        tmp_path, command_ok=False, failure_threshold=2, auto_resume=["command"]
    )
    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))
    daemon.run_once(now=datetime(2026, 1, 1, 9, 1))  # drains
    assert len(backend.drain_calls) == 1

    holder["ok"] = True
    actions = daemon.run_once(now=datetime(2026, 1, 1, 9, 2))

    assert actions[0].action == "resume"
    assert backend.resume_calls == ["node047"]
    assert state.active_drains() == []


def test_manual_resume_by_admin_is_reconciled_and_resets_debounce(tmp_path):
    backend = FakeBackend(is_drained_return=None)
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=2,
                                                   backend=backend)
    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))
    daemon.run_once(now=datetime(2026, 1, 1, 9, 1))  # drains
    assert state.active_drains() != []

    # Admin manually resumed the node out-of-band; RM now reports healthy.
    backend.is_drained_return = False

    actions = daemon.run_once(now=datetime(2026, 1, 1, 9, 2))

    assert state.active_drains() == []
    # still failing, but debounce restarted from 1, not straight back to drain
    assert actions[0].action == "monitoring"
    assert actions[0].consecutive_fails == 1


def test_hostmask_mismatch_skips_check(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, hostmask="gpu*")

    actions = daemon.run_once(now=datetime(2026, 1, 1))
    assert actions == []
    assert backend.drain_calls == []


def test_unknown_check_name_reported_as_error(tmp_path):
    checks_file = tmp_path / "checks.conf"
    checks_file.write_text("* || totally_made_up_check\n")
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text("{}\n")
    config = Config(checks_file=checks_file, baseline_file=baseline_file,
                     state_db=tmp_path / "state.db", log_file=tmp_path / "chpc.log")
    daemon = Daemon(config, FakeBackend(), State(config.state_db), hostname="node047")

    actions = daemon.run_once(now=datetime(2026, 1, 1))
    assert actions[0].action == "error"


def test_malformed_checks_file_reports_single_error_action(tmp_path):
    checks_file = tmp_path / "checks.conf"
    checks_file.write_text("this line has no separator\n")
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text("{}\n")
    config = Config(checks_file=checks_file, baseline_file=baseline_file,
                     state_db=tmp_path / "state.db", log_file=tmp_path / "chpc.log")
    daemon = Daemon(config, FakeBackend(), State(config.state_db), hostname="node047")

    actions = daemon.run_once(now=datetime(2026, 1, 1))
    assert len(actions) == 1
    assert actions[0].action == "error"


def test_drain_writes_recovery_instructions_to_log_file(tmp_path):
    daemon, holder, backend, state = make_daemon(tmp_path, command_ok=False, failure_threshold=1)
    daemon.run_once(now=datetime(2026, 1, 1, 9, 0))

    log_text = daemon.config.log_file.read_text()
    assert "RECOVERY STEPS" in log_text
    assert "command" in log_text
