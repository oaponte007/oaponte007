"""Command-line entrypoint: `chpc install|check|run|status|explain|resume|baseline`."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import baseline as baseline_mod
from . import recovery
from .backends.base import CommandRunner
from .backends.detect import detect_resource_manager
from .backends.pbs import PBSBackend
from .backends.slurm import SlurmBackend
from .config import Config
from .daemon import Daemon
from .state import State

DEFAULT_CHECKS_TEMPLATE = """\
# chpc checks file. One check per line:
#   <hostmask> || <builtin_check_name> [--flag value ...]
#   <hostmask> || command || <any shell command line>
# hostmask supports globs against this host's hostname; "*" matches all.
# Lines starting with # are comments. See CHPC_MANUAL.md for the full
# reference of builtin checks and their flags.

*  || check_real_memory --tolerance-percent 2
*  || check_cpu_count --tolerance 0
*  || check_load_average --max-per-core 1.5
*  || check_disk_usage --path / --max-percent 90 --max-inode-percent 90
*  || check_dir_size --path /tmp --max-gb 50
*  || check_zombie_processes --max 5
{extra}
"""


def _build_backend(config: Config, runner: CommandRunner):
    rm = detect_resource_manager(config.resource_manager)
    if rm == "slurm":
        return SlurmBackend(runner, binary=config.slurm_binary)
    if rm == "pbs":
        return PBSBackend(runner, binary=config.pbs_binary, offline_flag=config.pbs_offline_flag,
                            note_flag=config.pbs_note_flag, clear_flag=config.pbs_clear_flag)
    return None


def _build_daemon(config: Config) -> Daemon:
    runner = CommandRunner(dry_run=config.dry_run, timeout=config.command_timeout)
    backend = _build_backend(config, runner)
    state = State(config.state_db)
    return Daemon(config, backend, state)


def cmd_install(args: argparse.Namespace) -> int:
    config = Config.load(args.config) if args.config else Config()
    if args.core is not None:
        config.cpu_affinity = [args.core]
    config.ensure_dirs()

    if config.baseline_file.exists() and not args.force:
        print(f"baseline already exists at {config.baseline_file} (use --force to recapture)")
    else:
        data = baseline_mod.capture()
        baseline_mod.save(config.baseline_file, data)
        print(f"captured baseline -> {config.baseline_file}")
        print(f"  cpu_count={data['cpu_count']} real_memory_kb={data['real_memory_kb']} "
              f"gpu_count={data['gpu_count']} mounts={len(data['mounts'])} "
              f"interfaces={len(data['interfaces'])}")

    if config.checks_file.exists() and not args.force:
        print(f"checks file already exists at {config.checks_file} (use --force to overwrite)")
    else:
        extra_lines = []
        if data := baseline_mod.load(config.baseline_file):
            if data.get("gpu_count"):
                extra_lines.append("*  || check_gpu_count")
            for m in data.get("mounts", []):
                if m["fstype"] in ("nfs", "nfs4", "lustre", "gpfs", "cifs"):
                    extra_lines.append(f"*  || check_mount_present --path {m['path']} --fstype {m['fstype']}")
                    extra_lines.append(f"*  || check_disk_usage --path {m['path']} --max-percent 90")
        config.checks_file.write_text(
            DEFAULT_CHECKS_TEMPLATE.format(extra="\n".join(extra_lines))
        )
        print(f"wrote starter checks file -> {config.checks_file}")

    if not args.config:
        example_config = Path(args.write_config) if args.write_config else config.checks_file.parent / "chpc.yaml"
        print(f"\nNo --config given. Review defaults below and save your own to {example_config}, "
              f"or copy config/chpc.example.yaml from the repo.")

    rm = detect_resource_manager(config.resource_manager)
    print(f"\nDetected resource manager: {rm}")
    print(f"CPU pin: core(s) {config.cpu_affinity}")
    print("\nNext steps:")
    print(f"  1. Review/edit {config.checks_file}")
    print("  2. Install the systemd unit: cp systemd/chpc.service /etc/systemd/system/")
    print("  3. sudo systemctl daemon-reload && sudo systemctl enable --now chpc")
    print("  4. Dry-run first: `chpc check` shows current results with no side effects.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Pure preview: evaluates every check, touches no state, drains nothing."""
    config = Config.load(args.config)
    baseline_data = baseline_mod.load(config.baseline_file)
    hostname = socket.gethostname()

    from .checks.base import CheckContext
    from .checks.builtin import BUILTIN_CHECKS
    from .checks.parser import parse_file
    import fnmatch

    ctx = CheckContext(hostname=hostname, baseline=baseline_data,
                        command_timeout=config.command_timeout)
    try:
        specs = parse_file(config.checks_file)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    all_ok = True
    for spec in specs:
        if not fnmatch.fnmatch(hostname.lower(), spec.hostmask.lower()):
            continue
        checker = BUILTIN_CHECKS.get(spec.name)
        if checker is None:
            print(f"UNKNOWN  {spec.name:<24}{spec.raw}")
            all_ok = False
            continue
        result = checker(spec.args, ctx)
        status = "OK  " if result.ok else "FAIL"
        print(f"{status}     {spec.name:<24}{result.detail}")
        all_ok = all_ok and result.ok
    return 0 if all_ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    if args.dry_run is not None:
        config.dry_run = args.dry_run
    logging.basicConfig(level=config.log_level,
                         format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    daemon = _build_daemon(config)
    if args.once:
        for a in daemon.run_once():
            print(f"{a.check_name}\t{a.action}\t{a.detail}")
        return 0
    daemon.run_forever()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    state = State(config.state_db)
    rows = state.all_check_states()
    if not rows:
        print("No check history yet -- run `chpc check` or `chpc run --once` first.")
        return 0
    print(f"{'CHECK':<26}{'LAST':<6}{'STREAK':<8}{'DRAINED':<9}LAST DETAIL")
    for r in rows:
        active = "yes" if state.is_active(r.check_key) else "no"
        print(f"{r.check_name:<26}{'ok' if r.last_ok else 'FAIL':<6}{r.consecutive_fails:<8}"
              f"{active:<9}{r.last_detail}")

    active_drains = state.active_drains()
    if active_drains:
        print("\nActive drains (chpc believes these are still in effect):")
        for d in active_drains:
            print(f"  {d.check_name} since {d.drained_at.isoformat()}Z: {d.reason}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    state = State(config.state_db)

    if args.check_name:
        names = [args.check_name]
    else:
        names = [d.check_name for d in state.active_drains()] or [
            r.check_name for r in state.all_check_states() if not r.last_ok
        ]
        if not names:
            print("Nothing currently failing or drained.")
            return 0

    for name in names:
        row = None
        for r in state.all_check_states():
            if r.check_name == name:
                row = r
                break
        detail = row.last_detail if row else "(no recorded check result yet)"
        print(recovery.build_instructions(name, detail))
        print()
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    runner = CommandRunner(dry_run=config.dry_run, timeout=config.command_timeout)
    backend = _build_backend(config, runner)
    state = State(config.state_db)
    node = args.node or socket.gethostname()

    if backend is None:
        print("no resource manager backend configured/detected; clearing local state only")
    else:
        ok = backend.resume(node)
        print(f"backend.resume({node}) -> {'ok' if ok else 'FAILED'}")

    if args.all or not args.check_name:
        state.clear_all_drained()
        print("cleared all chpc drain bookkeeping")
    else:
        matched = False
        for r in state.all_check_states():
            if r.check_name == args.check_name:
                state.clear_drained(r.check_key)
                matched = True
        print(f"cleared bookkeeping for check={args.check_name}" if matched
              else f"no recorded state for check={args.check_name}")
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    if args.baseline_cmd == "show":
        data = baseline_mod.load(config.baseline_file)
        if not data:
            print(f"no baseline captured yet at {config.baseline_file}")
            return 1
        for k, v in data.items():
            print(f"{k}: {v}")
        return 0
    if args.baseline_cmd == "recapture":
        data = baseline_mod.capture()
        baseline_mod.save(config.baseline_file, data)
        print(f"recaptured baseline -> {config.baseline_file}")
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chpc", description=__doc__)
    parser.add_argument("--config", default=None, help="path to chpc.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="capture baseline, write starter checks file")
    p_install.add_argument("--core", type=int, default=None, help="CPU core to pin to (default: 0)")
    p_install.add_argument("--force", action="store_true", help="overwrite existing baseline/checks file")
    p_install.add_argument("--write-config", default=None)
    p_install.set_defaults(func=cmd_install)

    p_check = sub.add_parser("check", help="evaluate checks once, no side effects, no draining")
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="the daemon loop (what systemd runs)")
    p_run.add_argument("--once", action="store_true", help="one real cycle (with drain/state logic) and exit")
    p_run.add_argument("--dry-run", dest="dry_run", action="store_true", default=None)
    p_run.add_argument("--live", dest="dry_run", action="store_false")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="show check streaks and active drains")
    p_status.set_defaults(func=cmd_status)

    p_explain = sub.add_parser("explain", help="print recovery instructions for a check")
    p_explain.add_argument("check_name", nargs="?", default=None)
    p_explain.set_defaults(func=cmd_explain)

    p_resume = sub.add_parser("resume", help="resume the node via the RM backend and clear chpc state")
    p_resume.add_argument("check_name", nargs="?", default=None)
    p_resume.add_argument("--node", default=None)
    p_resume.add_argument("--all", action="store_true")
    p_resume.set_defaults(func=cmd_resume)

    p_baseline = sub.add_parser("baseline", help="show or recapture the install-time baseline")
    p_baseline.add_argument("baseline_cmd", choices=["show", "recapture"])
    p_baseline.set_defaults(func=cmd_baseline)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
