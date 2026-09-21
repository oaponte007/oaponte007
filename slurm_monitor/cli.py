"""Command-line entrypoint: `slurm-monitor watch|diagnose|status|log|report|resolve`."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

from .agent import Agent
from .classifier import classify
from .config import Config
from .diagnostics import diagnose as run_diagnose
from .history import History
from .notify import Notifier
from .slurm_client import SlurmClient


def _build_agent(config: Config) -> Agent:
    client = SlurmClient(dry_run=config.dry_run)
    history = History(config.db_path, window=timedelta(hours=config.recurrence_window_hours))
    notifier = Notifier(config.webhook_url)
    return Agent(
        client=client,
        history=history,
        notifier=notifier,
        remote_exec=config.remote_exec,
        poll_interval=config.poll_interval,
        recurrence_threshold=config.recurrence_threshold,
    )


def cmd_watch(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    if args.dry_run is not None:
        config.dry_run = args.dry_run
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = _build_agent(config)
    if args.once:
        decisions = agent.poll_once()
        for d in decisions:
            print(f"{d.node}\t{d.category.value}\t{d.action}\t{d.note.splitlines()[0] if d.note else ''}")
        return 0
    agent.run_forever()
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    client = SlurmClient(dry_run=True)  # diagnose is always read-only
    node_state = client.get_node_state(args.node)
    if node_state is None:
        print(f"error: could not read state for node {args.node!r} (is it a valid node name?)", file=sys.stderr)
        return 1

    category = classify(node_state.reason)
    report = run_diagnose(node_state, category, client, remote_exec=config.remote_exec)

    history = History(config.db_path)
    prior = history.prior_occurrences(args.node, category.value, datetime.utcnow())

    print(f"Node:        {node_state.name}")
    print(f"State:       {node_state.state}")
    print(f"Reason:      {node_state.reason or '(none)'}")
    print()
    print(report.probable_cause)
    print()
    print("Recommended Action")
    print("-" * 34)
    for i, action in enumerate(report.recommended_actions, 1):
        print(f"{i}. {action}")
    print()
    print(f"Confidence: {report.confidence}")
    print(f"Occurrences of this problem on this node in the last 24h: {len(prior) + 1}")
    if history.is_quarantined(args.node, category.value):
        print("Status: QUARANTINED -- agent has already force-drained this node for this "
              "issue; resume manually once resolved to clear.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    client = SlurmClient(dry_run=True)
    history = History(config.db_path)
    now = datetime.utcnow()
    states = [s for s in client.get_node_states() if s.is_problem]
    if not states:
        print("No nodes currently in a DRAIN/DOWN-like state.")
        return 0
    print(f"{'NODE':<15}{'STATE':<12}{'CATEGORY':<22}{'OCCURRENCES(24h)':<18}{'QUARANTINED':<12}REASON")
    for s in states:
        category = classify(s.reason)
        count = len(history.prior_occurrences(s.name, category.value, now)) + 1
        quarantined = "yes" if history.is_quarantined(s.name, category.value) else "no"
        print(f"{s.name:<15}{s.state:<12}{category.value:<22}{count:<18}{quarantined:<12}{s.reason}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    history = History(config.db_path)
    history.clear_quarantine(args.node, args.category)
    print(f"cleared quarantine for node={args.node} category={args.category or 'ALL'}")
    return 0


_SINCE_RE = re.compile(r"^(\d+)\s*([smhdw])$", re.I)
_SINCE_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_since(value: str) -> datetime:
    """Accepts a relative duration ("24h", "7d", "30m") measured back from
    now, or an ISO 8601 timestamp/date, for --since on `log`/`report`."""
    m = _SINCE_RE.match(value.strip())
    if m:
        amount, unit = m.groups()
        return datetime.utcnow() - timedelta(**{_SINCE_UNITS[unit.lower()]: int(amount)})
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid --since {value!r}; use a duration like '24h'/'7d' or an ISO timestamp"
        )


def cmd_log(args: argparse.Namespace) -> int:
    """Show the persistent audit trail: every decision the agent has made,
    for periodic admin review (nothing here mutates the cluster)."""
    config = Config.load(args.config)
    history = History(config.db_path)
    entries = history.query_actions(
        node=args.node, category=args.category, action=args.action,
        since=parse_since(args.since) if args.since else None, limit=args.limit,
    )

    if not entries:
        print("No matching actions in the audit log.")
        return 0

    if args.format == "json":
        print(json.dumps([
            {
                "ts": e.ts.isoformat(), "node": e.node, "category": e.category, "action": e.action,
                "reason": e.reason, "note": e.note, "success": e.success,
                "occurrences_in_window": e.occurrences_in_window,
            }
            for e in entries
        ], indent=2))
        return 0

    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["ts", "node", "category", "action", "success", "occurrences_in_window", "reason"])
        for e in entries:
            writer.writerow([e.ts.isoformat(), e.node, e.category, e.action,
                              "" if e.success is None else e.success, e.occurrences_in_window, e.reason])
        return 0

    print(f"{'TIMESTAMP (UTC)':<20}{'NODE':<12}{'CATEGORY':<20}{'ACTION':<15}{'OK':<6}{'#24h':<6}REASON")
    for e in entries:
        ok = "-" if e.success is None else ("yes" if e.success else "NO")
        print(f"{e.ts.isoformat(timespec='seconds'):<20}{e.node:<12}{e.category:<20}{e.action:<15}"
              f"{ok:<6}{e.occurrences_in_window:<6}{e.reason}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Summarize the audit trail over a period -- the periodic digest an
    admin would skim to spot which nodes/categories need real attention,
    rather than reading every log line."""
    config = Config.load(args.config)
    history = History(config.db_path)
    since = parse_since(args.since)
    entries = history.query_actions(since=since, limit=args.limit)

    print(f"slurm-monitor action report: since {since.isoformat(timespec='seconds')}Z "
          f"({len(entries)} action(s))")
    if not entries:
        return 0

    by_action = Counter(e.action for e in entries)
    print("\nBy action:")
    for action, count in by_action.most_common():
        print(f"  {action:<15}{count}")

    force_drains = [e for e in entries if e.action == "force_drain"]
    if force_drains:
        print(f"\nForce-drained ({len(force_drains)}) -- needs investigation:")
        for e in force_drains:
            print(f"  {e.ts.isoformat(timespec='seconds')}  {e.node:<12}{e.category}")

    manual = [e for e in entries if e.action == "manual_review"]
    if manual:
        by_node_category = Counter((e.node, e.category) for e in manual)
        print(f"\nFlagged for manual review ({len(manual)}), by node/category:")
        for (node, category), count in by_node_category.most_common(10):
            print(f"  {node:<12}{category:<22}x{count}")

    failed = [e for e in entries if e.success is False]
    if failed:
        print(f"\nWARNING: {len(failed)} action(s) the agent attempted did not succeed "
              "(scontrol/systemctl command failed) -- check `slurm-monitor log --action "
              "force_drain` / `resume` and cluster connectivity.")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slurm-monitor", description=__doc__)
    parser.add_argument("--config", help="path to slurm_monitor.yaml", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_watch = sub.add_parser("watch", help="run the monitoring/remediation loop")
    p_watch.add_argument("--once", action="store_true", help="run a single poll cycle and exit")
    p_watch.add_argument("--dry-run", dest="dry_run", action="store_true", default=None)
    p_watch.add_argument("--live", dest="dry_run", action="store_false")
    p_watch.set_defaults(func=cmd_watch)

    p_diag = sub.add_parser("diagnose", help="run read-only diagnostics on one node")
    p_diag.add_argument("node")
    p_diag.set_defaults(func=cmd_diagnose)

    p_status = sub.add_parser("status", help="list problem nodes with classification + recurrence count")
    p_status.set_defaults(func=cmd_status)

    p_resolve = sub.add_parser("resolve", help="manually clear a quarantine entry")
    p_resolve.add_argument("node")
    p_resolve.add_argument("--category", default=None, help="limit to one category; default: all")
    p_resolve.set_defaults(func=cmd_resolve)

    p_log = sub.add_parser("log", help="show the persistent audit trail of every decision the agent made")
    p_log.add_argument("--node", default=None)
    p_log.add_argument("--category", default=None)
    p_log.add_argument("--action", default=None,
                        choices=["ignore", "resume", "force_drain", "manual_review"])
    p_log.add_argument("--since", default=None, help="e.g. '24h', '7d', or an ISO timestamp")
    p_log.add_argument("--limit", type=int, default=200)
    p_log.add_argument("--format", choices=["table", "json", "csv"], default="table")
    p_log.set_defaults(func=cmd_log)

    p_report = sub.add_parser("report", help="periodic summary digest of the audit trail, for admin review")
    p_report.add_argument("--since", default="24h", help="e.g. '24h', '7d' (default: 24h)")
    p_report.add_argument("--limit", type=int, default=5000)
    p_report.set_defaults(func=cmd_report)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
