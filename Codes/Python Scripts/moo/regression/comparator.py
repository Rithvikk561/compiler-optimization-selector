"""
moo/regression/comparator.py — Baseline-vs-selected and strategy-vs-strategy comparison engine.

Reuses existing Stage 1–6 measurement structures and Stage 2 objective definitions.
Extracts metrics, reliability, and noise metadata from ProgramRecord (Week 9),
MOOEvaluationResult (Stage 3), or raw dictionaries.
Enforces explicit selection provenance (refusing to silently fabricate AI selections).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional, Sequence

from ..objectives import ALL_OBJECTIVES, ObjectiveSpec
from .detector import (
    DEFAULT_THRESHOLDS,
    METRIC_SIGNAL_FAMILIES,
    RegressionThresholds,
    derive_family_comparisons,
    derive_overall_status,
    detect_metric_change,
)
from .schema import (
    MetricComparison,
    OverallStatus,
    ProgramComparison,
    SelectionRecord,
    StrategyComparison,
)


# ---------------------------------------------------------------------------
# Metric Registry & Specification
# ---------------------------------------------------------------------------

# Canonical metric specs based on moo.objectives and security subsystem
KNOWN_METRIC_SPECS: dict[str, tuple[bool, str]] = {
    # (lower_is_better, unit)
    "execution_time":   (True, "seconds"),
    "energy":           (True, "joules"),
    "code_size":        (True, "bytes"),
    "carbon":           (True, "grams CO2eq"),
    "sinks_eliminated": (True, "count"),
    "sinks_folded":     (True, "count"),
    "sinks_preserved":  (False, "count"),
}

# Dynamically sync with ALL_OBJECTIVES
for obj in ALL_OBJECTIVES:
    KNOWN_METRIC_SPECS[obj.name] = (obj.lower_is_better, obj.unit)


# ---------------------------------------------------------------------------
# Metric & Metadata Extractors
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ExtractedMeasurement:
    """Extracted numeric metrics along with timing reliability and noise metadata."""
    metrics: dict[str, Optional[float]]
    timing_is_reliable: Optional[bool] = True
    timing_cv: Optional[float] = None
    energy_is_estimated: bool = True
    carbon_is_estimated: bool = True


def extract_measurement_from_dict(m: Optional[dict[str, Any]]) -> ExtractedMeasurement:
    """Extract standard metrics and noise/reliability metadata from measurement dict."""
    metrics: dict[str, Optional[float]] = {
        "execution_time": None,
        "energy": None,
        "code_size": None,
        "carbon": None,
    }
    timing_reliable: Optional[bool] = True
    timing_cv: Optional[float] = None
    energy_est: bool = True
    carbon_est: bool = True

    if not isinstance(m, dict):
        return ExtractedMeasurement(metrics, timing_reliable, timing_cv, energy_est, carbon_est)

    timing = m.get("timing")
    if isinstance(timing, dict):
        metrics["execution_time"] = timing.get("median_s")
        timing_cv = timing.get("cv")
        if "timing_is_reliable" in timing:
            timing_reliable = timing.get("timing_is_reliable")
        elif timing_cv is not None and timing_cv > 0.10:
            # Over threshold defaults to unreliable
            timing_reliable = False

    energy = m.get("energy")
    if isinstance(energy, dict):
        metrics["energy"] = energy.get("energy_joules")
        energy_est = energy.get("is_estimated", True)

    code_size = m.get("code_size")
    if isinstance(code_size, dict):
        metrics["code_size"] = code_size.get("primary_value")

    carbon = m.get("carbon")
    if isinstance(carbon, dict):
        metrics["carbon"] = carbon.get("carbon_grams")
        carbon_est = carbon.get("is_estimated", True)

    # Security sinks if present in measurement
    security = m.get("security")
    if isinstance(security, dict):
        if "sinks_eliminated" in security:
            metrics["sinks_eliminated"] = security.get("sinks_eliminated")
        if "sinks_folded" in security:
            metrics["sinks_folded"] = security.get("sinks_folded")
        if "sinks_preserved" in security:
            metrics["sinks_preserved"] = security.get("sinks_preserved")

    return ExtractedMeasurement(
        metrics=metrics,
        timing_is_reliable=timing_reliable,
        timing_cv=timing_cv,
        energy_is_estimated=energy_est,
        carbon_is_estimated=carbon_est,
    )


def extract_metrics_from_baseline(baseline_data: Any) -> ExtractedMeasurement:
    """Extract metrics from baseline object or dict."""
    if baseline_data is None:
        return ExtractedMeasurement({})

    if hasattr(baseline_data, "measurement"):
        m = getattr(baseline_data, "measurement")
    elif isinstance(baseline_data, dict):
        m = baseline_data.get("measurement")
    else:
        m = None

    return extract_measurement_from_dict(m)


def extract_metrics_from_candidate(candidate_data: Any) -> ExtractedMeasurement:
    """Extract metrics from candidate object or dict."""
    if candidate_data is None:
        return ExtractedMeasurement({})

    if hasattr(candidate_data, "measurement"):
        m = getattr(candidate_data, "measurement")
    elif isinstance(candidate_data, dict):
        m = candidate_data.get("measurement")
    else:
        m = None

    em = extract_measurement_from_dict(m)

    # Check top-level security field on candidate if present
    sec = getattr(candidate_data, "security", None) if hasattr(candidate_data, "security") else (candidate_data.get("security") if isinstance(candidate_data, dict) else None)
    if isinstance(sec, dict):
        if "sinks_eliminated" in sec:
            em.metrics["sinks_eliminated"] = sec.get("sinks_eliminated")
        if "sinks_folded" in sec:
            em.metrics["sinks_folded"] = sec.get("sinks_folded")
        if "sinks_preserved" in sec:
            em.metrics["sinks_preserved"] = sec.get("sinks_preserved")

    return em


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
    Carries noise/reliability metadata and computes signal family grouping.
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    ref_em = extract_metrics_from_baseline(reference_data) if reference_strategy_name.startswith("baseline") else extract_metrics_from_candidate(reference_data)
    tgt_em = extract_metrics_from_candidate(target_data)

    ref_metrics = ref_em.metrics
    tgt_metrics = tgt_em.metrics

    all_metric_names = sorted(set(list(ref_metrics.keys()) + list(tgt_metrics.keys())))

    comparisons: dict[str, MetricComparison] = {}
    for mname in all_metric_names:
        lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
        b_val = ref_metrics.get(mname)
        t_val = tgt_metrics.get(mname)
        th_pct = thresh.get_threshold(mname)

        is_est = False
        if mname == "energy":
            is_est = ref_em.energy_is_estimated or tgt_em.energy_is_estimated
        elif mname == "carbon":
            is_est = ref_em.carbon_is_estimated or tgt_em.carbon_is_estimated

        mc = detect_metric_change(
            metric_name=mname,
            baseline_val=b_val,
            target_val=t_val,
            lower_is_better=lower_is_better,
            unit=unit,
            threshold_pct=th_pct,
            baseline_is_reliable=ref_em.timing_is_reliable,
            target_is_reliable=tgt_em.timing_is_reliable,
            baseline_cv=ref_em.timing_cv,
            target_cv=tgt_em.timing_cv,
            is_estimated=is_est,
        )
        comparisons[mname] = mc

    overall = derive_overall_status(comparisons)
    fam_comp, fam_st = derive_family_comparisons(comparisons)

    return StrategyComparison(
        strategy_name=target_strategy_name,
        reference_strategy=reference_strategy_name,
        is_valid=is_valid,
        pareto_status=pareto_status,
        metric_comparisons=comparisons,
        overall_status=overall,
        family_comparisons=fam_comp,
        family_status=fam_st,
    )


# ---------------------------------------------------------------------------
# Program-Level Comparison
# ---------------------------------------------------------------------------

def compare_program(
    record_or_dict: Any,
    selected_strategy: Optional[str] = None,
    selection_record: Optional[SelectionRecord] = None,
    thresholds: Optional[RegressionThresholds] = None,
) -> ProgramComparison:
    """
    Compare baseline against selected strategy and all other strategies in a ProgramRecord.

    Parameters
    ----------
    record_or_dict    : ProgramRecord dataclass or dict (from Week 9 benchmark outputs)
    selected_strategy : explicit selected strategy name (e.g. '-O2', 'mem2reg,simplifycfg').
    selection_record  : SelectionRecord verifying explicit provenance of the AI selection.
                        If neither selected_strategy nor selection_record is provided,
                        this function REFUSES to fabricate an AI selection and leaves
                        selected_comparison as None.
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

    # Source hash for provenance validation
    record_sha = None
    ce = d.get("corpus_entry")
    if isinstance(ce, dict) and ce.get("source_sha256"):
        record_sha = ce.get("source_sha256")
    elif d.get("source_sha256"):
        record_sha = d.get("source_sha256")

    # If the program failed at pipeline level
    if status == "pipeline_error" or baseline is None:
        return ProgramComparison(
            program_id=pid,
            status=status if status != "ok" else "pipeline_error",
            baseline_strategy="baseline (-O0)",
            selected_strategy=selected_strategy,
            selected_comparison=None,
            selection_provenance=selection_record,
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

    # 2. Determine selected strategy strictly through provenance or explicit caller argument
    chosen_strategy: Optional[str] = None
    provenance_obj: Optional[SelectionRecord] = selection_record

    if selection_record is not None:
        # Validate program identity
        if selection_record.program_id and selection_record.program_id != pid:
            raise ValueError(
                f"SelectionRecord program_id '{selection_record.program_id}' does not match record program_id '{pid}'"
            )
        if record_sha and selection_record.source_sha256 and selection_record.source_sha256 != record_sha:
            raise ValueError(
                f"SelectionRecord source_sha256 '{selection_record.source_sha256}' does not match record source_sha256 '{record_sha}'"
            )
        chosen_strategy = selection_record.selected_strategy
    elif selected_strategy is not None:
        chosen_strategy = selected_strategy
    else:
        # DO NOT fabricate AI selection: do NOT default to frontier[0] or first candidate!
        chosen_strategy = None

    # 3. Retrieve selected comparison
    selected_comp: Optional[StrategyComparison] = None
    overall: OverallStatus = OverallStatus.INCOMPARABLE
    fam_comp: dict[str, dict[str, MetricComparison]] = {}
    fam_st: dict[str, OverallStatus] = {}

    if chosen_strategy and chosen_strategy in strategy_comparisons:
        selected_comp = strategy_comparisons[chosen_strategy]
        overall = selected_comp.overall_status
        fam_comp = selected_comp.family_comparisons
        fam_st = selected_comp.family_status

    return ProgramComparison(
        program_id=pid,
        status=status,
        baseline_strategy="baseline (-O0)",
        selected_strategy=chosen_strategy,
        selected_comparison=selected_comp,
        selection_provenance=provenance_obj,
        strategy_comparisons=strategy_comparisons,
        pareto_frontier=frontier,
        overall_status=overall,
        family_comparisons=fam_comp,
        family_status=fam_st,
        pipeline_error=pipeline_error,
    )
