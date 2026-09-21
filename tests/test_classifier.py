from slurm_monitor.classifier import CATEGORY_INFO, classify
from slurm_monitor.models import Category


def test_low_real_memory():
    assert classify("Low RealMemory") is Category.LOW_REAL_MEMORY


def test_low_cpu_topology():
    assert classify("Low socket*core*thread count, Low CPUs") is Category.LOW_CPU_TOPOLOGY


def test_not_responding():
    assert classify("Node is not responding") is Category.NOT_RESPONDING


def test_kill_task_failed():
    assert classify("Kill task failed") is Category.KILL_TASK_FAILED


def test_prolog_failed():
    assert classify("prolog failed") is Category.PROLOG_FAILED


def test_epilog_failed():
    assert classify("epilog failed") is Category.EPILOG_FAILED


def test_gres_mismatch():
    assert classify("gres/gpu count reported lower than configured") is Category.GRES_MISMATCH


def test_gpu_failure_xid():
    assert classify("Xid 79 detected on GPU 0") is Category.GPU_FAILURE


def test_unexpected_reboot():
    assert classify("Node unexpectedly rebooted") is Category.UNEXPECTED_REBOOT


def test_filesystem():
    assert classify("NFS mount unavailable") is Category.FILESYSTEM


def test_admin_drain():
    assert classify("draining node by request of admin") is Category.ADMIN_DRAIN


def test_empty_reason_is_unknown():
    assert classify("") is Category.UNKNOWN
    assert classify("   ") is Category.UNKNOWN


def test_unmatched_reason_is_unknown():
    assert classify("something completely unprecedented happened") is Category.UNKNOWN


def test_every_category_has_info():
    for category in Category:
        assert category in CATEGORY_INFO
        assert "title" in CATEGORY_INFO[category]
        assert "auto_fixable" in CATEGORY_INFO[category]
        assert "checks" in CATEGORY_INFO[category]
