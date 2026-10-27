"""Command-line interface for the SLA tracker.

Usage:
    python -m sla_tracker --tickets data/tickets.json --policy data/sla_policy.json \
        --holidays data/holidays.json [--now 2025-11-07T18:00:00] \
        [--out results.json] [--csv results.csv] [--report summary.md]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report
from .engine import compute_all
from .models import InputError, load_dataset
from .summary import summarize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sla_tracker",
        description="Compute SLA breaches for support tickets in business hours.")
    p.add_argument("--tickets", required=True, type=Path, help="path to tickets JSON")
    p.add_argument("--policy", required=True, type=Path, help="path to SLA policy JSON")
    p.add_argument("--holidays", required=True, type=Path, help="path to holidays JSON")
    p.add_argument("--now", type=str, default=None,
                   help="evaluation cutoff, ISO-8601 (default: resolved_at or, if none, current time)")
    p.add_argument("--out", type=Path, default=None, help="write full results as JSON")
    p.add_argument("--csv", type=Path, default=None, help="write per-ticket CSV")
    p.add_argument("--report", type=Path, default=None, help="write Markdown summary")
    p.add_argument("--stdout", action="store_true", help="print full results JSON to stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.tickets, args.policy, args.holidays)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.now is not None:
        try:
            from .models import parse_timestamp
            now = parse_timestamp(args.now, "--now")
        except InputError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        # Unresolved tickets with no --now: use the latest timestamp present in
        # the data as the cutoff so runs are deterministic and reproducible.
        candidates = [t.resolved_at for t in dataset.tickets if t.resolved_at]
        latest_event = max((e.at for t in dataset.tickets for e in t.status_history),
                           default=None)
        if latest_event is not None:
            candidates.append(latest_event)
        now = max(candidates) if candidates else datetime.now()

    results = compute_all(dataset, now)
    summary = summarize(results)

    wrote = False
    if args.out is not None:
        report.write_json(results, summary, args.out)
        wrote = True
    if args.csv is not None:
        report.write_csv(results, args.csv)
        wrote = True
    if args.report is not None:
        args.report.write_text(report.summary_markdown(summary), encoding="utf-8")
        wrote = True
    if args.stdout or not wrote:
        import json
        print(json.dumps(report.results_to_dict(results, summary), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
