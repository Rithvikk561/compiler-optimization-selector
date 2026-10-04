"""
moo/regression/historical.py — Historical run-to-run benchmark regression comparison.

Compares benchmark outputs across different runs (e.g. earlier git commit vs current,
or baseline test suite vs regression test suite) using Week 9 structured ProgramRecords.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional, Sequence

from .comparator import (
    KNOWN_METRIC_SPECS,
    extract_metrics_from_baseline,
    extract_metrics_from_candidate,
)
from .detector import DEFAULT_THRESHOLDS, RegressionThresholds, derive_overall_status, detect_metric_change
from .schema import (
    HistoricalComparison,
    HistoricalProgramComparison,
    MetricComparison,
    OverallStatus,
)


def _index_records_by_id(records: Sequence[Any]) -> tuple[dict[str, Any], Optional[str]]:
    """Index ProgramRecord objects or dicts by program_id and infer run_id."""
    index: dict[str, Any] = {}
    inferred_run_id: Optional[str] = None
    for r in records:
        if hasattr(r, "to_dict"):
            d = r.to_dict()
        elif isinstance(r, dict):
            d = r
        else:
            continue

        pid = d.get("program_id")
        if pid:
            index[str(pid)] = d
            if inferred_run_id is None and d.get("run_id"):
                inferred_run_id = str(d.get("run_id"))

    return index, inferred_run_id


def compare_historical_runs(
    previous_records: Sequence[Any],
    current_records: Sequence[Any],
    previous_run_id: Optional[str] = None,
    current_run_id: Optional[str] = None,
    strategy_to_compare: str = "baseline (-O0)",
    thresholds: Optional[RegressionThresholds] = None,
) -> HistoricalComparison:
    """
    Compare two historical benchmark runs program by program.

    Parameters
    ----------
    previous_records    : sequence of ProgramRecord objects/dicts from historical run
    current_records     : sequence of ProgramRecord objects/dicts from current run
    previous_run_id     : identifier for previous run (inferred if None)
    current_run_id      : identifier for current run (inferred if None)
    strategy_to_compare : primary strategy to track across runs (default: 'baseline (-O0)')
    thresholds          : RegressionThresholds or None for defaults

    Returns
    -------
    HistoricalComparison containing per-program deltas and suite summary.
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    prev_map, prev_inferred = _index_records_by_id(previous_records)
    curr_map, curr_inferred = _index_records_by_id(current_records)

    p_run = previous_run_id or prev_inferred or "previous_run"
    c_run = current_run_id or curr_inferred or "current_run"

    all_pids = sorted(set(list(prev_map.keys()) + list(curr_map.keys())))

    progs: dict[str, HistoricalProgramComparison] = {}
    n_common = 0
    n_missing_prev = 0
    n_missing_curr = 0
    n_failed_prev = 0
    n_failed_curr = 0
    n_improved = 0
    n_regressed = 0
    n_mixed = 0
    n_unchanged = 0

    for pid in all_pids:
        prev_d = prev_map.get(pid)
        curr_d = curr_map.get(pid)

        # 1. Missing in current
        if curr_d is None:
            n_missing_curr += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="missing_current",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=["Program was present in previous run but missing in current run"],
            )
            continue

        # 2. Missing in previous
        if prev_d is None:
            n_missing_prev += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="missing_previous",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=["Program was added in current run; no previous run data available"],
            )
            continue

        # 3. Present in both
        n_common += 1

        # Check failures
        prev_status = prev_d.get("status", "ok")
        curr_status = curr_d.get("status", "ok")
        prev_err = prev_d.get("pipeline_error")
        curr_err = curr_d.get("pipeline_error")

        if prev_status == "pipeline_error" or prev_d.get("baseline") is None:
            n_failed_prev += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="failed_previous",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=[f"Previous run failed: {prev_err or 'baseline unavailable'}"],
            )
            continue

        if curr_status == "pipeline_error" or curr_d.get("baseline") is None:
            n_failed_curr += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="failed_current",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=[f"Current run failed: {curr_err or 'baseline unavailable'}"],
            )
            continue

        # Both succeeded: extract metric comparison for strategy_to_compare
        # Reference is previous run value; target is current run value.
        def _get_strat_metrics(d: dict, strat: str) -> dict[str, Optional[float]]:
            if strat == "baseline (-O0)" or strat == "-O0_baseline":
                return extract_metrics_from_baseline(d.get("baseline"))
            # Search candidates
            cands = d.get("candidates") or []
            for c in cands:
                name = c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")
                if name == strat:
                    return extract_metrics_from_candidate(c)
            return {}

        prev_metrics = _get_strat_metrics(prev_d, strategy_to_compare)
        curr_metrics = _get_strat_metrics(curr_d, strategy_to_compare)

        all_m = sorted(set(list(prev_metrics.keys()) + list(curr_metrics.keys())))
        m_comps: dict[str, MetricComparison] = {}
        for mname in all_m:
            lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
            p_val = prev_metrics.get(mname)
            c_val = curr_metrics.get(mname)
            th_pct = thresh.get_threshold(mname)

            mc = detect_metric_change(
                metric_name=mname,
                baseline_val=p_val,    # previous run is baseline
                target_val=c_val,      # current run is target
                lower_is_better=lower_is_better,
                unit=unit,
                threshold_pct=th_pct,
            )
            m_comps[mname] = mc

        overall = derive_overall_status(m_comps)
        if overall == OverallStatus.IMPROVED:
            n_improved += 1
        elif overall == OverallStatus.REGRESSED:
            n_regressed += 1
        elif overall == OverallStatus.MIXED:
            n_mixed += 1
        elif overall == OverallStatus.UNCHANGED:
            n_unchanged += 1

        # Also extract per-strategy comparisons for common candidate strategies
        strat_historical: dict[str, dict[str, MetricComparison]] = {}
        prev_cands = {
            (c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")): c
            for c in (prev_d.get("candidates") or [])
        }
        curr_cands = {
            (c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")): c
            for c in (curr_d.get("candidates") or [])
        }
        common_strats = sorted(set(prev_cands.keys()).intersection(curr_cands.keys()))
        for sname in common_strats:
            if not sname:
                continue
            s_prev_m = extract_metrics_from_candidate(prev_cands[sname])
            s_curr_m = extract_metrics_from_candidate(curr_cands[sname])
            s_metrics_dict: dict[str, MetricComparison] = {}
            for mname in sorted(set(list(s_prev_m.keys()) + list(s_curr_m.keys()))):
                lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
                th_pct = thresh.get_threshold(mname)
                s_metrics_dict[mname] = detect_metric_change(
                    metric_name=mname,
                    baseline_val=s_prev_m.get(mname),
                    target_val=s_curr_m.get(mname),
                    lower_is_better=lower_is_better,
                    unit=unit,
                    threshold_pct=th_pct,
                )
            strat_historical[sname] = s_metrics_dict

        progs[pid] = HistoricalProgramComparison(
            program_id=pid,
            status="ok",
            previous_run_id=p_run,
            current_run_id=c_run,
            metric_comparisons=m_comps,
            strategy_historical=strat_historical,
            overall_status=overall,
            notes=[],
        )

    summary = {
        "n_total_programs": len(all_pids),
        "n_common": n_common,
        "n_missing_previous": n_missing_prev,
        "n_missing_current": n_missing_curr,
        "n_failed_previous": n_failed_prev,
        "n_failed_current": n_failed_curr,
        "n_improved": n_improved,
        "n_regressed": n_regressed,
        "n_mixed": n_mixed,
        "n_unchanged": n_unchanged,
    }

    return HistoricalComparison(
        previous_run_id=p_run,
        current_run_id=c_run,
        programs=progs,
        summary=summary,
    )
