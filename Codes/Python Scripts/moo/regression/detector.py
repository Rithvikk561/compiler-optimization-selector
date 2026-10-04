"""
moo/regression/detector.py — Regression, improvement, noise-awareness, and signal family detection logic.

Implements direction-aware difference calculation, explicit threshold semantics,
noise-aware confidence gating (detecting inconclusive differences due to high CV/unreliable timing),
and signal family grouping (performance, size, security).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Mapping, Optional, Sequence

from .schema import ComparisonStatus, MetricComparison, OverallStatus


# ---------------------------------------------------------------------------
# Signal Family Mapping & Derived Relationships
# ---------------------------------------------------------------------------

METRIC_SIGNAL_FAMILIES: dict[str, str] = {
    "execution_time":   "performance",
    "energy":           "performance",      # derived from execution_time
    "carbon":           "performance",      # derived from energy
    "code_size":        "size",
    "security_sink_calls": "security",
    "security_vulnerabilities": "security",
    "sinks_eliminated": "security",
    "sinks_folded":     "security",
    "sinks_preserved":  "security",
}

DERIVED_METRIC_RELATIONSHIPS: dict[str, str] = {
    "energy": "derived: elapsed_time * TDP * utilisation (estimated)",
    "carbon": "derived: energy * grid_intensity (estimated)",
}


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
# Core Metric Comparison with Noise Awareness
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
    baseline_is_reliable: Optional[bool] = True,
    target_is_reliable: Optional[bool] = True,
    baseline_cv: Optional[float] = None,
    target_cv: Optional[float] = None,
    is_estimated: bool = False,
) -> MetricComparison:
    """
    Compute delta, percentage change, ratio, and classify into ComparisonStatus.
    Incorporates noise/reliability metadata to detect inconclusive changes.

    Parameters
    ----------
    metric_name          : identifier of the metric (e.g., 'execution_time')
    baseline_val         : reference baseline numeric value
    target_val           : candidate / target numeric value
    lower_is_better      : whether smaller values denote improvement
    unit                 : physical unit for display
    threshold_pct        : tolerance percentage band (|% change| <= threshold_pct -> UNCHANGED)
    baseline_is_reliable : True if baseline timing met reliability criteria
    target_is_reliable   : True if candidate timing met reliability criteria
    baseline_cv          : baseline measurement coefficient of variation (if applicable)
    target_cv            : candidate measurement coefficient of variation (if applicable)
    is_estimated         : True for derived metrics like energy and carbon

    Returns
    -------
    MetricComparison instance with full numerical breakdown, confidence, and explanation.
    """
    # Max CV between baseline and target
    cvs = [cv for cv in (baseline_cv, target_cv) if cv is not None and is_finite_number(cv)]
    noise_cv = max(cvs) if cvs else None
    timing_reliable = (baseline_is_reliable is not False) and (target_is_reliable is not False)

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
            is_reliable=timing_reliable,
            confidence="INCOMPARABLE",
            noise_cv=noise_cv,
            is_estimated=is_estimated,
        )

    b = float(baseline_val)
    t = float(target_val)
    delta = t - b

    # 2. Control Case: Identical Values strictly evaluate to UNCHANGED
    if b == t:
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
            reason="Baseline and target values are identical",
            threshold_pct=threshold_pct,
            is_reliable=timing_reliable,
            confidence="HIGH" if timing_reliable else "LOW",
            noise_cv=noise_cv,
            is_estimated=is_estimated,
        )

    # 3. Handle zero baseline
    if b == 0.0:
        verb = "increased" if t > 0.0 else "decreased"
        if lower_is_better:
            st = ComparisonStatus.REGRESSED if t > 0.0 else ComparisonStatus.IMPROVED
        else:
            st = ComparisonStatus.IMPROVED if t > 0.0 else ComparisonStatus.REGRESSED
        return MetricComparison(
            metric_name=metric_name,
            baseline_value=b,
            target_value=t,
            delta=delta,
            percent_change=None,
            ratio=None,
            lower_is_better=lower_is_better,
            unit=unit,
            status=st,
            reason=f"Baseline is 0.0; target {verb} to {t:g}",
            threshold_pct=threshold_pct,
            is_reliable=timing_reliable,
            confidence="HIGH" if timing_reliable else "LOW",
            noise_cv=noise_cv,
            is_estimated=is_estimated,
        )

    # 4. Standard finite non-zero baseline
    percent_change = (delta / b) * 100.0
    ratio = t / b

    # 5. Noise-Aware Evaluation
    # Only applicable to performance family metrics (execution_time, energy, carbon)
    is_timing_dependent = metric_name in ("execution_time", "energy", "carbon")

    if is_timing_dependent and not timing_reliable:
        # Measurement did not meet reliability criteria (e.g. CV exceeded threshold or timeout)
        return MetricComparison(
            metric_name=metric_name,
            baseline_value=b,
            target_value=t,
            delta=delta,
            percent_change=percent_change,
            ratio=ratio,
            lower_is_better=lower_is_better,
            unit=unit,
            status=ComparisonStatus.INCONCLUSIVE,
            reason=(
                f"Measurement timing is unreliable; observed delta {percent_change:+.2f}% "
                f"cannot be certified as confident regression or improvement"
            ),
            threshold_pct=threshold_pct,
            is_reliable=False,
            confidence="INCONCLUSIVE",
            noise_cv=noise_cv,
            is_estimated=is_estimated,
        )

    # If CV noise is known and delta is smaller than measurement noise
    if is_timing_dependent and noise_cv is not None and noise_cv > 0.0:
        cv_noise_pct = noise_cv * 100.0
        # If delta is inside the noise envelope and exceeds normal threshold
        if abs(percent_change) > threshold_pct and abs(percent_change) < cv_noise_pct:
            return MetricComparison(
                metric_name=metric_name,
                baseline_value=b,
                target_value=t,
                delta=delta,
                percent_change=percent_change,
                ratio=ratio,
                lower_is_better=lower_is_better,
                unit=unit,
                status=ComparisonStatus.INCONCLUSIVE,
                reason=(
                    f"Observed delta {percent_change:+.2f}% is within measurement noise envelope "
                    f"(CV {cv_noise_pct:.1f}%); classified as inconclusive"
                ),
                threshold_pct=threshold_pct,
                is_reliable=timing_reliable,
                confidence="INCONCLUSIVE",
                noise_cv=noise_cv,
                is_estimated=is_estimated,
            )

    # 6. Status determination using direction semantics and threshold
    if abs(percent_change) <= threshold_pct:
        status = ComparisonStatus.UNCHANGED
        reason = f"{percent_change:+.2f}% unchanged (|change| <= {threshold_pct:.2f}%)"
        conf = "HIGH"
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

        conf = "HIGH" if timing_reliable else "LOW"

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
        is_reliable=timing_reliable,
        confidence=conf,
        noise_cv=noise_cv,
        is_estimated=is_estimated,
    )


# ---------------------------------------------------------------------------
# Signal Family & Overall Status Aggregators
# ---------------------------------------------------------------------------

def derive_family_comparisons(
    metric_comparisons: Mapping[str, MetricComparison],
) -> tuple[dict[str, dict[str, MetricComparison]], dict[str, OverallStatus]]:
    """
    Group metric comparisons by their canonical signal family (performance, size, security)
    and compute family-level statuses.
    """
    fam_comp: dict[str, dict[str, MetricComparison]] = {}
    fam_st: dict[str, OverallStatus] = {}

    for mname, comp in metric_comparisons.items():
        fam = METRIC_SIGNAL_FAMILIES.get(mname, "other")
        if fam not in fam_comp:
            fam_comp[fam] = {}
        fam_comp[fam][mname] = comp

    for fam, m_dict in fam_comp.items():
        fam_st[fam] = derive_overall_status(m_dict)

    return fam_comp, fam_st


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
    - If no IMPROVED, no REGRESSED, but has INCONCLUSIVE -> INCONCLUSIVE
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
    has_inconclusive = any(c.status == ComparisonStatus.INCONCLUSIVE for c in comp_list)

    if has_improved and not has_regressed:
        return OverallStatus.IMPROVED
    if has_regressed and not has_improved:
        return OverallStatus.REGRESSED
    if has_improved and has_regressed:
        return OverallStatus.MIXED
    if has_unchanged:
        return OverallStatus.UNCHANGED
    if has_inconclusive:
        return OverallStatus.INCONCLUSIVE
    return OverallStatus.INCOMPARABLE
