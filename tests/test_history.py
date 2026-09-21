from datetime import datetime, timedelta

import pytest

from slurm_monitor.history import History


@pytest.fixture
def history(tmp_path):
    return History(tmp_path / "history.db", window=timedelta(hours=24))


def test_first_occurrence_is_not_recurring(history):
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert history.is_recurring("node01", "low_real_memory", now) is False


def test_second_occurrence_within_window_is_recurring(history):
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    history.record("node01", "low_real_memory", "Low RealMemory", t0)

    t1 = t0 + timedelta(hours=5)
    assert history.is_recurring("node01", "low_real_memory", t1) is True


def test_occurrence_outside_24h_window_is_not_recurring(history):
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    history.record("node01", "low_real_memory", "Low RealMemory", t0)

    t1 = t0 + timedelta(hours=25)
    assert history.is_recurring("node01", "low_real_memory", t1) is False


def test_different_category_does_not_count_as_recurring(history):
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    history.record("node01", "low_real_memory", "Low RealMemory", t0)

    t1 = t0 + timedelta(hours=1)
    assert history.is_recurring("node01", "not_responding", t1) is False


def test_different_node_does_not_count_as_recurring(history):
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    history.record("node01", "low_real_memory", "Low RealMemory", t0)

    t1 = t0 + timedelta(hours=1)
    assert history.is_recurring("node02", "low_real_memory", t1) is False


def test_quarantine_lifecycle(history):
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert history.is_quarantined("node01", "low_real_memory") is False

    history.mark_quarantined("node01", "low_real_memory", "auto-drain note", now)
    assert history.is_quarantined("node01", "low_real_memory") is True
    assert history.is_quarantined_any("node01") is True
    assert history.is_quarantined("node01", "not_responding") is False

    history.clear_quarantine("node01", "low_real_memory")
    assert history.is_quarantined("node01", "low_real_memory") is False


def test_clear_quarantine_without_category_clears_all(history):
    now = datetime(2026, 1, 1, 12, 0, 0)
    history.mark_quarantined("node01", "low_real_memory", "note1", now)
    history.mark_quarantined("node01", "gpu_failure", "note2", now)

    history.clear_quarantine("node01")

    assert history.is_quarantined("node01", "low_real_memory") is False
    assert history.is_quarantined("node01", "gpu_failure") is False


def test_prior_occurrences_ordered_and_scoped(history):
    t0 = datetime(2026, 1, 1, 8, 0, 0)
    t1 = t0 + timedelta(hours=2)
    history.record("node01", "not_responding", "Node is not responding", t0)
    history.record("node01", "not_responding", "Node is not responding", t1)

    prior = history.prior_occurrences("node01", "not_responding", t1 + timedelta(hours=1))
    assert [o.detected_at for o in prior] == [t0, t1]


def test_log_action_and_query_roundtrip(history):
    t0 = datetime(2026, 1, 1, 9, 0, 0)
    history.log_action(
        node="node047", category="low_real_memory", action="manual_review",
        reason="Low RealMemory", note="diagnostic report text", ts=t0, success=None,
        occurrences_in_window=1,
    )

    entries = history.query_actions()
    assert len(entries) == 1
    e = entries[0]
    assert e.node == "node047"
    assert e.action == "manual_review"
    assert e.success is None
    assert e.ts == t0


def test_query_actions_filters_by_node_category_action(history):
    t0 = datetime(2026, 1, 1, 9, 0, 0)
    history.log_action(node="node047", category="low_real_memory", action="manual_review",
                        reason="Low RealMemory", note="", ts=t0)
    history.log_action(node="node047", category="low_real_memory", action="force_drain",
                        reason="Low RealMemory", note="", ts=t0 + timedelta(hours=5), success=True,
                        occurrences_in_window=2)
    history.log_action(node="node012", category="not_responding", action="resume",
                        reason="Node is not responding", note="", ts=t0, success=True)

    assert len(history.query_actions(node="node047")) == 2
    assert len(history.query_actions(category="not_responding")) == 1
    assert len(history.query_actions(action="force_drain")) == 1

    force_drain = history.query_actions(action="force_drain")[0]
    assert force_drain.success is True
    assert force_drain.occurrences_in_window == 2


def test_query_actions_since_filter_and_ordering(history):
    t0 = datetime(2026, 1, 1, 9, 0, 0)
    history.log_action(node="node047", category="x", action="ignore", reason="", note="", ts=t0)
    history.log_action(node="node047", category="x", action="ignore", reason="", note="",
                        ts=t0 + timedelta(hours=2))

    recent = history.query_actions(since=t0 + timedelta(hours=1))
    assert len(recent) == 1
    assert recent[0].ts == t0 + timedelta(hours=2)

    all_entries = history.query_actions()
    # newest first
    assert all_entries[0].ts > all_entries[1].ts


def test_history_survives_reopen(tmp_path):
    db_path = tmp_path / "history.db"
    t0 = datetime(2026, 1, 1, 12, 0, 0)

    h1 = History(db_path, window=timedelta(hours=24))
    h1.record("node01", "low_real_memory", "Low RealMemory", t0)

    h2 = History(db_path, window=timedelta(hours=24))
    assert h2.is_recurring("node01", "low_real_memory", t0 + timedelta(hours=1)) is True
