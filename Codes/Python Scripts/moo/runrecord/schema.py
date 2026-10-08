"""
moo/runrecord/schema.py — Canonical RunRecord data model for TOACD pipeline.

The RunRecord is the SINGLE authoritative record for one optimization/compilation run.
It captures every stage from source identity through downstream analysis results.

Design principles
-----------------
- Explicit status fields (RunStatus, MeasurementStatus) prevent silent zero-inflation.
- Partial runs are first-class citizens: missing stages get NOT_RUN, not fake zeros.
- Failed stages get FAILED status, not zero-valued measurements.
- Provenance is either proven (DQN, MOO, etc.) or explicitly UNKNOWN.
- RunRecord never modifies the production optimization decision.
- Agentic AI output is marked advisory_only=True in the schema.
- Adaptive learning output is marked advisory_only=True in the schema.
- Existing downstream schemas (ExperienceRecord, AgentContext, etc.) are projected
  from the RunRecord; they are NOT duplicated here.
- JSON-serializable via to_dict() / from_dict().
- Versioned schema for forward compatibility.

IMPORTANT: This module contains ONLY data models. No pipeline logic lives here.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import os
from enum import Enum
from typing import Any, Optional


RUNRECORD_SCHEMA_VERSION: str = "runrecord.1.0"
"""Version string embedded in every RunRecord."""

BASELINE_STRATEGY_LABEL: str = "baseline (-O0)"
"""Canonical label for the -O0 baseline configuration. Never changed."""


# ---------------------------------------------------------------------------
# Status enumerations
# ---------------------------------------------------------------------------

class RunStatus(str, Enum):
    """
    Lifecycle status of a stage in the RunRecord pipeline.

    OK          — stage completed and produced valid results
    UNKNOWN     — stage may have run but results are unavailable or unverifiable
    NOT_RUN     — stage was intentionally not executed in this run
    FAILED      — stage attempted but failed explicitly (error captured)
    """
    OK       = "OK"
    UNKNOWN  = "UNKNOWN"
    NOT_RUN  = "NOT_RUN"
    FAILED   = "FAILED"


class MeasurementStatus(str, Enum):
    """
    Status of one measurement outcome (baseline or optimized).

    OK              — measurement completed successfully with valid timing data
    FAILED_BUILD    — executable could not be built
    FAILED_RUN      — executable built but runtime measurement failed
    FAILED_TIMEOUT  — measurement timed out
    FAILED_CORRECTNESS — executable produced incorrect output
    NOT_RUN         — measurement was not attempted
    UNKNOWN         — measurement state cannot be determined
    """
    OK                   = "OK"
    FAILED_BUILD         = "FAILED_BUILD"
    FAILED_RUN           = "FAILED_RUN"
    FAILED_TIMEOUT       = "FAILED_TIMEOUT"
    FAILED_CORRECTNESS   = "FAILED_CORRECTNESS"
    NOT_RUN              = "NOT_RUN"
    UNKNOWN              = "UNKNOWN"


class SelectionProvenance(str, Enum):
    """
    Origin provenance of the selected optimization strategy.

    Only set to a specific value when the implementation can PROVE the origin.
    Never silently assume a provenance value.

    DQN_MOO     — DQN Q-value argmax filtered by MOO Pareto frontier (moo_aware)
    DQN_ARGMAX  — pure DQN Q-value argmax (no MOO frontier available)
    MOO_ONLY    — MOO-only selection (no AI Q-values)
    HEURISTIC   — rule-based heuristic selection
    MANUAL      — manually specified by user/caller
    FALLBACK    — emergency fallback (exception during primary selection)
    UNKNOWN     — provenance cannot be determined
    """
    DQN_MOO    = "DQN_MOO"
    DQN_ARGMAX = "DQN_ARGMAX"
    MOO_ONLY   = "MOO_ONLY"
    HEURISTIC  = "HEURISTIC"
    MANUAL     = "MANUAL"
    FALLBACK   = "FALLBACK"
    UNKNOWN    = "UNKNOWN"


# ---------------------------------------------------------------------------
# Measurement snapshot (one build+run result)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class MeasurementSnapshot:
    """
    Compact measurement record for one configuration (baseline or optimized).

    Deliberately avoids duplicating the full MeasurementResult schema.
    Only the canonical summary fields are captured here for RunRecord use.
    Full MeasurementResult is available via the source artifact.

    Fields
    ------
    strategy            — strategy label (e.g. "baseline (-O0)", "-O2")
    status              — MeasurementStatus
    error_detail        — human-readable error if status != OK
    median_s            — median execution time in seconds (None if not measured)
    code_size_bytes     — primary code size metric (None if not measured)
    energy_joules       — estimated energy (None if not measured/unavailable)
    carbon_grams        — estimated carbon (None if not measured/unavailable)
    timing_is_reliable  — True/False/None from measurement.py
    n_samples           — number of valid timing samples collected
    measurement_dict    — full serialized MeasurementResult dict for auditing
                          (stored by reference; NOT copied unless necessary)
    """
    strategy: str
    status: MeasurementStatus = MeasurementStatus.UNKNOWN
    error_detail: Optional[str] = None

    median_s: Optional[float] = None
    code_size_bytes: Optional[int] = None
    energy_joules: Optional[float] = None
    carbon_grams: Optional[float] = None
    timing_is_reliable: Optional[bool] = None
    n_samples: int = 0

    measurement_dict: Optional[dict] = None  # full MeasurementResult.to_dict()

    def is_ok(self) -> bool:
        """True iff status is OK (not FAILED, NOT_RUN, or UNKNOWN)."""
        return self.status == MeasurementStatus.OK

    def has_valid_timing(self) -> bool:
        """True iff status is OK and median_s is a positive finite number."""
        if self.status != MeasurementStatus.OK:
            return False
        return self.median_s is not None and self.median_s > 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status.value if isinstance(self.status, MeasurementStatus) else str(self.status),
            "error_detail": self.error_detail,
            "median_s": self.median_s,
            "code_size_bytes": self.code_size_bytes,
            "energy_joules": self.energy_joules,
            "carbon_grams": self.carbon_grams,
            "timing_is_reliable": self.timing_is_reliable,
            "n_samples": self.n_samples,
            # Full measurement_dict is included for auditing but may be large
            "measurement_dict": self.measurement_dict,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MeasurementSnapshot":
        raw_status = d.get("status", MeasurementStatus.UNKNOWN.value)
        try:
            status = MeasurementStatus(raw_status)
        except ValueError:
            status = MeasurementStatus.UNKNOWN
        return cls(
            strategy=str(d.get("strategy", "")),
            status=status,
            error_detail=d.get("error_detail"),
            median_s=d.get("median_s"),
            code_size_bytes=d.get("code_size_bytes"),
            energy_joules=d.get("energy_joules"),
            carbon_grams=d.get("carbon_grams"),
            timing_is_reliable=d.get("timing_is_reliable"),
            n_samples=int(d.get("n_samples", 0)),
            measurement_dict=d.get("measurement_dict"),
        )

    @classmethod
    def not_run(cls, strategy: str, reason: str = "") -> "MeasurementSnapshot":
        """Construct an explicit NOT_RUN snapshot. Never treated as zero."""
        return cls(
            strategy=strategy,
            status=MeasurementStatus.NOT_RUN,
            error_detail=reason or "Measurement was not run",
        )

    @classmethod
    def failed(cls, strategy: str, reason: str) -> "MeasurementSnapshot":
        """Construct an explicit FAILED snapshot. Never treated as zero."""
        return cls(
            strategy=strategy,
            status=MeasurementStatus.FAILED_RUN,
            error_detail=reason,
        )

    @classmethod
    def failed_build(cls, strategy: str, reason: str) -> "MeasurementSnapshot":
        """Construct an explicit FAILED_BUILD snapshot. Never treated as zero."""
        return cls(
            strategy=strategy,
            status=MeasurementStatus.FAILED_BUILD,
            error_detail=reason,
        )


# ---------------------------------------------------------------------------
# RunRecord — canonical pipeline record
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RunRecord:
    """
    Canonical, immutable-ish record of one optimization/compilation run.

    Represents the entire pipeline state for a single program at a single moment:
      source → profile → selection → trace → compile → benchmark → downstream

    The RunRecord is the ONLY authoritative source of truth for a completed run.

    Immutability
    ------------
    RunRecord is not enforced-immutable (frozen=False) to allow builder construction.
    However, once built and returned from RunRecordBuilder, it MUST NOT be mutated
    by downstream consumers. Downstream modules receive projections, not the record.

    Failure representation
    ----------------------
    Every field that can fail has a corresponding *_status field.
    When a stage fails:
      - status field = FAILED or NOT_RUN
      - data fields = None
      - error fields = human-readable description
    NEVER set a data field to 0 when the true value is "not measured" or "failed".

    Provenance
    ----------
    selection_provenance is one of SelectionProvenance enum values.
    It is ONLY set to a specific provenance when the builder can prove the origin.
    When provenance cannot be determined, it MUST be SelectionProvenance.UNKNOWN.

    Agentic / Adaptive Safety
    -------------------------
    agentic_result is advisory_only=True at the schema level.
    adaptive_experience_id is a link only — it does NOT change selected_strategy.
    Neither agentic nor adaptive results override or silently replace the selection.

    Security
    --------
    security_status = NOT_RUN unless the security analyzer actually ran.
    security_result = None unless the security analyzer returned a result.
    NEVER set security_status = OK without an actual analyzer result.
    """

    # --- Schema identity ---
    schema_version: str = RUNRECORD_SCHEMA_VERSION

    # --- Run identity ---
    run_id: str = ""              # unique run identifier (uuid4 or similar)
    created_at: str = ""          # ISO-8601 creation timestamp

    # --- Source identity ---
    source_path: Optional[str] = None     # absolute path to source file
    source_file: str = ""                  # basename of source file
    source_hash: Optional[str] = None     # SHA-256 of source file content
    source_language: str = "C"            # source language (always "C" for now)

    # --- Toolchain identity ---
    clang_version: Optional[str] = None
    opt_version: Optional[str] = None
    toolchain_ok: bool = False
    toolchain_notes: list[str] = dataclasses.field(default_factory=list)

    # --- IR / feature extraction ---
    ir_features: Optional[dict[str, float]] = None   # canonical 8 IR features
    ir_hash: Optional[str] = None                     # SHA-256 of unoptimized IR
    ir_path: Optional[str] = None                     # path to unoptimized IR

    # --- Program profile (Week 7/8) ---
    program_profile: Optional[dict] = None            # ProgramProfile.to_dict()
    profile_status: RunStatus = RunStatus.NOT_RUN

    # --- Optimization selection ---
    selected_strategy: Optional[str] = None           # selected optimization strategy
    selection_provenance: SelectionProvenance = SelectionProvenance.UNKNOWN
    selection_model_id: Optional[str] = None          # model identifier / checkpoint
    selection_model_version: Optional[str] = None     # version string
    q_value_selected: Optional[float] = None          # Q-value for selected strategy
    q_value_argmax: Optional[float] = None            # Q-value of pure argmax choice
    q_rank_full: list[tuple[str, float]] = dataclasses.field(default_factory=list)
    selection_status: RunStatus = RunStatus.NOT_RUN
    selection_error: Optional[str] = None

    # --- Decision trace / XAI ---
    decision_trace: Optional[dict] = None             # DecisionTrace.to_dict()
    decision_trace_id: Optional[str] = None           # linkage identifier
    xai_result: Optional[dict] = None                 # XAIResult.to_dict()
    trace_status: RunStatus = RunStatus.NOT_RUN

    # --- MOO information ---
    pareto_frontier: list[str] = dataclasses.field(default_factory=list)
    pareto_dominated: list[str] = dataclasses.field(default_factory=list)
    pareto_invalid: list[str] = dataclasses.field(default_factory=list)
    objectives_used: list[str] = dataclasses.field(default_factory=list)
    moo_active: bool = False
    moo_status: RunStatus = RunStatus.NOT_RUN

    # --- Baseline measurements (always -O0) ---
    baseline_config: str = BASELINE_STRATEGY_LABEL
    baseline_measurement: Optional[MeasurementSnapshot] = None
    baseline_status: MeasurementStatus = MeasurementStatus.NOT_RUN

    # --- Optimized measurements ---
    optimized_measurement: Optional[MeasurementSnapshot] = None
    optimized_status: MeasurementStatus = MeasurementStatus.NOT_RUN

    # --- Benchmark overall status ---
    benchmark_status: RunStatus = RunStatus.NOT_RUN
    benchmark_error: Optional[str] = None

    # --- Regression / comparison (Week 10) ---
    regression_comparison: Optional[dict] = None      # ProgramComparison.to_dict()
    regression_overall_status: Optional[str] = None   # OverallStatus string
    regression_status: RunStatus = RunStatus.NOT_RUN

    # --- Adaptive learning linkage (Week 11) ---
    adaptive_experience_id: Optional[str] = None      # ExperienceRecord.experience_id
    adaptive_reward: Optional[float] = None           # computed reward (advisory)
    adaptive_status: RunStatus = RunStatus.NOT_RUN
    # SAFETY: adaptive learning is ADVISORY ONLY — never overrides selected_strategy
    adaptive_is_advisory_only: bool = True

    # --- Agentic AI analysis (Week 12) ---
    agentic_report: Optional[dict] = None             # AgentAnalysisReport.to_dict()
    agentic_verdict: Optional[str] = None             # AgentVerdict string
    agentic_status: RunStatus = RunStatus.NOT_RUN
    # SAFETY: agentic analysis is ADVISORY ONLY — never overrides selected_strategy
    agentic_is_advisory_only: bool = True

    # --- Security analysis ---
    security_result: Optional[dict] = None            # CandidateSecurity.to_dict()
    security_verdict: Optional[str] = None            # CandidateVerdict string
    security_status: RunStatus = RunStatus.NOT_RUN
    # SAFETY: security_status = NOT_RUN unless the security analyzer actually ran.
    # NEVER fabricate a positive security result.

    # --- Week 13 Security Additions ---
    security_gate: Optional[dict] = None              # GateResult.to_dict()
    agentic_security: Optional[dict] = None           # Agentic security assessment summary
    security_events: list[dict] = dataclasses.field(default_factory=list)  # list of SecurityEvent.to_dict()

    # --- Effective strategy provenance (Week 14) ---
    # selected_strategy is ALWAYS the original AI/MOO selection;
    # effective_strategy is what was actually (or would be) benchmarked after the security gate.
    effective_strategy: Optional[str] = None
    fallback_occurred: bool = False

    # --- Overall run summary ---
    overall_status: RunStatus = RunStatus.UNKNOWN
    run_notes: list[str] = dataclasses.field(default_factory=list)

    # ----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict. All enum values become strings."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_path": self.source_path,
            "source_file": self.source_file,
            "source_hash": self.source_hash,
            "source_language": self.source_language,
            "clang_version": self.clang_version,
            "opt_version": self.opt_version,
            "toolchain_ok": self.toolchain_ok,
            "toolchain_notes": list(self.toolchain_notes),
            "ir_features": dict(self.ir_features) if self.ir_features else None,
            "ir_hash": self.ir_hash,
            "ir_path": self.ir_path,
            "program_profile": dict(self.program_profile) if self.program_profile else None,
            "profile_status": self.profile_status.value,
            "selected_strategy": self.selected_strategy,
            "selection_provenance": self.selection_provenance.value,
            "selection_model_id": self.selection_model_id,
            "selection_model_version": self.selection_model_version,
            "q_value_selected": self.q_value_selected,
            "q_value_argmax": self.q_value_argmax,
            "q_rank_full": [list(pair) for pair in self.q_rank_full],
            "selection_status": self.selection_status.value,
            "selection_error": self.selection_error,
            "decision_trace": self.decision_trace,
            "decision_trace_id": self.decision_trace_id,
            "xai_result": self.xai_result,
            "trace_status": self.trace_status.value,
            "pareto_frontier": list(self.pareto_frontier),
            "pareto_dominated": list(self.pareto_dominated),
            "pareto_invalid": list(self.pareto_invalid),
            "objectives_used": list(self.objectives_used),
            "moo_active": self.moo_active,
            "moo_status": self.moo_status.value,
            "baseline_config": self.baseline_config,
            "baseline_measurement": self.baseline_measurement.to_dict() if self.baseline_measurement else None,
            "baseline_status": self.baseline_status.value,
            "optimized_measurement": self.optimized_measurement.to_dict() if self.optimized_measurement else None,
            "optimized_status": self.optimized_status.value,
            "benchmark_status": self.benchmark_status.value,
            "benchmark_error": self.benchmark_error,
            "regression_comparison": self.regression_comparison,
            "regression_overall_status": self.regression_overall_status,
            "regression_status": self.regression_status.value,
            "adaptive_experience_id": self.adaptive_experience_id,
            "adaptive_reward": self.adaptive_reward,
            "adaptive_status": self.adaptive_status.value,
            "adaptive_is_advisory_only": True,  # ALWAYS True
            "agentic_report": self.agentic_report,
            "agentic_verdict": self.agentic_verdict,
            "agentic_status": self.agentic_status.value,
            "agentic_is_advisory_only": True,  # ALWAYS True
            "security_result": self.security_result,
            "security_verdict": self.security_verdict,
            "security_status": self.security_status.value,
            "security_gate": self.security_gate,
            "agentic_security": self.agentic_security,
            "security_events": list(self.security_events),
            "effective_strategy": self.effective_strategy,
            "fallback_occurred": self.fallback_occurred,
            "overall_status": self.overall_status.value,
            "run_notes": list(self.run_notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunRecord":
        """Reconstruct from a JSON-deserialized dict. Safe defaults for missing fields."""
        def _rs(key: str, default: RunStatus = RunStatus.UNKNOWN) -> RunStatus:
            val = d.get(key)
            if val is None:
                return default
            try:
                return RunStatus(val)
            except ValueError:
                return default

        def _ms(key: str, default: MeasurementStatus = MeasurementStatus.UNKNOWN) -> MeasurementStatus:
            val = d.get(key)
            if val is None:
                return default
            try:
                return MeasurementStatus(val)
            except ValueError:
                return default

        def _sp(key: str) -> SelectionProvenance:
            val = d.get(key)
            if val is None:
                return SelectionProvenance.UNKNOWN
            try:
                return SelectionProvenance(val)
            except ValueError:
                return SelectionProvenance.UNKNOWN

        raw_base = d.get("baseline_measurement")
        raw_opt = d.get("optimized_measurement")

        return cls(
            schema_version=str(d.get("schema_version", RUNRECORD_SCHEMA_VERSION)),
            run_id=str(d.get("run_id", "")),
            created_at=str(d.get("created_at", "")),
            source_path=d.get("source_path"),
            source_file=str(d.get("source_file", "")),
            source_hash=d.get("source_hash"),
            source_language=str(d.get("source_language", "C")),
            clang_version=d.get("clang_version"),
            opt_version=d.get("opt_version"),
            toolchain_ok=bool(d.get("toolchain_ok", False)),
            toolchain_notes=list(d.get("toolchain_notes") or []),
            ir_features=d.get("ir_features"),
            ir_hash=d.get("ir_hash"),
            ir_path=d.get("ir_path"),
            program_profile=d.get("program_profile"),
            profile_status=_rs("profile_status", RunStatus.NOT_RUN),
            selected_strategy=d.get("selected_strategy"),
            selection_provenance=_sp("selection_provenance"),
            selection_model_id=d.get("selection_model_id"),
            selection_model_version=d.get("selection_model_version"),
            q_value_selected=d.get("q_value_selected"),
            q_value_argmax=d.get("q_value_argmax"),
            q_rank_full=[tuple(pair) for pair in d.get("q_rank_full", [])],
            selection_status=_rs("selection_status", RunStatus.NOT_RUN),
            selection_error=d.get("selection_error"),
            decision_trace=d.get("decision_trace"),
            decision_trace_id=d.get("decision_trace_id"),
            xai_result=d.get("xai_result"),
            trace_status=_rs("trace_status", RunStatus.NOT_RUN),
            pareto_frontier=list(d.get("pareto_frontier") or []),
            pareto_dominated=list(d.get("pareto_dominated") or []),
            pareto_invalid=list(d.get("pareto_invalid") or []),
            objectives_used=list(d.get("objectives_used") or []),
            moo_active=bool(d.get("moo_active", False)),
            moo_status=_rs("moo_status", RunStatus.NOT_RUN),
            baseline_config=str(d.get("baseline_config", BASELINE_STRATEGY_LABEL)),
            baseline_measurement=(
                MeasurementSnapshot.from_dict(raw_base) if isinstance(raw_base, dict) else None
            ),
            baseline_status=_ms("baseline_status", MeasurementStatus.NOT_RUN),
            optimized_measurement=(
                MeasurementSnapshot.from_dict(raw_opt) if isinstance(raw_opt, dict) else None
            ),
            optimized_status=_ms("optimized_status", MeasurementStatus.NOT_RUN),
            benchmark_status=_rs("benchmark_status", RunStatus.NOT_RUN),
            benchmark_error=d.get("benchmark_error"),
            regression_comparison=d.get("regression_comparison"),
            regression_overall_status=d.get("regression_overall_status"),
            regression_status=_rs("regression_status", RunStatus.NOT_RUN),
            adaptive_experience_id=d.get("adaptive_experience_id"),
            adaptive_reward=d.get("adaptive_reward"),
            adaptive_status=_rs("adaptive_status", RunStatus.NOT_RUN),
            adaptive_is_advisory_only=True,   # ALWAYS True
            agentic_report=d.get("agentic_report"),
            agentic_verdict=d.get("agentic_verdict"),
            agentic_status=_rs("agentic_status", RunStatus.NOT_RUN),
            agentic_is_advisory_only=True,    # ALWAYS True
            security_result=d.get("security_result"),
            security_verdict=d.get("security_verdict"),
            security_status=_rs("security_status", RunStatus.NOT_RUN),
            security_gate=d.get("security_gate"),
            agentic_security=d.get("agentic_security"),
            security_events=list(d.get("security_events") or []),
            effective_strategy=d.get("effective_strategy") or None,
            fallback_occurred=bool(d.get("fallback_occurred", False)),
            overall_status=_rs("overall_status", RunStatus.UNKNOWN),
            run_notes=list(d.get("run_notes") or []),
        )

    def compute_overall_status(self) -> RunStatus:
        """
        Derive an overall run status from component statuses.
        Does NOT modify self — returns a computed value.

        Heuristic:
          - If selection failed → FAILED
          - If benchmark failed → FAILED (but partial data may exist)
          - If selection OK and baseline OK → OK
          - Otherwise → UNKNOWN
        """
        if self.selection_status == RunStatus.FAILED:
            return RunStatus.FAILED
        if self.benchmark_status == RunStatus.FAILED:
            return RunStatus.FAILED
        if (self.selection_status == RunStatus.OK
                and self.baseline_status == MeasurementStatus.OK):
            return RunStatus.OK
        if self.selection_status == RunStatus.OK:
            return RunStatus.UNKNOWN
        return RunStatus.UNKNOWN
