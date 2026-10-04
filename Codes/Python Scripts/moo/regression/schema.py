"""
moo/regression/schema.py — Versioned data models for Week 10 Optimization Regression & Comparison.

Builds on top of the Week 9 benchmark architecture (moo.bench) and Stage 2 multi-objective
definitions (moo.objectives).

Core models:
  - ComparisonStatus: Enum for per-metric outcome (IMPROVED, REGRESSED, UNCHANGED, INCONCLUSIVE, INCOMPARABLE)
  - OverallStatus: Enum for aggregated program outcome (IMPROVED, REGRESSED, MIXED, UNCHANGED, INCONCLUSIVE, INCOMPARABLE)
  - SelectionRecord: Explicit provenance record for optimization strategy selection
  - MetricComparison: Explicit pairwise comparison between baseline and target metric values
  - StrategyComparison: Comparison across all supported metrics for a given strategy
  - ProgramComparison: Full comparison record for a single program (baseline vs selected & all strategies)
  - HistoricalProgramComparison: Per-program delta across historical benchmark runs
  - HistoricalComparison: Complete suite-level comparison between two benchmark runs
  - RegressionReport: Top-level versioned report container
"""

from __future__ import annotations

import dataclasses
from enum import Enum
import json
import math
from typing import Any, Optional


REGRESSION_SCHEMA_VERSION: str = "week10.1.0"
"""Version identifier for all Week 10 regression models and reports."""


class ComparisonStatus(str, Enum):
    """Classification of a single metric's comparison outcome."""
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    UNCHANGED = "UNCHANGED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INCOMPARABLE = "INCOMPARABLE"


class OverallStatus(str, Enum):
    """Classification of an aggregated multi-metric comparison outcome."""
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    MIXED = "MIXED"
    UNCHANGED = "UNCHANGED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INCOMPARABLE = "INCOMPARABLE"


@dataclasses.dataclass
class SelectionRecord:
    """
    Explicit provenance record for an optimization strategy selection.

    Prevents regression comparison from silently defaulting to frontier[0]
    or fabricating an AI selection when no selection actually occurred.

    Fields
    ------
    program_id        : stable identifier of the benchmark program
    source_sha256     : SHA-256 hex digest of the C source code at selection time
    selected_strategy : strategy selected (e.g. 'mem2reg,simplifycfg', '-O2')
    selection_source  : origin of selection (e.g. 'DQN∩Pareto', 'DQN_fallback', 'manual')
    model_identifier  : model name or checkpoint hash (or None)
    trace_id          : identifier or reference to DecisionTrace (or None)
    timestamp         : ISO-8601 timestamp string (or None)
    """
    program_id: str
    source_sha256: str
    selected_strategy: str
    selection_source: str = "DQN∩Pareto"
    model_identifier: Optional[str] = None
    trace_id: Optional[str] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "source_sha256": self.source_sha256,
            "selected_strategy": self.selected_strategy,
            "selection_source": self.selection_source,
            "model_identifier": self.model_identifier,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SelectionRecord":
        return cls(
            program_id=str(d.get("program_id", "")),
            source_sha256=str(d.get("source_sha256", "")),
            selected_strategy=str(d.get("selected_strategy", "")),
            selection_source=str(d.get("selection_source", "DQN∩Pareto")),
            model_identifier=d.get("model_identifier"),
            trace_id=d.get("trace_id"),
            timestamp=d.get("timestamp"),
        )


@dataclasses.dataclass
class MetricComparison:
    """
    Comparison between a reference/baseline metric and a candidate/target metric.

    Fields
    ------
    metric_name     : identifier matching existing project definitions
                      (e.g., 'execution_time', 'energy', 'code_size', 'carbon', 'sinks_eliminated')
    baseline_value  : reference value (float, int, or None if missing)
    target_value    : candidate value (float, int, or None if missing)
    delta           : target_value - baseline_value (None if incomparable)
    percent_change  : percentage change relative to baseline ((target - base) / base * 100)
    ratio           : target_value / baseline_value
    lower_is_better : directionality semantics (True for execution_time, energy, size, carbon, sinks_eliminated)
    unit            : physical unit (e.g., 'seconds', 'joules', 'bytes', 'grams', 'count')
    status          : ComparisonStatus classification
    reason          : human-readable explanation of the comparison result
    threshold_pct   : percentage threshold used for unchanged band
    is_reliable     : whether the measurements met timing/measurement reliability criteria
    confidence      : 'HIGH', 'LOW', or 'INCONCLUSIVE' based on CV noise and reliability
    noise_cv        : highest coefficient of variation between baseline and target
    is_estimated    : whether the metric is estimated rather than direct hardware measurement
    """
    metric_name: str
    baseline_value: Optional[float]
    target_value: Optional[float]
    delta: Optional[float]
    percent_change: Optional[float]
    ratio: Optional[float]
    lower_is_better: bool
    unit: str
    status: ComparisonStatus
    reason: str
    threshold_pct: float = 1.0
    is_reliable: Optional[bool] = True
    confidence: str = "HIGH"
    noise_cv: Optional[float] = None
    is_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "baseline_value": self.baseline_value,
            "target_value": self.target_value,
            "delta": self.delta,
            "percent_change": self.percent_change,
            "ratio": self.ratio,
            "lower_is_better": self.lower_is_better,
            "unit": self.unit,
            "status": self.status.value if isinstance(self.status, ComparisonStatus) else str(self.status),
            "reason": self.reason,
            "threshold_pct": self.threshold_pct,
            "is_reliable": self.is_reliable,
            "confidence": self.confidence,
            "noise_cv": self.noise_cv,
            "is_estimated": self.is_estimated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetricComparison":
        raw_status = d.get("status", ComparisonStatus.INCOMPARABLE.value)
        status = ComparisonStatus(raw_status) if raw_status in ComparisonStatus._value2member_map_ else ComparisonStatus.INCOMPARABLE
        return cls(
            metric_name=str(d.get("metric_name", "")),
            baseline_value=d.get("baseline_value"),
            target_value=d.get("target_value"),
            delta=d.get("delta"),
            percent_change=d.get("percent_change"),
            ratio=d.get("ratio"),
            lower_is_better=bool(d.get("lower_is_better", True)),
            unit=str(d.get("unit", "")),
            status=status,
            reason=str(d.get("reason", "")),
            threshold_pct=float(d.get("threshold_pct", 1.0)),
            is_reliable=d.get("is_reliable", True),
            confidence=str(d.get("confidence", "HIGH")),
            noise_cv=d.get("noise_cv"),
            is_estimated=bool(d.get("is_estimated", False)),
        )


@dataclasses.dataclass
class StrategyComparison:
    """
    Comparison of a specific optimization strategy against the baseline.

    Fields
    ------
    strategy_name       : name of the evaluated strategy (e.g., '-O2', 'mem2reg,simplifycfg')
    reference_strategy  : reference strategy compared against (default: 'baseline (-O0)')
    is_valid            : True if strategy built, ran correctly, and produced valid measurements
    pareto_status       : 'FRONTIER', 'DOMINATED', 'INVALID', or 'UNKNOWN'
    metric_comparisons  : dict mapping metric_name -> MetricComparison
    overall_status      : OverallStatus across all evaluated metrics
    family_comparisons  : dict mapping family_name -> {metric_name: MetricComparison}
    family_status       : dict mapping family_name -> OverallStatus
    """
    strategy_name: str
    reference_strategy: str = "baseline (-O0)"
    is_valid: bool = True
    pareto_status: str = "UNKNOWN"
    metric_comparisons: dict[str, MetricComparison] = dataclasses.field(default_factory=dict)
    overall_status: OverallStatus = OverallStatus.INCOMPARABLE
    family_comparisons: dict[str, dict[str, MetricComparison]] = dataclasses.field(default_factory=dict)
    family_status: dict[str, OverallStatus] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "reference_strategy": self.reference_strategy,
            "is_valid": self.is_valid,
            "pareto_status": self.pareto_status,
            "metric_comparisons": {k: v.to_dict() for k, v in self.metric_comparisons.items()},
            "overall_status": self.overall_status.value if isinstance(self.overall_status, OverallStatus) else str(self.overall_status),
            "family_comparisons": {
                fam: {m: comp.to_dict() for m, comp in m_dict.items()}
                for fam, m_dict in self.family_comparisons.items()
            },
            "family_status": {
                fam: st.value if isinstance(st, OverallStatus) else str(st)
                for fam, st in self.family_status.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StrategyComparison":
        raw_overall = d.get("overall_status", OverallStatus.INCOMPARABLE.value)
        overall = OverallStatus(raw_overall) if raw_overall in OverallStatus._value2member_map_ else OverallStatus.INCOMPARABLE
        raw_metrics = d.get("metric_comparisons", {})
        metrics = {k: MetricComparison.from_dict(v) for k, v in raw_metrics.items()} if isinstance(raw_metrics, dict) else {}

        raw_fam_comp = d.get("family_comparisons", {})
        fam_comp: dict[str, dict[str, MetricComparison]] = {}
        if isinstance(raw_fam_comp, dict):
            for fam, m_dict in raw_fam_comp.items():
                if isinstance(m_dict, dict):
                    fam_comp[fam] = {m: MetricComparison.from_dict(comp) for m, comp in m_dict.items()}

        raw_fam_st = d.get("family_status", {})
        fam_st: dict[str, OverallStatus] = {}
        if isinstance(raw_fam_st, dict):
            for fam, st_val in raw_fam_st.items():
                fam_st[fam] = OverallStatus(st_val) if st_val in OverallStatus._value2member_map_ else OverallStatus.INCOMPARABLE

        return cls(
            strategy_name=str(d.get("strategy_name", "")),
            reference_strategy=str(d.get("reference_strategy", "baseline (-O0)")),
            is_valid=bool(d.get("is_valid", True)),
            pareto_status=str(d.get("pareto_status", "UNKNOWN")),
            metric_comparisons=metrics,
            overall_status=overall,
            family_comparisons=fam_comp,
            family_status=fam_st,
        )


@dataclasses.dataclass
class ProgramComparison:
    """
    Comprehensive regression and optimization comparison for a single benchmark program.

    Fields
    ------
    program_id           : stable identifier of the program (e.g., '01_hello_world')
    status               : 'ok', 'pipeline_error', 'no_valid_candidates', or 'missing'
    baseline_strategy    : reference baseline strategy name (always 'baseline (-O0)')
    selected_strategy    : strategy chosen by AI / MOO selector (or None if unavailable)
    selected_comparison  : StrategyComparison for selected_strategy vs baseline (or None)
    selection_provenance : SelectionRecord certifying origin of selection (or None)
    strategy_comparisons : dict mapping strategy_name -> StrategyComparison for all tested strategies
    pareto_frontier      : list of non-dominated strategy names
    overall_status       : OverallStatus of the selected strategy vs baseline
    family_comparisons   : dict mapping family_name -> {metric_name: MetricComparison} for selected
    family_status        : dict mapping family_name -> OverallStatus for selected
    pipeline_error       : error string if the evaluation pipeline failed (None if ok)
    """
    program_id: str
    status: str
    baseline_strategy: str = "baseline (-O0)"
    selected_strategy: Optional[str] = None
    selected_comparison: Optional[StrategyComparison] = None
    selection_provenance: Optional[SelectionRecord] = None
    strategy_comparisons: dict[str, StrategyComparison] = dataclasses.field(default_factory=dict)
    pareto_frontier: list[str] = dataclasses.field(default_factory=list)
    overall_status: OverallStatus = OverallStatus.INCOMPARABLE
    family_comparisons: dict[str, dict[str, MetricComparison]] = dataclasses.field(default_factory=dict)
    family_status: dict[str, OverallStatus] = dataclasses.field(default_factory=dict)
    pipeline_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "status": self.status,
            "baseline_strategy": self.baseline_strategy,
            "selected_strategy": self.selected_strategy,
            "selected_comparison": self.selected_comparison.to_dict() if self.selected_comparison else None,
            "selection_provenance": self.selection_provenance.to_dict() if self.selection_provenance else None,
            "strategy_comparisons": {k: v.to_dict() for k, v in self.strategy_comparisons.items()},
            "pareto_frontier": list(self.pareto_frontier),
            "overall_status": self.overall_status.value if isinstance(self.overall_status, OverallStatus) else str(self.overall_status),
            "family_comparisons": {
                fam: {m: comp.to_dict() for m, comp in m_dict.items()}
                for fam, m_dict in self.family_comparisons.items()
            },
            "family_status": {
                fam: st.value if isinstance(st, OverallStatus) else str(st)
                for fam, st in self.family_status.items()
            },
            "pipeline_error": self.pipeline_error,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProgramComparison":
        raw_overall = d.get("overall_status", OverallStatus.INCOMPARABLE.value)
        overall = OverallStatus(raw_overall) if raw_overall in OverallStatus._value2member_map_ else OverallStatus.INCOMPARABLE
        raw_sel = d.get("selected_comparison")
        sel_comp = StrategyComparison.from_dict(raw_sel) if isinstance(raw_sel, dict) else None
        raw_prov = d.get("selection_provenance")
        prov = SelectionRecord.from_dict(raw_prov) if isinstance(raw_prov, dict) else None

        raw_strats = d.get("strategy_comparisons", {})
        strat_comps = {k: StrategyComparison.from_dict(v) for k, v in raw_strats.items()} if isinstance(raw_strats, dict) else {}

        raw_fam_comp = d.get("family_comparisons", {})
        fam_comp: dict[str, dict[str, MetricComparison]] = {}
        if isinstance(raw_fam_comp, dict):
            for fam, m_dict in raw_fam_comp.items():
                if isinstance(m_dict, dict):
                    fam_comp[fam] = {m: MetricComparison.from_dict(comp) for m, comp in m_dict.items()}

        raw_fam_st = d.get("family_status", {})
        fam_st: dict[str, OverallStatus] = {}
        if isinstance(raw_fam_st, dict):
            for fam, st_val in raw_fam_st.items():
                fam_st[fam] = OverallStatus(st_val) if st_val in OverallStatus._value2member_map_ else OverallStatus.INCOMPARABLE

        return cls(
            program_id=str(d.get("program_id", "")),
            status=str(d.get("status", "ok")),
            baseline_strategy=str(d.get("baseline_strategy", "baseline (-O0)")),
            selected_strategy=d.get("selected_strategy"),
            selected_comparison=sel_comp,
            selection_provenance=prov,
            strategy_comparisons=strat_comps,
            pareto_frontier=list(d.get("pareto_frontier", [])),
            overall_status=overall,
            family_comparisons=fam_comp,
            family_status=fam_st,
            pipeline_error=d.get("pipeline_error"),
        )


@dataclasses.dataclass
class HistoricalProgramComparison:
    """
    Comparison of a program's performance across two distinct benchmark runs.

    Fields
    ------
    program_id              : stable program identifier
    status                  : 'ok', 'missing_previous', 'missing_current',
                              'failed_previous', 'failed_current', 'source_mismatch',
                              'environment_incompatible'
    previous_run_id         : run ID of the historical/reference run
    current_run_id          : run ID of the current run
    source_sha256           : verified source hash (None if mismatched or missing)
    environment_compatible  : True if toolchain and platform matched
    metric_comparisons      : dict mapping metric_name -> MetricComparison (current vs previous)
    strategy_historical     : dict mapping strategy_name -> {metric_name: MetricComparison}
    overall_status          : OverallStatus across the tracked metrics
    notes                   : list of diagnostic notes or explanations
    """
    program_id: str
    status: str
    previous_run_id: Optional[str]
    current_run_id: Optional[str]
    source_sha256: Optional[str] = None
    environment_compatible: bool = True
    metric_comparisons: dict[str, MetricComparison] = dataclasses.field(default_factory=dict)
    strategy_historical: dict[str, dict[str, MetricComparison]] = dataclasses.field(default_factory=dict)
    overall_status: OverallStatus = OverallStatus.INCOMPARABLE
    notes: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "status": self.status,
            "previous_run_id": self.previous_run_id,
            "current_run_id": self.current_run_id,
            "source_sha256": self.source_sha256,
            "environment_compatible": self.environment_compatible,
            "metric_comparisons": {k: v.to_dict() for k, v in self.metric_comparisons.items()},
            "strategy_historical": {
                s: {m: comp.to_dict() for m, comp in m_dict.items()}
                for s, m_dict in self.strategy_historical.items()
            },
            "overall_status": self.overall_status.value if isinstance(self.overall_status, OverallStatus) else str(self.overall_status),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HistoricalProgramComparison":
        raw_overall = d.get("overall_status", OverallStatus.INCOMPARABLE.value)
        overall = OverallStatus(raw_overall) if raw_overall in OverallStatus._value2member_map_ else OverallStatus.INCOMPARABLE
        raw_metrics = d.get("metric_comparisons", {})
        metrics = {k: MetricComparison.from_dict(v) for k, v in raw_metrics.items()} if isinstance(raw_metrics, dict) else {}
        raw_strats = d.get("strategy_historical", {})
        strat_hist: dict[str, dict[str, MetricComparison]] = {}
        if isinstance(raw_strats, dict):
            for s, m_dict in raw_strats.items():
                if isinstance(m_dict, dict):
                    strat_hist[s] = {m: MetricComparison.from_dict(comp) for m, comp in m_dict.items()}

        return cls(
            program_id=str(d.get("program_id", "")),
            status=str(d.get("status", "ok")),
            previous_run_id=d.get("previous_run_id"),
            current_run_id=d.get("current_run_id"),
            source_sha256=d.get("source_sha256"),
            environment_compatible=bool(d.get("environment_compatible", True)),
            metric_comparisons=metrics,
            strategy_historical=strat_hist,
            overall_status=overall,
            notes=list(d.get("notes", [])),
        )


@dataclasses.dataclass
class HistoricalComparison:
    """
    Suite-level comparison between two benchmark runs.

    Fields
    ------
    previous_run_id : run ID of earlier run
    current_run_id  : run ID of later run
    programs        : dict mapping program_id -> HistoricalProgramComparison
    summary         : aggregate statistics (e.g., n_common, n_improved, n_regressed)
    """
    previous_run_id: str
    current_run_id: str
    programs: dict[str, HistoricalProgramComparison] = dataclasses.field(default_factory=dict)
    summary: dict[str, int] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_run_id": self.previous_run_id,
            "current_run_id": self.current_run_id,
            "programs": {k: v.to_dict() for k, v in self.programs.items()},
            "summary": dict(self.summary),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HistoricalComparison":
        raw_progs = d.get("programs", {})
        progs = {k: HistoricalProgramComparison.from_dict(v) for k, v in raw_progs.items()} if isinstance(raw_progs, dict) else {}
        return cls(
            previous_run_id=str(d.get("previous_run_id", "")),
            current_run_id=str(d.get("current_run_id", "")),
            programs=progs,
            summary=dict(d.get("summary", {})),
        )


@dataclasses.dataclass
class RegressionReport:
    """
    Top-level structured report capturing optimization regressions and comparisons.

    Fields
    ------
    schema_version        : REGRESSION_SCHEMA_VERSION ('week10.1.0')
    report_id             : unique identifier for this report
    created_at            : ISO-8601 timestamp
    suite_name            : descriptive name of the test suite
    thresholds            : dictionary of applied thresholds
    program_comparisons   : dict mapping program_id -> ProgramComparison
    historical_comparison : optional HistoricalComparison if comparing across runs
    summary               : aggregate counts (n_total, n_improved, n_regressed, n_mixed, n_unchanged, n_inconclusive)
    family_summary        : aggregate counts grouped by signal family (performance, size, security)
    metadata              : environment, platform, git commit, toolchain info, and derived notes
    """
    schema_version: str
    report_id: str
    created_at: str
    suite_name: str
    thresholds: dict[str, Any]
    program_comparisons: dict[str, ProgramComparison] = dataclasses.field(default_factory=dict)
    historical_comparison: Optional[HistoricalComparison] = None
    summary: dict[str, int] = dataclasses.field(default_factory=dict)
    family_summary: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "created_at": self.created_at,
            "suite_name": self.suite_name,
            "thresholds": dict(self.thresholds),
            "program_comparisons": {k: v.to_dict() for k, v in self.program_comparisons.items()},
            "historical_comparison": self.historical_comparison.to_dict() if self.historical_comparison else None,
            "summary": dict(self.summary),
            "family_summary": dict(self.family_summary),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RegressionReport":
        raw_progs = d.get("program_comparisons", {})
        progs = {k: ProgramComparison.from_dict(v) for k, v in raw_progs.items()} if isinstance(raw_progs, dict) else {}
        raw_hist = d.get("historical_comparison")
        hist = HistoricalComparison.from_dict(raw_hist) if isinstance(raw_hist, dict) else None
        return cls(
            schema_version=str(d.get("schema_version", REGRESSION_SCHEMA_VERSION)),
            report_id=str(d.get("report_id", "")),
            created_at=str(d.get("created_at", "")),
            suite_name=str(d.get("suite_name", "")),
            thresholds=dict(d.get("thresholds", {})),
            program_comparisons=progs,
            historical_comparison=hist,
            summary=dict(d.get("summary", {})),
            family_summary=dict(d.get("family_summary", {})),
            metadata=dict(d.get("metadata", {})),
        )

    def to_text_summary(self) -> str:
        """Render a readable textual summary of the regression report."""
        lines = [
            "=" * 78,
            f"TOACD OPTIMIZATION REGRESSION REPORT ({self.schema_version})",
            f"Report ID : {self.report_id}",
            f"Created   : {self.created_at}",
            f"Suite     : {self.suite_name}",
            "-" * 78,
            f"Summary: {self.summary.get('n_total', len(self.program_comparisons))} programs evaluated",
            f"  Improved    : {self.summary.get('n_improved', 0)}",
            f"  Regressed   : {self.summary.get('n_regressed', 0)}",
            f"  Mixed       : {self.summary.get('n_mixed', 0)}",
            f"  Unchanged   : {self.summary.get('n_unchanged', 0)}",
            f"  Inconclusive: {self.summary.get('n_inconclusive', 0)}",
            f"  Incomparable: {self.summary.get('n_incomparable', 0)}",
            "-" * 78,
            "Signal Family Interpretation Note:",
            "  - performance: execution_time, energy (derived), carbon (derived)",
            "  - size       : code_size",
            "  - security   : security sink metrics (where present)",
            "  Energy and carbon are derived from runtime; performance family",
            "  captures this single underlying physical dimension.",
            "-" * 78,
            f"{'Program':<24} {'Selected':<18} {'Status':<14} {'Exec Time':<12} {'Conf':<8}",
            "-" * 78,
        ]
        for pid, pcomp in sorted(self.program_comparisons.items()):
            sel = pcomp.selected_strategy or "(none/unavail)"
            status = pcomp.overall_status.value if isinstance(pcomp.overall_status, OverallStatus) else str(pcomp.overall_status)
            exec_diff = "N/A"
            conf = "N/A"
            if pcomp.selected_comparison and "execution_time" in pcomp.selected_comparison.metric_comparisons:
                mc = pcomp.selected_comparison.metric_comparisons["execution_time"]
                conf = mc.confidence
                if mc.percent_change is not None:
                    exec_diff = f"{mc.percent_change:+.1f}%"
            lines.append(f"{pid:<24} {sel:<18} {status:<14} {exec_diff:<12} {conf:<8}")
        lines.append("=" * 78)
        return "\n".join(lines)
