"""Command-line entrypoint: `slurm-monitor watch|diagnose|status`."""

from __future__ import annotations

import argparse
import logging
import sys
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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
