"""
moo/regression/comparator.py — Baseline-vs-selected and strategy-vs-strategy comparison engine.

Reuses existing Stage 1–6 measurement structures and Stage 2 objective definitions.
Extracts metrics from ProgramRecord (Week 9), MOOEvaluationResult (Stage 3),
or raw dictionaries.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional, Sequence

from ..objectives import ALL_OBJECTIVES, ObjectiveSpec
from .detector import DEFAULT_THRESHOLDS, RegressionThresholds, detect_metric_change, derive_overall_status
from .schema import MetricComparison, OverallStatus, ProgramComparison, StrategyComparison


# ---------------------------------------------------------------------------
# Metric Registry & Specification
# ---------------------------------------------------------------------------

# Canonical metric specs based on moo.objectives and security subsystem
KNOWN_METRIC_SPECS: dict[str, tuple[bool, str]] = {
    # (lower_is_better, unit)
    "execution_time": (True, "seconds"),
    "energy": (True, "joules"),
    "code_size": (True, "bytes"),
    "carbon": (True, "grams CO2eq"),
    "sinks_eliminated": (True, "count"),
    "sinks_folded": (True, "count"),
    "sinks_preserved": (False, "count"),
}

# Dynamically sync with ALL_OBJECTIVES
for obj in ALL_OBJECTIVES:
    KNOWN_METRIC_SPECS[obj.name] = (obj.lower_is_better, obj.unit)


# ---------------------------------------------------------------------------
# Metric Extractors
# ---------------------------------------------------------------------------

def extract_metrics_from_measurement_dict(m: Optional[dict[str, Any]]) -> dict[str, Optional[float]]:
    """Extract standard metrics from a measurement dictionary."""
    metrics: dict[str, Optional[float]] = {
        "execution_time": None,
        "energy": None,
        "code_size": None,
        "carbon": None,
    }
    if not isinstance(m, dict):
        return metrics

    timing = m.get("timing")
    if isinstance(timing, dict):
        metrics["execution_time"] = timing.get("median_s")

    energy = m.get("energy")
    if isinstance(energy, dict):
        metrics["energy"] = energy.get("energy_joules")

    code_size = m.get("code_size")
    if isinstance(code_size, dict):
        metrics["code_size"] = code_size.get("primary_value")

    carbon = m.get("carbon")
    if isinstance(carbon, dict):
        metrics["carbon"] = carbon.get("carbon_grams")

    # Security sinks if present in measurement
    security = m.get("security")
    if isinstance(security, dict):
        if "sinks_eliminated" in security:
            metrics["sinks_eliminated"] = security.get("sinks_eliminated")
        if "sinks_folded" in security:
            metrics["sinks_folded"] = security.get("sinks_folded")
        if "sinks_preserved" in security:
            metrics["sinks_preserved"] = security.get("sinks_preserved")

    return metrics


def extract_metrics_from_baseline(baseline_data: Any) -> dict[str, Optional[float]]:
    """Extract metrics from baseline object or dict."""
    if baseline_data is None:
        return {}

    if hasattr(baseline_data, "measurement"):
        m = getattr(baseline_data, "measurement")
    elif isinstance(baseline_data, dict):
        m = baseline_data.get("measurement")
    else:
        m = None

    return extract_metrics_from_measurement_dict(m)


def extract_metrics_from_candidate(candidate_data: Any) -> dict[str, Optional[float]]:
    """Extract metrics from candidate object or dict."""
    if candidate_data is None:
        return {}

    if hasattr(candidate_data, "measurement"):
        m = getattr(candidate_data, "measurement")
    elif isinstance(candidate_data, dict):
        m = candidate_data.get("measurement")
    else:
        m = None

    metrics = extract_metrics_from_measurement_dict(m)

    # Check top-level security field on candidate if present
    sec = getattr(candidate_data, "security", None) if hasattr(candidate_data, "security") else (candidate_data.get("security") if isinstance(candidate_data, dict) else None)
    if isinstance(sec, dict):
        if "sinks_eliminated" in sec:
            metrics["sinks_eliminated"] = sec.get("sinks_eliminated")
        if "sinks_folded" in sec:
            metrics["sinks_folded"] = sec.get("sinks_folded")
        if "sinks_preserved" in sec:
            metrics["sinks_preserved"] = sec.get("sinks_preserved")

    return metrics


# ---------------------------------------------------------------------------
# Strategy Comparison
# ---------------------------------------------------------------------------

def compare_strategies(
    reference_data: Any,
    target_data: Any,
    target_strategy_name: str,
    reference_strategy_name: str = "baseline (-O0)",
    thresholds: Optional[RegressionThresholds] = None,
    is_valid: bool = True,
    pareto_status: str = "UNKNOWN",
) -> StrategyComparison:
    """
    Compare a target strategy against a reference strategy across all metrics.
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    ref_metrics = extract_metrics_from_baseline(reference_data) if reference_strategy_name.startswith("baseline") else extract_metrics_from_candidate(reference_data)
    tgt_metrics = extract_metrics_from_candidate(target_data)

    # Union of tracked metric names
    all_metric_names = sorted(set(list(ref_metrics.keys()) + list(tgt_metrics.keys())))

    comparisons: dict[str, MetricComparison] = {}
    for mname in all_metric_names:
        lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
        b_val = ref_metrics.get(mname)
        t_val = tgt_metrics.get(mname)
        th_pct = thresh.get_threshold(mname)

        mc = detect_metric_change(
            metric_name=mname,
            baseline_val=b_val,
            target_val=t_val,
            lower_is_better=lower_is_better,
            unit=unit,
            threshold_pct=th_pct,
        )
        comparisons[mname] = mc

    overall = derive_overall_status(comparisons)

    return StrategyComparison(
        strategy_name=target_strategy_name,
        reference_strategy=reference_strategy_name,
        is_valid=is_valid,
        pareto_status=pareto_status,
        metric_comparisons=comparisons,
        overall_status=overall,
    )


# ---------------------------------------------------------------------------
# Program-Level Comparison
# ---------------------------------------------------------------------------

def compare_program(
    record_or_dict: Any,
    selected_strategy: Optional[str] = None,
    thresholds: Optional[RegressionThresholds] = None,
) -> ProgramComparison:
    """
    Compare baseline against selected strategy and all other strategies in a ProgramRecord.

    Parameters
    ----------
    record_or_dict    : ProgramRecord dataclass or dict (from Week 9 benchmark outputs)
    selected_strategy : explicit selected strategy name (e.g. '-O2', 'mem2reg,simplifycfg').
                        If None, will look up from frontier or highest priority candidate.
    thresholds        : RegressionThresholds instance or None for defaults
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    if hasattr(record_or_dict, "to_dict"):
        d = record_or_dict.to_dict()
    elif isinstance(record_or_dict, dict):
        d = record_or_dict
    else:
        d = {}

    pid = str(d.get("program_id", "unknown"))
    status = str(d.get("status", "ok"))
    pipeline_error = d.get("pipeline_error")
    baseline = d.get("baseline")
    candidates = d.get("candidates") or []
    frontier = list(d.get("pareto_frontier") or [])

    # If the program failed at pipeline level
    if status == "pipeline_error" or baseline is None:
        return ProgramComparison(
            program_id=pid,
            status=status if status != "ok" else "pipeline_error",
            baseline_strategy="baseline (-O0)",
            selected_strategy=selected_strategy,
            selected_comparison=None,
            strategy_comparisons={},
            pareto_frontier=frontier,
            overall_status=OverallStatus.INCOMPARABLE,
            pipeline_error=pipeline_error or "Baseline measurement unavailable",
        )

    # 1. Evaluate all available candidate strategies
    strategy_comparisons: dict[str, StrategyComparison] = {}
    for cand in candidates:
        sname = cand.get("strategy_name") if isinstance(cand, dict) else getattr(cand, "strategy_name", "")
        if not sname:
            continue
        is_valid = bool(cand.get("build_ok") and cand.get("correct") and cand.get("measurement")) if isinstance(cand, dict) else cand.is_valid()
        pareto_status = cand.get("pareto_status", "UNKNOWN") if isinstance(cand, dict) else getattr(cand, "pareto_status", "UNKNOWN")

        strat_comp = compare_strategies(
            reference_data=baseline,
            target_data=cand,
            target_strategy_name=sname,
            reference_strategy_name="baseline (-O0)",
            thresholds=thresh,
            is_valid=is_valid,
            pareto_status=pareto_status,
        )
        strategy_comparisons[sname] = strat_comp

    # 2. Determine selected strategy if not given explicitly
    chosen_strategy = selected_strategy
    if chosen_strategy is None:
        # If there is a single strategy on the Pareto frontier, use it
        if len(frontier) == 1:
            chosen_strategy = frontier[0]
        elif len(frontier) > 1:
            # Pick first frontier strategy
            chosen_strategy = frontier[0]
        elif candidates:
            # Fallback to first valid candidate
            for cand in candidates:
                cname = cand.get("strategy_name") if isinstance(cand, dict) else getattr(cand, "strategy_name", "")
                if cname in strategy_comparisons and strategy_comparisons[cname].is_valid:
                    chosen_strategy = cname
                    break

    # 3. Retrieve selected comparison
    selected_comp = strategy_comparisons.get(chosen_strategy) if chosen_strategy else None
    overall = selected_comp.overall_status if selected_comp else OverallStatus.INCOMPARABLE

    return ProgramComparison(
        program_id=pid,
        status=status,
        baseline_strategy="baseline (-O0)",
        selected_strategy=chosen_strategy,
        selected_comparison=selected_comp,
        strategy_comparisons=strategy_comparisons,
        pareto_frontier=frontier,
        overall_status=overall,
        pipeline_error=pipeline_error,
    )
