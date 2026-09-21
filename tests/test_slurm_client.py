from slurm_monitor.slurm_client import parse_node_line


SAMPLE_LINE = (
    'NodeName=node047 Arch=x86_64 CoresPerSocket=32 '
    'CPUAlloc=0 CPUTot=128 CPULoad=0.02 AvailableFeatures=(null) '
    'ActiveFeatures=(null) Gres=(null) NodeAddr=node047 NodeHostName=node047 '
    'Version=23.02 OS=Linux RealMemory=512000 AllocMem=0 FreeMem=510842 '
    'Sockets=2 Boards=1 State=DRAINED ThreadsPerCore=2 TmpDisk=0 Weight=1 '
    'Owner=N/A MCS_label=N/A Partitions=compute BootTime=2026-01-01T00:00:00 '
    'SlurmdStartTime=2026-01-01T00:05:00 CfgTRES=cpu=128,mem=512000M '
    'AllocTRES= CapWatts=n/a CurrentWatts=0 AveWatts=0 '
    'ExtSensorsJoules=n/s ExtSensorsWatts=0 ExtSensorsTemp=n/s '
    'Reason=Low RealMemory [root@2026-01-01T09:00:00]'
)


def test_parse_node_line_basic_fields():
    ns = parse_node_line(SAMPLE_LINE)
    assert ns.name == "node047"
    assert ns.state == "DRAINED"
    assert ns.reason == "Low RealMemory"
    assert ns.reason_set_by == "root"
    assert ns.reason_set_at is not None
    assert ns.reason_set_at.isoformat() == "2026-01-01T09:00:00"
    assert ns.cfg_tres == "cpu=128,mem=512000M"
    assert ns.is_problem is True


def test_parse_node_line_idle_no_reason():
    line = "NodeName=node001 State=IDLE Reason= CfgTRES=cpu=64 AllocTRES="
    ns = parse_node_line(line)
    assert ns.state == "IDLE"
    assert ns.reason == ""
    assert ns.is_problem is False


def test_parse_node_line_down_star_is_a_problem():
    line = "NodeName=node002 State=DOWN* Reason=Not responding [slurmctld@2026-01-01T08:00:00]"
    ns = parse_node_line(line)
    assert ns.is_problem is True
    assert ns.reason == "Not responding"
