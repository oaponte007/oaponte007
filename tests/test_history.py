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


def test_history_survives_reopen(tmp_path):
    db_path = tmp_path / "history.db"
    t0 = datetime(2026, 1, 1, 12, 0, 0)

    h1 = History(db_path, window=timedelta(hours=24))
    h1.record("node01", "low_real_memory", "Low RealMemory", t0)

    h2 = History(db_path, window=timedelta(hours=24))
    assert h2.is_recurring("node01", "low_real_memory", t0 + timedelta(hours=1)) is True
