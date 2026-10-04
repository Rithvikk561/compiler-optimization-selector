"""
moo/regression — Week 10 Optimization Regression & Comparison package.

Builds on top of the Week 9 benchmark infrastructure (moo.bench) to provide:
  - Baseline vs AI-selected optimization comparisons
  - Strategy vs strategy pairwise comparisons
  - Direction-aware regression, improvement, and unchanged detection
  - Multi-metric aggregation
  - Cross-run historical benchmark comparisons
  - Versioned, structured regression reports (week10.1.0)
"""

from .schema import (
    REGRESSION_SCHEMA_VERSION,
    ComparisonStatus,
    OverallStatus,
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
    detect_metric_change,
    derive_overall_status,
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
    "MetricComparison",
    "StrategyComparison",
    "ProgramComparison",
    "HistoricalProgramComparison",
    "HistoricalComparison",
    "RegressionReport",
    "RegressionThresholds",
    "DEFAULT_THRESHOLDS",
    "detect_metric_change",
    "derive_overall_status",
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
