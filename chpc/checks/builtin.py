"""Builtin check functions.

Each takes (args: List[str], ctx: CheckContext) -> CheckResult. Most read a
stable Linux /proc or /sys interface directly instead of shelling out, which
is both cheap (this whole daemon is meant to live on one pinned core) and
identical across RHEL/Rocky 8, 9, and 10 -- these interfaces predate all
three by a long way.

A check whose baseline value was never captured returns ok=True with a
detail note rather than failing: a missing baseline is an install/config
problem, not evidence the node is unhealthy, and it must never itself
trigger a drain. It does still show up in `chpc check`/`chpc status` output
so the gap gets noticed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List

from .base import CheckContext, CheckResult

Args = Dict[str, object]


def parse_kv(args: List[str], bool_flags: tuple = ()) -> Args:
    """Parses ["--max-percent", "90", "--require-up"] style args into a
    dict, honoring both "--key value" and "--key=value" forms."""
    out: Args = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--"):
            key = tok[2:]
            if "=" in key:
                key, val = key.split("=", 1)
                out[key] = val
                i += 1
                continue
            if key in bool_flags:
                out[key] = True
                i += 1
                continue
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                out[key] = args[i + 1]
                i += 2
            else:
                out[key] = True
                i += 1
        else:
            i += 1
    return out


def _skip(field: str) -> CheckResult:
    return CheckResult(True, f"baseline field '{field}' not captured; run `chpc baseline recapture`")


def _read_meminfo(path: str) -> Dict[str, int]:
    values: Dict[str, int] = {}
    try:
        for line in Path(path).read_text().splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0])
    except OSError:
        pass
    return values


def _read_mounts(path: str) -> List[Dict[str, str]]:
    mounts = []
    try:
        for line in Path(path).read_text().splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mounts.append({"device": parts[0], "path": parts[1], "fstype": parts[2]})
    except OSError:
        pass
    return mounts


def check_real_memory(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    tolerance = float(kv.get("tolerance-percent", 2))
    baseline_kb = ctx.baseline.get("real_memory_kb")
    if baseline_kb is None:
        return _skip("real_memory_kb")
    mem = _read_meminfo(ctx.proc_meminfo)
    mem_kb = mem.get("MemTotal")
    if mem_kb is None:
        return CheckResult(False, f"could not read MemTotal from {ctx.proc_meminfo}")
    diff_pct = abs(mem_kb - baseline_kb) / baseline_kb * 100 if baseline_kb else 0.0
    ok = diff_pct <= tolerance
    detail = f"MemTotal={mem_kb}kB baseline={baseline_kb}kB diff={diff_pct:.2f}% (tolerance {tolerance}%)"
    return CheckResult(ok, detail, measured=f"{mem_kb}kB", expected=f"{baseline_kb}kB ±{tolerance}%")


def check_cpu_count(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    tolerance = int(kv.get("tolerance", 0))
    baseline_count = ctx.baseline.get("cpu_count")
    if baseline_count is None:
        return _skip("cpu_count")
    count = ctx.cpu_count if ctx.cpu_count is not None else (os.cpu_count() or 0)
    ok = abs(count - baseline_count) <= tolerance
    detail = f"cpu_count={count} baseline={baseline_count} (tolerance {tolerance})"
    return CheckResult(ok, detail, measured=str(count), expected=str(baseline_count))


def check_load_average(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    max_per_core = float(kv.get("max-per-core", 1.5))
    load1 = (ctx.loadavg() if ctx.loadavg else os.getloadavg())[0]
    cpu_count = ctx.cpu_count if ctx.cpu_count is not None else (os.cpu_count() or 1)
    per_core = load1 / max(cpu_count, 1)
    ok = per_core <= max_per_core
    detail = f"load1={load1:.2f} cpu_count={cpu_count} per_core={per_core:.2f} (max {max_per_core})"
    return CheckResult(ok, detail, measured=f"{per_core:.2f}", expected=f"<= {max_per_core}")


def check_disk_usage(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    path = str(kv.get("path", "/"))
    max_percent = float(kv.get("max-percent", 90))
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return CheckResult(False, f"could not stat {path}: {exc}")
    percent = (usage.used / usage.total * 100) if usage.total else 0.0
    ok = percent <= max_percent
    detail = f"path={path} used={percent:.1f}% (max {max_percent}%) free={usage.free // (1024**2)}MB"
    return CheckResult(ok, detail, measured=f"{percent:.1f}%", expected=f"<= {max_percent}%")


def check_swap_usage(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    max_percent = float(kv.get("max-percent", 50))
    mem = _read_meminfo(ctx.proc_meminfo)
    total = mem.get("SwapTotal", 0)
    free = mem.get("SwapFree", 0)
    if total == 0:
        return CheckResult(True, "no swap configured")
    percent = (total - free) / total * 100
    ok = percent <= max_percent
    detail = f"swap used={percent:.1f}% (max {max_percent}%) total={total}kB"
    return CheckResult(ok, detail, measured=f"{percent:.1f}%", expected=f"<= {max_percent}%")


def check_mount_present(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    path = kv.get("path")
    fstype = kv.get("fstype")
    if not path:
        return CheckResult(False, "check_mount_present requires --path")
    for m in _read_mounts(ctx.proc_mounts):
        if m["path"] == path and (fstype is None or m["fstype"] == fstype):
            detail = f"{path} mounted ({m['fstype']})"
            return CheckResult(True, detail, measured=m["fstype"], expected=fstype or "present")
    detail = f"{path} not mounted" + (f" as {fstype}" if fstype else "")
    return CheckResult(False, detail, measured="absent", expected=f"mounted{(' as ' + fstype) if fstype else ''}")


def check_zombie_processes(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args)
    max_zombies = int(kv.get("max", 5))
    zombies = 0
    try:
        for entry in Path(ctx.proc_root).iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat_text = (entry / "stat").read_text()
            except OSError:
                continue
            close_paren = stat_text.rfind(")")
            if close_paren == -1:
                continue
            fields = stat_text[close_paren + 1:].split()
            if fields and fields[0] == "Z":
                zombies += 1
    except OSError as exc:
        return CheckResult(False, f"could not scan {ctx.proc_root}: {exc}")
    ok = zombies <= max_zombies
    detail = f"zombie_processes={zombies} (max {max_zombies})"
    return CheckResult(ok, detail, measured=str(zombies), expected=f"<= {max_zombies}")


def check_gpu_count(args: List[str], ctx: CheckContext) -> CheckResult:
    baseline_count = ctx.baseline.get("gpu_count")
    if baseline_count is None:
        return _skip("gpu_count")
    out = ctx.run(["nvidia-smi", "-L"], timeout=ctx.command_timeout)
    if not out.ok:
        if baseline_count == 0:
            return CheckResult(True, "nvidia-smi unavailable, and baseline expects 0 GPUs")
        return CheckResult(False, f"nvidia-smi failed (rc={out.returncode}): {out.stderr.strip()[:200]}")
    count = len([line for line in out.stdout.splitlines() if line.strip()])
    ok = count == baseline_count
    detail = f"gpu_count={count} baseline={baseline_count}"
    return CheckResult(ok, detail, measured=str(count), expected=str(baseline_count))


def check_network_interface(args: List[str], ctx: CheckContext) -> CheckResult:
    kv = parse_kv(args, bool_flags=("allow-down",))
    iface = kv.get("iface")
    if not iface:
        return CheckResult(False, "check_network_interface requires --iface")
    iface_dir = Path(ctx.sys_class_net) / str(iface)
    if not iface_dir.exists():
        return CheckResult(False, f"interface {iface} not present", measured="absent", expected="present")
    if kv.get("allow-down"):
        return CheckResult(True, f"interface {iface} present")
    try:
        state = (iface_dir / "operstate").read_text().strip()
    except OSError:
        state = "unknown"
    ok = state == "up"
    detail = f"interface {iface} operstate={state}"
    return CheckResult(ok, detail, measured=state, expected="up")


def check_command(args: List[str], ctx: CheckContext) -> CheckResult:
    """The generic escape hatch: run any shell command; exit 0 is a pass.
    `args` is a single-element list holding the raw command line (see
    checks/parser.py -- the `command || ...` form is never re-split, so the
    command itself may freely contain && / || / pipes)."""
    if not args:
        return CheckResult(False, "command check has no command to run")
    command_line = args[0]
    out = ctx.run([command_line], timeout=ctx.command_timeout, shell=True)
    ok = out.ok
    combined = (out.stdout.strip() + " " + out.stderr.strip()).strip()
    detail = f"`{command_line}` exit={out.returncode}" + (f": {combined[:200]}" if combined else "")
    return CheckResult(ok, detail, measured=str(out.returncode), expected="0")


BUILTIN_CHECKS = {
    "check_real_memory": check_real_memory,
    "check_cpu_count": check_cpu_count,
    "check_load_average": check_load_average,
    "check_disk_usage": check_disk_usage,
    "check_swap_usage": check_swap_usage,
    "check_mount_present": check_mount_present,
    "check_zombie_processes": check_zombie_processes,
    "check_gpu_count": check_gpu_count,
    "check_network_interface": check_network_interface,
    "command": check_command,
}
