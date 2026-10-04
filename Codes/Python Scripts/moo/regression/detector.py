"""
moo/regression/detector.py — Regression, improvement, and unchanged detection logic.

Implements direction-aware difference calculation and explicit threshold semantics
for individual metrics and multi-objective aggregations.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Mapping, Optional, Sequence

from .schema import ComparisonStatus, MetricComparison, OverallStatus


# ---------------------------------------------------------------------------
# Configurable Regression Thresholds
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RegressionThresholds:
    """
    Explicit thresholds for classifying performance differences into
    IMPROVED, REGRESSED, or UNCHANGED bands.

    Parameters
    ----------
    default_threshold_pct  : default tolerance band in percent (e.g. 1.0 = ±1.0%)
    per_metric_thresholds  : dictionary of metric-specific override thresholds
                             (e.g. {'code_size': 0.0, 'execution_time': 2.0})
    """
    default_threshold_pct: float = 1.0
    per_metric_thresholds: dict[str, float] = dataclasses.field(default_factory=dict)

    def get_threshold(self, metric_name: str) -> float:
        """Return the percentage threshold for a specific metric."""
        return float(self.per_metric_thresholds.get(metric_name, self.default_threshold_pct))

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_threshold_pct": self.default_threshold_pct,
            "per_metric_thresholds": dict(self.per_metric_thresholds),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RegressionThresholds":
        return cls(
            default_threshold_pct=float(d.get("default_threshold_pct", 1.0)),
            per_metric_thresholds={str(k): float(v) for k, v in d.get("per_metric_thresholds", {}).items()},
        )


# Default canonical thresholds
DEFAULT_THRESHOLDS = RegressionThresholds(
    default_threshold_pct=1.0,
    per_metric_thresholds={
        "execution_time": 1.0,
        "energy": 1.0,
        "code_size": 0.0,      # code size byte changes are deterministic
        "carbon": 1.0,
        "sinks_eliminated": 0.0,
        "sinks_folded": 0.0,
        "sinks_preserved": 0.0,
    },
)


# ---------------------------------------------------------------------------
# Core Metric Comparison
# ---------------------------------------------------------------------------

def is_finite_number(v: Any) -> bool:
    """Return True if v is a non-None, non-boolean number and math.isfinite(v)."""
    if v is None or isinstance(v, bool):
        return False
    try:
        f = float(v)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def detect_metric_change(
    metric_name: str,
    baseline_val: Optional[float],
    target_val: Optional[float],
    lower_is_better: bool = True,
    unit: str = "",
    threshold_pct: float = 1.0,
) -> MetricComparison:
    """
    Compute delta, percentage change, ratio, and classify into ComparisonStatus.

    Parameters
    ----------
    metric_name     : identifier of the metric (e.g., 'execution_time')
    baseline_val    : reference baseline numeric value
    target_val      : candidate / target numeric value
    lower_is_better : whether smaller values denote improvement (e.g. execution_time, energy, size)
    unit            : physical unit for human display
    threshold_pct   : tolerance percentage band (|% change| <= threshold_pct -> UNCHANGED)

    Returns
    -------
    MetricComparison instance with full numerical breakdown and explanation.
    """
    # 1. Check for missing / non-finite inputs
    if not is_finite_number(baseline_val) or not is_finite_number(target_val):
        reason = "Missing or invalid measurement values"
        if baseline_val is None and target_val is None:
            reason = "Both baseline and target values are missing"
        elif baseline_val is None:
            reason = "Baseline value is missing"
        elif target_val is None:
            reason = "Target value is missing"
        elif not is_finite_number(baseline_val):
            reason = f"Baseline value is non-finite: {baseline_val!r}"
        else:
            reason = f"Target value is non-finite: {target_val!r}"

        return MetricComparison(
            metric_name=metric_name,
            baseline_value=float(baseline_val) if is_finite_number(baseline_val) else None,
            target_value=float(target_val) if is_finite_number(target_val) else None,
            delta=None,
            percent_change=None,
            ratio=None,
            lower_is_better=lower_is_better,
            unit=unit,
            status=ComparisonStatus.INCOMPARABLE,
            reason=reason,
            threshold_pct=threshold_pct,
        )

    b = float(baseline_val)
    t = float(target_val)
    delta = t - b

    # 2. Handle zero baseline
    if b == 0.0:
        if t == 0.0:
            return MetricComparison(
                metric_name=metric_name,
                baseline_value=b,
                target_value=t,
                delta=0.0,
                percent_change=0.0,
                ratio=1.0,
                lower_is_better=lower_is_better,
                unit=unit,
                status=ComparisonStatus.UNCHANGED,
                reason="Both baseline and target are 0.0",
                threshold_pct=threshold_pct,
            )
        # Non-zero target with zero baseline
        ratio = None
        percent_change = None
        if lower_is_better:
            status = ComparisonStatus.REGRESSED if t > 0.0 else ComparisonStatus.IMPROVED
        else:
            status = ComparisonStatus.IMPROVED if t > 0.0 else ComparisonStatus.REGRESSED

        verb = "increased" if t > 0.0 else "decreased"
        return MetricComparison(
            metric_name=metric_name,
            baseline_value=b,
            target_value=t,
            delta=delta,
            percent_change=None,
            ratio=None,
            lower_is_better=lower_is_better,
            unit=unit,
            status=status,
            reason=f"Baseline is 0.0; target {verb} to {t:g}",
            threshold_pct=threshold_pct,
        )

    # 3. Standard finite non-zero baseline
    percent_change = (delta / b) * 100.0
    ratio = t / b

    # 4. Status determination using direction semantics and threshold
    if abs(percent_change) <= threshold_pct:
        status = ComparisonStatus.UNCHANGED
        reason = f"{percent_change:+.2f}% unchanged (|change| <= {threshold_pct:.2f}%)"
    else:
        if lower_is_better:
            if percent_change < -threshold_pct:
                status = ComparisonStatus.IMPROVED
                reason = f"{percent_change:+.2f}% improved (threshold {threshold_pct:.2f}%)"
            else:
                status = ComparisonStatus.REGRESSED
                reason = f"{percent_change:+.2f}% regressed (threshold {threshold_pct:.2f}%)"
        else:
            if percent_change > threshold_pct:
                status = ComparisonStatus.IMPROVED
                reason = f"{percent_change:+.2f}% improved (threshold {threshold_pct:.2f}%)"
            else:
                status = ComparisonStatus.REGRESSED
                reason = f"{percent_change:+.2f}% regressed (threshold {threshold_pct:.2f}%)"

    return MetricComparison(
        metric_name=metric_name,
        baseline_value=b,
        target_value=t,
        delta=delta,
        percent_change=percent_change,
        ratio=ratio,
        lower_is_better=lower_is_better,
        unit=unit,
        status=status,
        reason=reason,
        threshold_pct=threshold_pct,
    )


# ---------------------------------------------------------------------------
# Multi-Metric Overall Status Aggregator
# ---------------------------------------------------------------------------

def derive_overall_status(
    comparisons: Sequence[MetricComparison] | Mapping[str, MetricComparison],
) -> OverallStatus:
    """
    Derive aggregated OverallStatus across multiple metric comparisons.

    Logic:
    - If any metric is IMPROVED and none is REGRESSED -> IMPROVED
    - If any metric is REGRESSED and none is IMPROVED -> REGRESSED
    - If at least one is IMPROVED and at least one is REGRESSED -> MIXED (trade-off)
    - If no IMPROVED, no REGRESSED, and at least one UNCHANGED -> UNCHANGED
    - If all metrics are INCOMPARABLE (or empty) -> INCOMPARABLE
    """
    if isinstance(comparisons, Mapping):
        comp_list = list(comparisons.values())
    else:
        comp_list = list(comparisons)

    if not comp_list:
        return OverallStatus.INCOMPARABLE

    has_improved = any(c.status == ComparisonStatus.IMPROVED for c in comp_list)
    has_regressed = any(c.status == ComparisonStatus.REGRESSED for c in comp_list)
    has_unchanged = any(c.status == ComparisonStatus.UNCHANGED for c in comp_list)

    if has_improved and not has_regressed:
        return OverallStatus.IMPROVED
    if has_regressed and not has_improved:
        return OverallStatus.REGRESSED
    if has_improved and has_regressed:
        return OverallStatus.MIXED
    if has_unchanged:
        return OverallStatus.UNCHANGED
    return OverallStatus.INCOMPARABLE
