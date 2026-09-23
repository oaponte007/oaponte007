from datetime import datetime, timedelta

from chpc.state import State


def test_record_result_increments_and_resets_consecutive_fails(tmp_path):
    state = State(tmp_path / "state.db")
    t0 = datetime(2026, 1, 1)

    assert state.record_result("k1", "check_x", False, "fail 1", t0) == 1
    assert state.record_result("k1", "check_x", False, "fail 2", t0 + timedelta(minutes=1)) == 2
    assert state.record_result("k1", "check_x", True, "ok now", t0 + timedelta(minutes=2)) == 0
    assert state.record_result("k1", "check_x", False, "fail again", t0 + timedelta(minutes=3)) == 1


def test_get_returns_latest_row(tmp_path):
    state = State(tmp_path / "state.db")
    t0 = datetime(2026, 1, 1)
    state.record_result("k1", "check_x", False, "detail A", t0)

    row = state.get("k1")
    assert row.check_name == "check_x"
    assert row.consecutive_fails == 1
    assert row.last_detail == "detail A"
    assert row.last_ok is False


def test_mark_and_clear_drained(tmp_path):
    state = State(tmp_path / "state.db")
    t0 = datetime(2026, 1, 1)

    assert state.is_active("k1") is False
    state.mark_drained("k1", "check_x", "reason text", t0)
    assert state.is_active("k1") is True

    drains = state.active_drains()
    assert len(drains) == 1
    assert drains[0].reason == "reason text"

    state.record_result("k1", "check_x", False, "still failing", t0)  # bump consecutive_fails
    state.clear_drained("k1")
    assert state.is_active("k1") is False
    assert state.get("k1").consecutive_fails == 0


def test_clear_all_drained(tmp_path):
    state = State(tmp_path / "state.db")
    t0 = datetime(2026, 1, 1)
    state.mark_drained("k1", "check_x", "r1", t0)
    state.mark_drained("k2", "check_y", "r2", t0)

    state.clear_all_drained()

    assert state.active_drains() == []


def test_state_survives_reopen(tmp_path):
    db_path = tmp_path / "state.db"
    t0 = datetime(2026, 1, 1)
    s1 = State(db_path)
    s1.record_result("k1", "check_x", False, "detail", t0)
    s1.mark_drained("k1", "check_x", "reason", t0)

    s2 = State(db_path)
    assert s2.is_active("k1") is True
    assert s2.get("k1").consecutive_fails == 1
