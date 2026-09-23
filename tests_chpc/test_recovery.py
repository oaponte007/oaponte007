from chpc import recovery


def test_known_check_has_title_and_steps():
    assert "baseline" in recovery.title_for("check_real_memory").lower() or \
           "memory" in recovery.title_for("check_real_memory").lower()
    steps = recovery.steps_for("check_real_memory")
    assert len(steps) >= 3
    assert any("chpc resume" in s for s in steps)


def test_unknown_check_falls_back_to_default():
    assert recovery.title_for("check_totally_unknown") == recovery.DEFAULT_INFO[0]


def test_build_reason_includes_pointer_to_explain(monkeypatch):
    reason = recovery.build_reason("check_disk_usage", "path=/ used=95.0%", 3, "node047")
    assert "check_disk_usage" in reason
    assert "3x" in reason
    assert "chpc explain check_disk_usage" in reason
    assert "node047" in reason


def test_build_reason_truncates_long_detail():
    long_detail = "x" * 500
    reason = recovery.build_reason("check_disk_usage", long_detail, 1, "node047")
    assert len(reason) < len(long_detail) + 200


def test_build_instructions_includes_all_steps():
    text = recovery.build_instructions("check_gpu_count", "gpu_count=1 baseline=2")
    for step in recovery.steps_for("check_gpu_count"):
        assert step in text
    assert "gpu_count=1 baseline=2" in text
