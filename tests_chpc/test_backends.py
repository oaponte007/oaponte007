from chpc.backends.base import CommandResult
from chpc.backends.detect import detect_resource_manager
from chpc.backends.pbs import PBSBackend
from chpc.backends.slurm import SlurmBackend


class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def run(self, argv, mutating=False):
        self.calls.append((tuple(argv), mutating))
        key = tuple(argv)
        if key in self.responses:
            return self.responses[key]
        return CommandResult(argv, 0, "", "")


def test_slurm_drain_builds_expected_argv():
    runner = FakeRunner()
    backend = SlurmBackend(runner)
    assert backend.drain("node047", "AUTO-DRAIN: low memory") is True
    argv, mutating = runner.calls[0]
    assert argv == ("scontrol", "update", "NodeName=node047", "State=DRAIN",
                     "Reason=AUTO-DRAIN: low memory")
    assert mutating is True


def test_slurm_resume_builds_expected_argv():
    runner = FakeRunner()
    backend = SlurmBackend(runner)
    assert backend.resume("node047") is True
    argv, _ = runner.calls[0]
    assert argv == ("scontrol", "update", "NodeName=node047", "State=RESUME")


def test_slurm_is_drained_true():
    runner = FakeRunner({
        ("scontrol", "show", "node", "-o", "node047"):
            CommandResult([], 0, "NodeName=node047 State=DRAINED Reason=x", "")
    })
    backend = SlurmBackend(runner)
    assert backend.is_drained("node047") is True


def test_slurm_is_drained_false_for_idle():
    runner = FakeRunner({
        ("scontrol", "show", "node", "-o", "node047"):
            CommandResult([], 0, "NodeName=node047 State=IDLE", "")
    })
    backend = SlurmBackend(runner)
    assert backend.is_drained("node047") is False


def test_slurm_is_drained_none_on_command_failure():
    runner = FakeRunner({
        ("scontrol", "show", "node", "-o", "node047"): CommandResult([], 1, "", "no such node")
    })
    backend = SlurmBackend(runner)
    assert backend.is_drained("node047") is None


def test_slurm_down_star_counts_as_drained():
    runner = FakeRunner({
        ("scontrol", "show", "node", "-o", "node047"):
            CommandResult([], 0, "NodeName=node047 State=DOWN*", "")
    })
    backend = SlurmBackend(runner)
    assert backend.is_drained("node047") is True


def test_pbs_drain_builds_expected_argv():
    runner = FakeRunner()
    backend = PBSBackend(runner)
    assert backend.drain("node047", "AUTO-DRAIN: low memory") is True
    argv, mutating = runner.calls[0]
    assert argv == ("pbsnodes", "-o", "-N", "AUTO-DRAIN: low memory", "node047")
    assert mutating is True


def test_pbs_resume_builds_expected_argv():
    runner = FakeRunner()
    backend = PBSBackend(runner)
    assert backend.resume("node047") is True
    argv, _ = runner.calls[0]
    assert argv == ("pbsnodes", "-c", "node047")


def test_pbs_is_drained_true_for_offline():
    runner = FakeRunner({
        ("pbsnodes", "node047"): CommandResult([], 0, "node047\n     state = offline\n", "")
    })
    backend = PBSBackend(runner)
    assert backend.is_drained("node047") is True


def test_pbs_is_drained_false_for_free():
    runner = FakeRunner({
        ("pbsnodes", "node047"): CommandResult([], 0, "node047\n     state = free\n", "")
    })
    backend = PBSBackend(runner)
    assert backend.is_drained("node047") is False


def test_pbs_custom_flags_from_config():
    runner = FakeRunner()
    backend = PBSBackend(runner, offline_flag="--offline", note_flag="--note", clear_flag="--clear")
    backend.drain("node047", "reason")
    argv, _ = runner.calls[0]
    assert argv == ("pbsnodes", "--offline", "--note", "reason", "node047")


def test_detect_prefers_explicit_override():
    assert detect_resource_manager("pbs") == "pbs"
    assert detect_resource_manager("slurm") == "slurm"
    assert detect_resource_manager("none") == "none"


def test_detect_falls_back_to_none_when_nothing_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert detect_resource_manager("auto") == "none"


def test_detect_finds_slurm_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/scontrol" if name == "scontrol" else None)
    assert detect_resource_manager("auto") == "slurm"
