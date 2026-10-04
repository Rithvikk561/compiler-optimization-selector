"""
moo/regression/report.py — Structured regression report builder and persistence.

Assembles ProgramComparisons and optional HistoricalComparisons into a complete,
versioned RegressionReport, and handles JSON persistence.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import subprocess
from typing import Any, Mapping, Optional, Sequence

from .comparator import compare_program
from .detector import DEFAULT_THRESHOLDS, RegressionThresholds
from .historical import compare_historical_runs
from .schema import (
    REGRESSION_SCHEMA_VERSION,
    HistoricalComparison,
    OverallStatus,
    ProgramComparison,
    RegressionReport,
)


def _get_git_commit() -> Optional[str]:
    """Capture current short git commit hash if available."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


def _make_report_id(suite_name: str) -> str:
    """Generate unique deterministic-prefixed report ID."""
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    h = hashlib.sha256(f"{ts}:{suite_name}".encode()).hexdigest()[:8]
    return f"reg_{ts}_{h}"


def build_regression_report(
    records: Sequence[Any],
    previous_records: Optional[Sequence[Any]] = None,
    previous_run_id: Optional[str] = None,
    current_run_id: Optional[str] = None,
    suite_name: str = "optimization_regression",
    thresholds: Optional[RegressionThresholds] = None,
    selected_strategies: Optional[Mapping[str, str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> RegressionReport:
    """
    Build a comprehensive, versioned RegressionReport from benchmark run records.

    Parameters
    ----------
    records             : current benchmark run ProgramRecords or dicts
    previous_records    : optional historical benchmark run records for cross-run regression
    previous_run_id     : identifier of the previous run (optional)
    current_run_id      : identifier of the current run (optional)
    suite_name          : descriptive suite label
    thresholds          : RegressionThresholds instance (defaults to DEFAULT_THRESHOLDS)
    selected_strategies : optional mapping {program_id: selected_strategy_name}
    metadata            : optional extra metadata dict
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS
    sel_map = dict(selected_strategies) if selected_strategies else {}

    # 1. Compare each program in the current run
    program_comparisons: dict[str, ProgramComparison] = {}
    n_improved = 0
    n_regressed = 0
    n_mixed = 0
    n_unchanged = 0
    n_incomparable = 0

    for r in records:
        pid = r.get("program_id") if isinstance(r, dict) else getattr(r, "program_id", None)
        if not pid:
            continue
        pid_str = str(pid)
        chosen_strategy = sel_map.get(pid_str)

        pcomp = compare_program(
            record_or_dict=r,
            selected_strategy=chosen_strategy,
            thresholds=thresh,
        )
        program_comparisons[pid_str] = pcomp

        if pcomp.overall_status == OverallStatus.IMPROVED:
            n_improved += 1
        elif pcomp.overall_status == OverallStatus.REGRESSED:
            n_regressed += 1
        elif pcomp.overall_status == OverallStatus.MIXED:
            n_mixed += 1
        elif pcomp.overall_status == OverallStatus.UNCHANGED:
            n_unchanged += 1
        else:
            n_incomparable += 1

    # 2. Historical cross-run comparison if historical data provided
    hist_comp: Optional[HistoricalComparison] = None
    if previous_records is not None:
        hist_comp = compare_historical_runs(
            previous_records=previous_records,
            current_records=records,
            previous_run_id=previous_run_id,
            current_run_id=current_run_id,
            thresholds=thresh,
        )

    # 3. Environment metadata
    meta = {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        },
        "git_commit": _get_git_commit(),
        "baseline_convention": "O0 unoptimized reference build (-O0) vs AI-selected optimization",
    }
    if metadata:
        meta.update(metadata)

    summary = {
        "n_total": len(program_comparisons),
        "n_improved": n_improved,
        "n_regressed": n_regressed,
        "n_mixed": n_mixed,
        "n_unchanged": n_unchanged,
        "n_incomparable": n_incomparable,
    }

    report = RegressionReport(
        schema_version=REGRESSION_SCHEMA_VERSION,
        report_id=_make_report_id(suite_name),
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
        suite_name=suite_name,
        thresholds=thresh.to_dict(),
        program_comparisons=program_comparisons,
        historical_comparison=hist_comp,
        summary=summary,
        metadata=meta,
    )
    return report


def save_regression_report(report: RegressionReport, output_path: str) -> None:
    """Serialize and save RegressionReport to JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)


def load_regression_report(input_path: str) -> RegressionReport:
    """Load RegressionReport from JSON file."""
    with open(input_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return RegressionReport.from_dict(data)
