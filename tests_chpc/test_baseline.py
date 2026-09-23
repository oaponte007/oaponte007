from chpc import baseline


def test_capture_reads_meminfo_mounts_and_interfaces(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       1000000 kB\nMemFree:        500 kB\n")

    mounts = tmp_path / "mounts"
    mounts.write_text(
        "proc /proc proc rw 0 0\n"
        "tmpfs /run tmpfs rw 0 0\n"
        "server:/export /scratch nfs4 rw 0 0\n"
    )

    net = tmp_path / "net"
    net.mkdir()
    (net / "lo").mkdir()
    (net / "eth0").mkdir()
    (net / "ib0").mkdir()

    data = baseline.capture(
        proc_meminfo=str(meminfo),
        proc_mounts=str(mounts),
        sys_class_net=str(net),
        cpu_count=16,
        gpu_probe=lambda: ["GPU 0: A100", "GPU 1: A100"],
    )

    assert data["cpu_count"] == 16
    assert data["real_memory_kb"] == 1000000
    assert data["gpu_count"] == 2
    assert data["mounts"] == [{"path": "/scratch", "fstype": "nfs4"}]
    assert data["interfaces"] == ["eth0", "ib0"]  # lo excluded


def test_capture_handles_no_gpus():
    data = baseline.capture(
        proc_meminfo="/nonexistent",
        proc_mounts="/nonexistent",
        sys_class_net="/nonexistent",
        cpu_count=4,
        gpu_probe=lambda: [],
    )
    assert data["gpu_count"] == 0
    assert data["real_memory_kb"] is None
    assert data["mounts"] == []
    assert data["interfaces"] == []


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "baseline.yaml"
    data = {"cpu_count": 8, "real_memory_kb": 500000, "gpu_count": 0, "gpus": [],
            "mounts": [], "interfaces": ["eth0"]}
    baseline.save(path, data)

    loaded = baseline.load(path)
    assert loaded == data


def test_load_missing_file_returns_empty_dict(tmp_path):
    assert baseline.load(tmp_path / "does_not_exist.yaml") == {}
