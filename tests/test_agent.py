from datetime import datetime, timedelta

import pytest

from slurm_monitor.agent import Agent
from slurm_monitor.history import History
from slurm_monitor.models import Category, NodeState
from slurm_monitor.notify import Notifier
from slurm_monitor.slurm_client import CommandResult, SlurmClient


class FakeSlurmClient(SlurmClient):
    """A SlurmClient whose reads are canned and whose writes are recorded,
    so agent decision logic can be tested without a real cluster."""

    def __init__(self, node_states):
        super().__init__(dry_run=False)
        self._node_states = {s.name: s for s in node_states}
        self.calls: list[str] = []

    def set_state(self, node_state: NodeState) -> None:
        self._node_states[node_state.name] = node_state

    def get_node_states(self):
        return list(self._node_states.values())

    def get_node_state(self, node):
        return self._node_states.get(node)

    def run(self, command, mutating=False):
        self.calls.append(command)
        return CommandResult(command, 0, "", "")


def make_node(name, state, reason):
    return NodeState(name=name, state=state, reason=reason, raw={})


@pytest.fixture
def history(tmp_path):
    return History(tmp_path / "history.db", window=timedelta(hours=24))


def test_non_fixable_first_occurrence_is_manual_review_and_untouched(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    now = datetime(2026, 1, 1, 9, 0, 0)
    decisions = agent.poll_once(now=now)

    assert len(decisions) == 1
    d = decisions[0]
    assert d.node == "node047"
    assert d.category is Category.LOW_REAL_MEMORY
    assert d.action == "manual_review"
    assert not any("State=DRAIN" in c or "State=RESUME" in c for c in client.calls)
    assert not history.is_quarantined("node047", "low_real_memory")


def test_admin_drain_is_ignored(history):
    node = make_node("node099", "DRAINED", "Administrator requested maintenance")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    decisions = agent.poll_once(now=datetime(2026, 1, 1, 9, 0, 0))

    assert decisions[0].action == "ignore"
    assert decisions[0].category is Category.ADMIN_DRAIN
    assert client.calls == []


def test_auto_fixable_category_self_heals_and_resumes(history):
    node = make_node("node012", "DOWN*", "Node is not responding")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    decisions = agent.poll_once(now=datetime(2026, 1, 1, 9, 0, 0))

    assert decisions[0].action == "resume"
    assert any("systemctl restart slurmd" in c for c in client.calls)
    assert any("State=RESUME" in c for c in client.calls)


def test_recurrence_within_24h_triggers_force_drain_with_explanatory_note(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    first = agent.poll_once(now=t0)[0]
    assert first.action == "manual_review"

    # Same node, same problem, still within the 24h window.
    t1 = t0 + timedelta(hours=5)
    second = agent.poll_once(now=t1)[0]

    assert second.action == "force_drain"
    assert second.occurrences_in_window == 2
    assert "AUTO-DRAIN" in second.note
    assert "Low RealMemory" in second.note or "low_real_memory" in second.note.lower()
    assert history.is_quarantined("node047", "low_real_memory")
    assert any("State=DRAIN" in c and "node047" in c for c in client.calls)


def test_recurrence_outside_24h_window_does_not_force_drain(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    agent.poll_once(now=t0)

    t1 = t0 + timedelta(hours=25)
    second = agent.poll_once(now=t1)[0]

    assert second.action == "manual_review"
    assert not history.is_quarantined("node047", "low_real_memory")


def test_quarantined_node_is_left_alone_on_subsequent_polls(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    agent.poll_once(now=t0)
    t1 = t0 + timedelta(hours=1)
    agent.poll_once(now=t1)  # triggers force_drain + quarantine
    drain_calls_after_second_poll = len([c for c in client.calls if "State=DRAIN" in c])

    t2 = t1 + timedelta(hours=1)
    third = agent.poll_once(now=t2)[0]

    assert third.action == "manual_review"
    assert "already force-drained" in third.note
    drain_calls_after_third_poll = len([c for c in client.calls if "State=DRAIN" in c])
    assert drain_calls_after_third_poll == drain_calls_after_second_poll


def test_every_decision_is_written_to_the_audit_log(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    agent.poll_once(now=t0)

    entries = history.query_actions(node="node047")
    assert len(entries) == 1
    assert entries[0].action == "manual_review"
    assert entries[0].reason == "Low RealMemory"


def test_force_drain_and_resume_log_their_success_flag(history):
    drain_node = make_node("node047", "DRAINED", "Low RealMemory")
    resume_node = make_node("node012", "DOWN*", "Node is not responding")
    client = FakeSlurmClient([drain_node, resume_node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    agent.poll_once(now=t0)
    agent.poll_once(now=t0 + timedelta(hours=1))  # triggers the force_drain on node047

    drain_entry = history.query_actions(node="node047", action="force_drain")[0]
    assert drain_entry.success is True
    assert drain_entry.occurrences_in_window == 2

    resume_entry = history.query_actions(node="node012", action="resume")[0]
    assert resume_entry.success is True


def test_ignored_admin_drains_are_still_logged_for_full_audit_trail(history):
    node = make_node("node099", "DRAINED", "Administrator requested maintenance")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    agent.poll_once(now=datetime(2026, 1, 1, 9, 0, 0))

    entries = history.query_actions(node="node099")
    assert len(entries) == 1
    assert entries[0].action == "ignore"


def test_recovered_node_clears_quarantine(history):
    node = make_node("node047", "DRAINED", "Low RealMemory")
    client = FakeSlurmClient([node])
    agent = Agent(client, history, notifier=Notifier(None))

    t0 = datetime(2026, 1, 1, 9, 0, 0)
    agent.poll_once(now=t0)
    agent.poll_once(now=t0 + timedelta(hours=1))
    assert history.is_quarantined("node047", "low_real_memory")

    client.set_state(make_node("node047", "IDLE", ""))
    agent.poll_once(now=t0 + timedelta(hours=2))

    assert not history.is_quarantined("node047", "low_real_memory")
