"""
moo/regression — Week 10 Optimization Regression & Comparison package.

Builds on top of the Week 9 benchmark infrastructure (moo.bench) to provide:
  - Baseline vs AI-selected optimization comparisons with explicit selection provenance
  - Strategy vs strategy pairwise comparisons
  - Noise-aware regression, improvement, unchanged, and inconclusive detection
  - Signal family grouping (performance, size, security) and derived metric relationships
  - Cross-run historical benchmark comparisons with source hash and environment guards
  - Versioned, structured regression reports (week10.1.0)
"""

from .schema import (
    REGRESSION_SCHEMA_VERSION,
    ComparisonStatus,
    OverallStatus,
    SelectionRecord,
    MetricComparison,
    StrategyComparison,
    ProgramComparison,
    HistoricalProgramComparison,
    HistoricalComparison,
    RegressionReport,
)
from .detector import (
    RegressionThresholds,
    DEFAULT_THRESHOLDS,
    METRIC_SIGNAL_FAMILIES,
    DERIVED_METRIC_RELATIONSHIPS,
    detect_metric_change,
    derive_overall_status,
    derive_family_comparisons,
)
from .comparator import (
    KNOWN_METRIC_SPECS,
    compare_strategies,
    compare_program,
    extract_metrics_from_baseline,
    extract_metrics_from_candidate,
)
from .historical import (
    compare_historical_runs,
)
from .report import (
    build_regression_report,
    save_regression_report,
    load_regression_report,
)

__all__ = [
    "REGRESSION_SCHEMA_VERSION",
    "ComparisonStatus",
    "OverallStatus",
    "SelectionRecord",
    "MetricComparison",
    "StrategyComparison",
    "ProgramComparison",
    "HistoricalProgramComparison",
    "HistoricalComparison",
    "RegressionReport",
    "RegressionThresholds",
    "DEFAULT_THRESHOLDS",
    "METRIC_SIGNAL_FAMILIES",
    "DERIVED_METRIC_RELATIONSHIPS",
    "detect_metric_change",
    "derive_overall_status",
    "derive_family_comparisons",
    "KNOWN_METRIC_SPECS",
    "compare_strategies",
    "compare_program",
    "extract_metrics_from_baseline",
    "extract_metrics_from_candidate",
    "compare_historical_runs",
    "build_regression_report",
    "save_regression_report",
    "load_regression_report",
]
