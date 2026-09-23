import pytest

from chpc.checks.base import CheckContext, CommandOutput
from chpc.checks.builtin import (
    BUILTIN_CHECKS,
    check_command,
    check_cpu_count,
    check_dir_size,
    check_disk_usage,
    check_gpu_count,
    check_load_average,
    check_mount_present,
    check_network_interface,
    check_real_memory,
    check_swap_usage,
    check_zombie_processes,
    parse_kv,
)


def test_parse_kv_supports_space_and_equals_forms():
    assert parse_kv(["--path", "/scratch", "--max-percent=90"]) == {
        "path": "/scratch", "max-percent": "90"
    }


def test_parse_kv_bool_flag():
    assert parse_kv(["--allow-down"], bool_flags=("allow-down",)) == {"allow-down": True}


def test_all_builtin_names_are_registered():
    for name in ("check_real_memory", "check_cpu_count", "check_load_average",
                 "check_disk_usage", "check_dir_size", "check_swap_usage", "check_mount_present",
                 "check_zombie_processes", "check_gpu_count", "check_network_interface",
                 "command"):
        assert name in BUILTIN_CHECKS


def _write_meminfo(tmp_path, mem_total_kb, swap_total_kb=0, swap_free_kb=0):
    p = tmp_path / "meminfo"
    p.write_text(
        f"MemTotal:       {mem_total_kb} kB\n"
        f"MemFree:        1000 kB\n"
        f"SwapTotal:      {swap_total_kb} kB\n"
        f"SwapFree:       {swap_free_kb} kB\n"
    )
    return str(p)


class TestRealMemory:
    def test_within_tolerance_passes(self, tmp_path):
        meminfo = _write_meminfo(tmp_path, 1_000_000)
        ctx = CheckContext(hostname="n1", baseline={"real_memory_kb": 1_005_000},
                            proc_meminfo=meminfo)
        result = check_real_memory(["--tolerance-percent", "2"], ctx)
        assert result.ok

    def test_outside_tolerance_fails(self, tmp_path):
        meminfo = _write_meminfo(tmp_path, 900_000)
        ctx = CheckContext(hostname="n1", baseline={"real_memory_kb": 1_000_000},
                            proc_meminfo=meminfo)
        result = check_real_memory(["--tolerance-percent", "2"], ctx)
        assert not result.ok
        assert "900000" in result.detail

    def test_missing_baseline_skips_ok(self, tmp_path):
        meminfo = _write_meminfo(tmp_path, 900_000)
        ctx = CheckContext(hostname="n1", baseline={}, proc_meminfo=meminfo)
        result = check_real_memory([], ctx)
        assert result.ok
        assert "not captured" in result.detail


class TestCpuCount:
    def test_matches_baseline(self):
        ctx = CheckContext(hostname="n1", baseline={"cpu_count": 32}, cpu_count=32)
        assert check_cpu_count([], ctx).ok

    def test_mismatch_fails(self):
        ctx = CheckContext(hostname="n1", baseline={"cpu_count": 32}, cpu_count=16)
        result = check_cpu_count([], ctx)
        assert not result.ok

    def test_tolerance_allows_small_diff(self):
        ctx = CheckContext(hostname="n1", baseline={"cpu_count": 32}, cpu_count=31)
        assert check_cpu_count(["--tolerance", "1"], ctx).ok


class TestLoadAverage:
    def test_under_ceiling_passes(self):
        ctx = CheckContext(hostname="n1", cpu_count=4, loadavg=lambda: (2.0, 2.0, 2.0))
        result = check_load_average(["--max-per-core", "1.0"], ctx)
        assert result.ok  # 2.0/4 = 0.5 <= 1.0

    def test_over_ceiling_fails(self):
        ctx = CheckContext(hostname="n1", cpu_count=2, loadavg=lambda: (10.0, 10.0, 10.0))
        result = check_load_average(["--max-per-core", "1.0"], ctx)
        assert not result.ok


class TestDiskUsage:
    def test_reports_percent(self, tmp_path):
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(["--path", str(tmp_path), "--max-percent", "100"], ctx)
        assert result.ok

    def test_bad_path_fails(self):
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(["--path", "/definitely/not/a/real/path/xyz"], ctx)
        assert not result.ok

    def test_works_on_a_plain_directory_not_just_a_mount(self, tmp_path):
        # shutil.disk_usage reports the containing filesystem regardless of
        # whether `path` is itself a mount point -- this is what makes
        # check_disk_usage usable on "any directory that could interfere
        # with a job", not only dedicated mounts.
        sub = tmp_path / "some" / "nested" / "job_dir"
        sub.mkdir(parents=True)
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(["--path", str(sub), "--max-percent", "100"], ctx)
        assert result.ok
        assert str(sub) in result.detail

    def test_inode_percent_not_checked_when_flag_omitted(self, tmp_path):
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(["--path", str(tmp_path), "--max-percent", "100"], ctx)
        assert "inodes_used" not in result.detail

    @staticmethod
    def _fake_statvfs(f_ffree, f_files=1000):
        # shutil.disk_usage also calls os.statvfs() internally, so the fake
        # needs the block-based fields too (arbitrary but internally
        # consistent), not just the inode fields under test.
        class FakeStatvfs:
            pass

        s = FakeStatvfs()
        s.f_frsize = 4096
        s.f_blocks = 1000
        s.f_bfree = 500
        s.f_bavail = 500
        s.f_files = f_files
        s.f_ffree = f_ffree
        return s

    def test_inode_percent_failure(self, tmp_path, monkeypatch):
        import os as os_module

        monkeypatch.setattr(os_module, "statvfs", lambda path: self._fake_statvfs(f_ffree=50))
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(
            ["--path", str(tmp_path), "--max-percent", "100", "--max-inode-percent", "90"], ctx
        )
        assert not result.ok
        assert "inodes_used=95.0%" in result.detail

    def test_inode_percent_passes_under_threshold(self, tmp_path, monkeypatch):
        import os as os_module

        monkeypatch.setattr(os_module, "statvfs", lambda path: self._fake_statvfs(f_ffree=950))
        ctx = CheckContext(hostname="n1")
        result = check_disk_usage(
            ["--path", str(tmp_path), "--max-percent", "100", "--max-inode-percent", "90"], ctx
        )
        assert result.ok


class TestDirSize:
    def _make_files(self, base, sizes):
        base.mkdir(parents=True, exist_ok=True)
        for i, size in enumerate(sizes):
            (base / f"f{i}").write_bytes(b"x" * size)

    def test_under_max_gb_passes(self, tmp_path):
        self._make_files(tmp_path / "d", [1024, 2048])
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--path", str(tmp_path / "d"), "--max-gb", "1"], ctx)
        assert result.ok
        assert "files=2" in result.detail

    def test_over_max_gb_fails(self, tmp_path):
        self._make_files(tmp_path / "d", [5000, 5000])
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--path", str(tmp_path / "d"), "--max-gb", "0.000001"], ctx)
        assert not result.ok

    def test_max_files_threshold(self, tmp_path):
        self._make_files(tmp_path / "d", [10] * 5)
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--path", str(tmp_path / "d"), "--max-files", "3"], ctx)
        assert not result.ok
        assert "5 files > max 3" in result.detail

    def test_max_percent_of_filesystem(self, tmp_path):
        self._make_files(tmp_path / "d", [10])
        ctx = CheckContext(hostname="n1")
        # essentially any nonzero content is > 0% of a real filesystem's total
        result = check_dir_size(["--path", str(tmp_path / "d"), "--max-percent", "0"], ctx)
        assert not result.ok
        assert "% of filesystem" in result.detail

    def test_requires_path(self):
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--max-gb", "1"], ctx)
        assert not result.ok

    def test_requires_at_least_one_threshold(self, tmp_path):
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--path", str(tmp_path)], ctx)
        assert not result.ok
        assert "requires at least one" in result.detail

    def test_scan_cap_reports_inconclusive_not_failure(self, tmp_path):
        self._make_files(tmp_path / "d", [10] * 10)
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(
            ["--path", str(tmp_path / "d"), "--max-gb", "0.000001", "--max-scan", "3"], ctx
        )
        assert result.ok  # capped scan never reports a false failure
        assert "capped" in result.detail

    def test_bad_path_fails(self):
        ctx = CheckContext(hostname="n1")
        result = check_dir_size(["--path", "/definitely/not/a/real/path/xyz", "--max-gb", "1"], ctx)
        assert not result.ok


class TestSwapUsage:
    def test_no_swap_configured_passes(self, tmp_path):
        meminfo = _write_meminfo(tmp_path, 1_000_000, swap_total_kb=0, swap_free_kb=0)
        ctx = CheckContext(hostname="n1", proc_meminfo=meminfo)
        result = check_swap_usage([], ctx)
        assert result.ok
        assert "no swap" in result.detail

    def test_high_swap_usage_fails(self, tmp_path):
        meminfo = _write_meminfo(tmp_path, 1_000_000, swap_total_kb=1000, swap_free_kb=100)
        ctx = CheckContext(hostname="n1", proc_meminfo=meminfo)
        result = check_swap_usage(["--max-percent", "50"], ctx)
        assert not result.ok


class TestMountPresent:
    def _write_mounts(self, tmp_path, lines):
        p = tmp_path / "mounts"
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    def test_present_with_matching_fstype_passes(self, tmp_path):
        mounts = self._write_mounts(tmp_path, ["server:/export /scratch nfs4 rw 0 0"])
        ctx = CheckContext(hostname="n1", proc_mounts=mounts)
        result = check_mount_present(["--path", "/scratch", "--fstype", "nfs4"], ctx)
        assert result.ok

    def test_wrong_fstype_fails(self, tmp_path):
        mounts = self._write_mounts(tmp_path, ["server:/export /scratch nfs4 rw 0 0"])
        ctx = CheckContext(hostname="n1", proc_mounts=mounts)
        result = check_mount_present(["--path", "/scratch", "--fstype", "lustre"], ctx)
        assert not result.ok

    def test_missing_mount_fails(self, tmp_path):
        mounts = self._write_mounts(tmp_path, ["server:/export /home nfs4 rw 0 0"])
        ctx = CheckContext(hostname="n1", proc_mounts=mounts)
        result = check_mount_present(["--path", "/scratch"], ctx)
        assert not result.ok

    def test_requires_path_arg(self):
        ctx = CheckContext(hostname="n1")
        result = check_mount_present([], ctx)
        assert not result.ok


class TestZombieProcesses:
    def _make_proc(self, tmp_path, pid, comm, state):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} ({comm}) {state} 1 1 1\n")

    def test_counts_zombies(self, tmp_path):
        self._make_proc(tmp_path, 100, "bash", "S")
        self._make_proc(tmp_path, 101, "orphan", "Z")
        self._make_proc(tmp_path, 102, "orphan2", "Z")
        (tmp_path / "not_a_pid").mkdir()

        ctx = CheckContext(hostname="n1", proc_root=str(tmp_path))
        result = check_zombie_processes(["--max", "1"], ctx)
        assert not result.ok
        assert "zombie_processes=2" in result.detail

    def test_under_max_passes(self, tmp_path):
        self._make_proc(tmp_path, 100, "bash", "S")
        ctx = CheckContext(hostname="n1", proc_root=str(tmp_path))
        result = check_zombie_processes(["--max", "5"], ctx)
        assert result.ok


class TestGpuCount:
    def test_matches_baseline(self):
        def fake_run(argv, timeout=20, shell=False):
            return CommandOutput(argv, 0, "GPU 0: A100\nGPU 1: A100\n", "")
        ctx = CheckContext(hostname="n1", baseline={"gpu_count": 2}, run=fake_run)
        assert check_gpu_count([], ctx).ok

    def test_mismatch_fails(self):
        def fake_run(argv, timeout=20, shell=False):
            return CommandOutput(argv, 0, "GPU 0: A100\n", "")
        ctx = CheckContext(hostname="n1", baseline={"gpu_count": 2}, run=fake_run)
        assert not check_gpu_count([], ctx).ok

    def test_missing_nvidia_smi_but_zero_expected_passes(self):
        def fake_run(argv, timeout=20, shell=False):
            return CommandOutput(argv, 127, "", "not found")
        ctx = CheckContext(hostname="n1", baseline={"gpu_count": 0}, run=fake_run)
        assert check_gpu_count([], ctx).ok

    def test_missing_baseline_skips_ok(self):
        ctx = CheckContext(hostname="n1", baseline={})
        assert check_gpu_count([], ctx).ok


class TestNetworkInterface:
    def test_up_interface_passes(self, tmp_path):
        iface_dir = tmp_path / "eth0"
        iface_dir.mkdir()
        (iface_dir / "operstate").write_text("up\n")
        ctx = CheckContext(hostname="n1", sys_class_net=str(tmp_path))
        result = check_network_interface(["--iface", "eth0"], ctx)
        assert result.ok

    def test_down_interface_fails(self, tmp_path):
        iface_dir = tmp_path / "eth0"
        iface_dir.mkdir()
        (iface_dir / "operstate").write_text("down\n")
        ctx = CheckContext(hostname="n1", sys_class_net=str(tmp_path))
        result = check_network_interface(["--iface", "eth0"], ctx)
        assert not result.ok

    def test_allow_down_flag_skips_state_check(self, tmp_path):
        iface_dir = tmp_path / "eth0"
        iface_dir.mkdir()
        (iface_dir / "operstate").write_text("down\n")
        ctx = CheckContext(hostname="n1", sys_class_net=str(tmp_path))
        result = check_network_interface(["--iface", "eth0", "--allow-down"], ctx)
        assert result.ok

    def test_missing_interface_fails(self, tmp_path):
        ctx = CheckContext(hostname="n1", sys_class_net=str(tmp_path))
        result = check_network_interface(["--iface", "eth9"], ctx)
        assert not result.ok


class TestCommandCheck:
    def test_zero_exit_passes(self):
        def fake_run(argv, timeout=20, shell=False):
            return CommandOutput(argv, 0, "all good", "")
        ctx = CheckContext(hostname="n1", run=fake_run)
        result = check_command(["true"], ctx)
        assert result.ok

    def test_nonzero_exit_fails_with_detail(self):
        def fake_run(argv, timeout=20, shell=False):
            return CommandOutput(argv, 1, "", "boom")
        ctx = CheckContext(hostname="n1", run=fake_run)
        result = check_command(["/bin/false"], ctx)
        assert not result.ok
        assert "boom" in result.detail

    def test_no_command_fails(self):
        ctx = CheckContext(hostname="n1")
        result = check_command([], ctx)
        assert not result.ok
