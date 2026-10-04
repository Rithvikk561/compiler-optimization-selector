"""
moo/regression/__main__.py — CLI entry point for the Week 10 regression system.

Usage
-----
python -m moo.regression [command] [options]

Commands
--------
  info      Show regression schema version and supported metrics.
  compare   Analyze regressions in a benchmark run (baseline vs selected / strategies).
  history   Compare two historical benchmark runs and detect regressions.

Examples
--------
  python -m moo.regression info
  python -m moo.regression compare Codes/Benchmarks/runs/latest --out regression_report.json
  python -m moo.regression history Codes/Benchmarks/runs/run1 Codes/Benchmarks/runs/run2
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .comparator import KNOWN_METRIC_SPECS
from .report import build_regression_report, save_regression_report
from .schema import REGRESSION_SCHEMA_VERSION


def _load_run_records(run_dir: str) -> list[dict]:
    """Load all ProgramRecord JSON files from a run's results/ directory."""
    results_dir = os.path.join(run_dir, "results")
    if not os.path.isdir(results_dir):
        # Maybe run_dir itself contains records or is invalid
        results_dir = run_dir

    records = []
    if os.path.isdir(results_dir):
        for fn in sorted(os.listdir(results_dir)):
            if fn.endswith(".json") and fn != "run_manifest.json":
                p = os.path.join(results_dir, fn)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        records.append(json.load(fh))
                except Exception:
                    pass
    return records


def _load_run_id(run_dir: str) -> str:
    """Read run_id from run_manifest.json if present."""
    m_path = os.path.join(run_dir, "run_manifest.json")
    if os.path.isfile(m_path):
        try:
            with open(m_path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
                return str(d.get("run_id", os.path.basename(run_dir)))
        except Exception:
            pass
    return os.path.basename(run_dir)


def cmd_info(args: argparse.Namespace) -> int:
    """Print regression package metadata."""
    print("TOACD Week 10 — Optimization Regression & Comparison")
    print(f"  Schema version : {REGRESSION_SCHEMA_VERSION}")
    print("  Tracked Metrics and Semantics:")
    for mname, (lower_is_better, unit) in sorted(KNOWN_METRIC_SPECS.items()):
        direction = "lower is better (minimization)" if lower_is_better else "higher is better (maximization)"
        print(f"    - {mname:<18} [{unit:<12}]: {direction}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Compare baseline vs selected optimizations in a single benchmark run."""
    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        print(f"Error: directory not found: {run_dir}")
        return 1

    records = _load_run_records(run_dir)
    run_id = _load_run_id(run_dir)
    print(f"Loaded {len(records)} records from {run_dir} (run_id: {run_id})")

    report = build_regression_report(
        records=records,
        current_run_id=run_id,
        suite_name=f"compare_{run_id}",
    )
    print(report.to_text_summary())

    if args.out:
        save_regression_report(report, args.out)
        print(f"Report saved to: {args.out}")

    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Compare two historical benchmark runs."""
    prev_dir = args.prev_dir
    curr_dir = args.curr_dir
    if not os.path.isdir(prev_dir) or not os.path.isdir(curr_dir):
        print(f"Error: one or both directories not found: {prev_dir}, {curr_dir}")
        return 1

    prev_records = _load_run_records(prev_dir)
    curr_records = _load_run_records(curr_dir)
    prev_run_id = _load_run_id(prev_dir)
    curr_run_id = _load_run_id(curr_dir)

    print(f"Comparing previous run ({prev_run_id}, {len(prev_records)} programs) vs "
          f"current run ({curr_run_id}, {len(curr_records)} programs)")

    report = build_regression_report(
        records=curr_records,
        previous_records=prev_records,
        previous_run_id=prev_run_id,
        current_run_id=curr_run_id,
        suite_name=f"history_{prev_run_id}_vs_{curr_run_id}",
    )
    print(report.to_text_summary())

    if report.historical_comparison:
        hc = report.historical_comparison
        print("\nHistorical Run-to-Run Delta Summary:")
        for k, v in sorted(hc.summary.items()):
            print(f"  {k:<20}: {v}")

    if args.out:
        save_regression_report(report, args.out)
        print(f"Report saved to: {args.out}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m moo.regression",
        description="TOACD Week 10 Optimization Regression & Comparison",
    )
    sub = parser.add_subparsers(dest="command")

    # info
    sub.add_parser("info", help="Show regression schema and supported metrics")

    # compare
    p_comp = sub.add_parser("compare", help="Compare baseline vs selected optimizations")
    p_comp.add_argument("run_dir", help="Run directory containing benchmark results")
    p_comp.add_argument("--out", "-o", help="Save regression report to JSON")

    # history
    p_hist = sub.add_parser("history", help="Compare two historical benchmark runs")
    p_hist.add_argument("prev_dir", help="Historical reference run directory")
    p_hist.add_argument("curr_dir", help="Current run directory to compare")
    p_hist.add_argument("--out", "-o", help="Save regression report to JSON")

    args = parser.parse_args()
    commands = {
        "info": cmd_info,
        "compare": cmd_compare,
        "history": cmd_history,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(0)

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
