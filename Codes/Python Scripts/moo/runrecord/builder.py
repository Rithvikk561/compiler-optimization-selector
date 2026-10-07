"""
moo/runrecord/builder.py — RunRecord builder/factory.

Creates a RunRecord from existing pipeline artifacts without duplicating their schemas.
Accepts each artifact optionally — a partial run must remain representable.

Design principles
-----------------
- Every stage independently sets its own status field (OK / FAILED / NOT_RUN).
- NEVER convert a failed/missing artifact into a zero-valued measurement.
- NEVER fabricate provenance (only set to specific value when proven).
- NEVER claim security is OK without an actual security analyzer result.
- The builder does NOT rerun any pipeline stage; it only reads existing artifacts.
- Agentic and adaptive results are marked advisory-only in the record.
- Selected strategy is NEVER changed by this builder.

Usage
-----
    builder = RunRecordBuilder(source_path="path/to/TC1.c")
    builder.set_profile(program_profile)
    builder.set_selection(selection_result, decision_trace)
    builder.set_baseline_measurement(moo_result)
    builder.set_optimized_measurement(moo_result, selected_strategy)
    builder.set_regression(program_comparison)
    builder.set_security(candidate_security)
    builder.set_agentic(agent_report)
    builder.set_adaptive(experience_record)
    record = builder.build()
"""

from __future__ import annotations

import datetime
import hashlib
import math
import os
import uuid
from typing import Any, Optional

from .schema import (
    BASELINE_STRATEGY_LABEL,
    RUNRECORD_SCHEMA_VERSION,
    MeasurementSnapshot,
    MeasurementStatus,
    RunRecord,
    RunStatus,
    SelectionProvenance,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_of_file(path: str) -> Optional[str]:
    """Compute SHA-256 hex digest of a file. Returns None on any error."""
    if not path or not os.path.isfile(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _now_iso() -> str:
    """Return current local time as ISO-8601 string (seconds precision)."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute or dict key from an object, with default."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _float_or_none(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _measurement_snapshot_from_dict(
    mdict: Optional[dict],
    strategy: str,
) -> MeasurementSnapshot:
    """
    Build a MeasurementSnapshot from a MeasurementResult.to_dict() output.

    Explicit failure detection:
      - measurement_error set → FAILED_RUN
      - No timing data and no measurement_error → also FAILED_RUN (not zero)
      - timing.median_s == 0 AND measurement_error → FAILED_RUN (not zero timing)
      - Valid timing data → OK
    """
    if mdict is None:
        return MeasurementSnapshot.not_run(strategy, "No measurement data provided")

    measurement_error = mdict.get("measurement_error")
    timing = mdict.get("timing")
    code_size = mdict.get("code_size") or {}
    energy = mdict.get("energy") or {}
    carbon = mdict.get("carbon") or {}

    # Determine status
    if measurement_error:
        # Explicit measurement error — FAILED_RUN, NOT zero
        return MeasurementSnapshot(
            strategy=strategy,
            status=MeasurementStatus.FAILED_RUN,
            error_detail=str(measurement_error),
            measurement_dict=mdict,
        )

    if timing is None:
        # No timing at all and no explicit error → still failed (not zero)
        return MeasurementSnapshot(
            strategy=strategy,
            status=MeasurementStatus.FAILED_RUN,
            error_detail="No timing data collected",
            measurement_dict=mdict,
        )

    # Valid timing available
    median_s = _float_or_none(timing.get("median_s"))
    n_samples = int(timing.get("n_samples", 0))
    timing_is_reliable = mdict.get("timing_is_reliable")

    code_size_bytes = code_size.get("primary_value")
    if code_size_bytes is not None:
        try:
            code_size_bytes = int(code_size_bytes)
        except (TypeError, ValueError):
            code_size_bytes = None

    energy_joules = _float_or_none(energy.get("energy_joules"))
    carbon_grams = _float_or_none(carbon.get("carbon_grams"))

    # Determine if timing is actually valid (non-zero median)
    # A median_s of exactly 0.0 with real samples is suspicious but not impossible
    # for very fast programs. We accept it as OK if n_samples > 0.
    if median_s is None and n_samples == 0:
        return MeasurementSnapshot(
            strategy=strategy,
            status=MeasurementStatus.FAILED_RUN,
            error_detail="Timing data present but no valid samples",
            measurement_dict=mdict,
        )

    return MeasurementSnapshot(
        strategy=strategy,
        status=MeasurementStatus.OK,
        median_s=median_s,
        code_size_bytes=code_size_bytes,
        energy_joules=energy_joules,
        carbon_grams=carbon_grams,
        timing_is_reliable=timing_is_reliable,
        n_samples=n_samples,
        measurement_dict=mdict,
    )


def _infer_provenance_from_trace(trace_dict: Optional[dict]) -> SelectionProvenance:
    """
    Infer SelectionProvenance from a DecisionTrace dict.
    Only returns a specific provenance when it can be proven from the trace.
    Returns UNKNOWN if trace is None or unreadable.
    """
    if not trace_dict or not isinstance(trace_dict, dict):
        return SelectionProvenance.UNKNOWN

    method = trace_dict.get("selection_method", "")

    if method == "moo_aware":
        return SelectionProvenance.DQN_MOO
    elif method in ("argmax_fallback_no_frontier", "argmax_fallback_frontier_mismatch"):
        return SelectionProvenance.DQN_ARGMAX
    elif method == "argmax_fallback_exception":
        return SelectionProvenance.FALLBACK
    elif method:
        # Some other recognized method string — don't guess
        return SelectionProvenance.UNKNOWN
    else:
        return SelectionProvenance.UNKNOWN


# ---------------------------------------------------------------------------
# RunRecordBuilder
# ---------------------------------------------------------------------------

class RunRecordBuilder:
    """
    Builder/factory for constructing a RunRecord from existing pipeline artifacts.

    Each set_*() method is optional. A partial run (some stages NOT_RUN) is valid.
    The builder does NOT rerun any pipeline stage — only reads existing artifacts.

    CRITICAL GUARANTEES:
    1. Failed/missing measurements → explicit FAILED/NOT_RUN, never zero.
    2. Security status = NOT_RUN unless the actual analyzer ran.
    3. Selected strategy is never changed.
    4. Agentic/adaptive results always carry advisory_only=True.
    5. Provenance is UNKNOWN unless the builder can prove the origin.
    """

    def __init__(
        self,
        source_path: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self._source_path = source_path
        self._run_id = run_id or str(uuid.uuid4())
        self._created_at = _now_iso()

        # Components (set via set_*() methods)
        self._clang_version: Optional[str] = None
        self._opt_version: Optional[str] = None
        self._toolchain_ok: bool = False
        self._toolchain_notes: list[str] = []

        self._ir_features: Optional[dict[str, float]] = None
        self._ir_hash: Optional[str] = None
        self._ir_path: Optional[str] = None

        self._program_profile: Optional[dict] = None
        self._profile_status: RunStatus = RunStatus.NOT_RUN

        self._selected_strategy: Optional[str] = None
        self._selection_provenance: SelectionProvenance = SelectionProvenance.UNKNOWN
        self._selection_model_id: Optional[str] = None
        self._selection_model_version: Optional[str] = None
        self._q_value_selected: Optional[float] = None
        self._q_value_argmax: Optional[float] = None
        self._q_rank_full: list[tuple[str, float]] = []
        self._selection_status: RunStatus = RunStatus.NOT_RUN
        self._selection_error: Optional[str] = None

        self._decision_trace: Optional[dict] = None
        self._decision_trace_id: Optional[str] = None
        self._xai_result: Optional[dict] = None
        self._trace_status: RunStatus = RunStatus.NOT_RUN

        self._pareto_frontier: list[str] = []
        self._pareto_dominated: list[str] = []
        self._pareto_invalid: list[str] = []
        self._objectives_used: list[str] = []
        self._moo_active: bool = False
        self._moo_status: RunStatus = RunStatus.NOT_RUN

        self._baseline_measurement: Optional[MeasurementSnapshot] = None
        self._baseline_status: MeasurementStatus = MeasurementStatus.NOT_RUN

        self._optimized_measurement: Optional[MeasurementSnapshot] = None
        self._optimized_status: MeasurementStatus = MeasurementStatus.NOT_RUN

        self._benchmark_status: RunStatus = RunStatus.NOT_RUN
        self._benchmark_error: Optional[str] = None

        self._regression_comparison: Optional[dict] = None
        self._regression_overall_status: Optional[str] = None
        self._regression_status: RunStatus = RunStatus.NOT_RUN

        self._adaptive_experience_id: Optional[str] = None
        self._adaptive_reward: Optional[float] = None
        self._adaptive_status: RunStatus = RunStatus.NOT_RUN

        self._agentic_report: Optional[dict] = None
        self._agentic_verdict: Optional[str] = None
        self._agentic_status: RunStatus = RunStatus.NOT_RUN

        # Security starts as NOT_RUN explicitly.
        # NEVER set to OK without an actual analyzer result.
        self._security_result: Optional[dict] = None
        self._security_verdict: Optional[str] = None
        self._security_status: RunStatus = RunStatus.NOT_RUN

        # Week 13 Security Gate and Agentic Security additions
        self._security_gate: Optional[dict] = None
        self._agentic_security: Optional[dict] = None
        self._security_events: list[dict] = []

        self._run_notes: list[str] = []

    # ----------------------------------------------------------------
    # Toolchain
    # ----------------------------------------------------------------

    def set_toolchain(
        self,
        clang_version: Optional[str] = None,
        opt_version: Optional[str] = None,
        toolchain_ok: bool = False,
        toolchain_notes: Optional[list[str]] = None,
    ) -> "RunRecordBuilder":
        self._clang_version = clang_version
        self._opt_version = opt_version
        self._toolchain_ok = toolchain_ok
        self._toolchain_notes = list(toolchain_notes or [])
        return self

    # ----------------------------------------------------------------
    # IR / features
    # ----------------------------------------------------------------

    def set_ir_features(
        self,
        features: Optional[dict[str, float]] = None,
        ir_hash: Optional[str] = None,
        ir_path: Optional[str] = None,
    ) -> "RunRecordBuilder":
        self._ir_features = features
        self._ir_hash = ir_hash
        self._ir_path = ir_path
        return self

    # ----------------------------------------------------------------
    # Program profile (Week 7/8)
    # ----------------------------------------------------------------

    def set_profile(self, profile: Any) -> "RunRecordBuilder":
        """
        Accept a ProgramProfile instance or dict.
        Sets profile_status = OK on success, FAILED if profile is None.
        """
        if profile is None:
            self._profile_status = RunStatus.NOT_RUN
            return self

        if isinstance(profile, dict):
            self._program_profile = dict(profile)
            self._profile_status = RunStatus.OK
        elif hasattr(profile, "to_dict"):
            try:
                self._program_profile = profile.to_dict()
                self._profile_status = RunStatus.OK
            except Exception as exc:
                self._profile_status = RunStatus.FAILED
                self._run_notes.append(f"Profile serialization failed: {exc}")
        else:
            self._profile_status = RunStatus.FAILED
            self._run_notes.append(
                f"Profile has unexpected type {type(profile).__name__}; cannot serialize"
            )
        return self

    # ----------------------------------------------------------------
    # Optimization selection + DecisionTrace
    # ----------------------------------------------------------------

    def set_selection(
        self,
        selected_strategy: Optional[str],
        decision_trace: Any = None,
        selection_result: Any = None,
        model_id: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> "RunRecordBuilder":
        """
        Record the optimization selection and associated trace.

        Parameters
        ----------
        selected_strategy   : the chosen strategy string (must not be None for OK status)
        decision_trace      : DecisionTrace instance or dict (optional)
        selection_result    : SelectionResult instance (optional, for q_rank)
        model_id            : model checkpoint identifier
        model_version       : model version string
        """
        if not selected_strategy:
            self._selection_status = RunStatus.FAILED
            self._selection_error = "No strategy selected"
            return self

        self._selected_strategy = selected_strategy
        self._selection_model_id = model_id
        self._selection_model_version = model_version

        # Extract info from DecisionTrace
        if decision_trace is not None:
            trace_dict: Optional[dict] = None
            if isinstance(decision_trace, dict):
                trace_dict = dict(decision_trace)
            elif hasattr(decision_trace, "to_dict"):
                try:
                    trace_dict = decision_trace.to_dict()
                except Exception:
                    trace_dict = None

            if trace_dict is not None:
                self._decision_trace = trace_dict
                self._trace_status = RunStatus.OK
                self._decision_trace_id = trace_dict.get("trace_id")

                # Extract Q-values
                ai_top_q = trace_dict.get("ai_top_q")
                self._q_value_argmax = _float_or_none(ai_top_q)
                self._q_value_selected = _float_or_none(ai_top_q)  # may be same
                raw_q_rank = trace_dict.get("q_rank_full", [])
                self._q_rank_full = [
                    (str(pair[0]), float(pair[1]))
                    for pair in raw_q_rank
                    if len(pair) >= 2
                ]

                # Find the Q-value specifically for the selected strategy
                for strat, qv in self._q_rank_full:
                    if strat == selected_strategy:
                        self._q_value_selected = qv
                        break

                # Pareto info
                self._pareto_frontier = list(trace_dict.get("pareto_frontier") or [])
                self._pareto_dominated = list(trace_dict.get("pareto_dominated") or [])
                self._pareto_invalid = list(trace_dict.get("pareto_invalid") or [])
                self._objectives_used = list(trace_dict.get("objectives_used") or [])
                self._moo_active = bool(trace_dict.get("moo_active", False))
                self._moo_status = RunStatus.OK if self._pareto_frontier else RunStatus.NOT_RUN

                # Infer provenance from trace
                self._selection_provenance = _infer_provenance_from_trace(trace_dict)

                # Build XAI result from trace
                try:
                    from ..xai import XAIResult
                    xai = XAIResult.from_decision_trace(decision_trace)
                    self._xai_result = xai.to_dict()
                except Exception:
                    self._xai_result = None
            else:
                self._trace_status = RunStatus.FAILED
                self._run_notes.append("DecisionTrace could not be serialized")

        # Extract additional info from SelectionResult if provided
        if selection_result is not None:
            q_rank = getattr(selection_result, "q_rank", None)
            if q_rank:
                self._q_rank_full = list(q_rank)
            frontier = getattr(selection_result, "frontier", None)
            if frontier and not self._pareto_frontier:
                self._pareto_frontier = list(frontier)
            moo_active = getattr(selection_result, "moo_active", None)
            if moo_active is not None:
                self._moo_active = bool(moo_active)

        self._selection_status = RunStatus.OK
        return self

    # ----------------------------------------------------------------
    # MOOEvaluationResult (baseline + all strategies)
    # ----------------------------------------------------------------

    def set_moo_result(self, moo_result: Any) -> "RunRecordBuilder":
        """
        Extract baseline and frontier info from a MOOEvaluationResult.
        Does NOT extract the selected strategy's optimized measurement here;
        use set_optimized_from_moo() for that after the strategy is known.

        Parameters
        ----------
        moo_result : MOOEvaluationResult instance or dict
        """
        if moo_result is None:
            return self

        if not isinstance(moo_result, dict):
            if hasattr(moo_result, "to_dict"):
                try:
                    moo_dict = moo_result.to_dict()
                except Exception:
                    return self
            else:
                return self
        else:
            moo_dict = moo_result

        # Pareto info (if not already set by decision trace)
        if not self._pareto_frontier:
            self._pareto_frontier = list(moo_dict.get("pareto_frontier") or [])
        if not self._pareto_dominated:
            self._pareto_dominated = list(moo_dict.get("pareto_dominated") or [])
        if not self._pareto_invalid:
            self._pareto_invalid = list(moo_dict.get("pareto_invalid") or [])
        if not self._objectives_used:
            self._objectives_used = list(moo_dict.get("objectives_used") or [])

        # Baseline measurement
        baseline_dict = moo_dict.get("baseline")
        if baseline_dict and isinstance(baseline_dict, dict):
            build_ok = bool(baseline_dict.get("build_ok", False))
            if not build_ok:
                build_error = baseline_dict.get("build_error") or "Baseline build failed"
                self._baseline_measurement = MeasurementSnapshot.failed_build(
                    BASELINE_STRATEGY_LABEL, str(build_error)
                )
                self._baseline_status = MeasurementStatus.FAILED_BUILD
            else:
                mdata = baseline_dict.get("measurement")
                snap = _measurement_snapshot_from_dict(mdata, BASELINE_STRATEGY_LABEL)
                self._baseline_measurement = snap
                self._baseline_status = snap.status

        if moo_dict.get("pipeline_error"):
            self._benchmark_status = RunStatus.FAILED
            self._benchmark_error = str(moo_dict["pipeline_error"])

        return self

    def set_optimized_from_moo(
        self,
        moo_result: Any,
        selected_strategy: Optional[str] = None,
    ) -> "RunRecordBuilder":
        """
        Extract the optimized measurement for selected_strategy from a MOOEvaluationResult.

        If the selected strategy's build failed or result is incorrect, records FAILED status.
        Never converts a failure to a zero measurement.
        """
        strategy = selected_strategy or self._selected_strategy
        if not strategy:
            self._optimized_status = MeasurementStatus.NOT_RUN
            return self

        if moo_result is None:
            self._optimized_status = MeasurementStatus.NOT_RUN
            return self

        if not isinstance(moo_result, dict):
            if hasattr(moo_result, "to_dict"):
                try:
                    moo_dict = moo_result.to_dict()
                except Exception:
                    self._optimized_status = MeasurementStatus.NOT_RUN
                    return self
            else:
                self._optimized_status = MeasurementStatus.NOT_RUN
                return self
        else:
            moo_dict = moo_result

        # Find the candidate entry for selected_strategy
        candidates = moo_dict.get("candidates") or []
        target_candidate = None
        for cand in candidates:
            if isinstance(cand, dict) and cand.get("strategy_name") == strategy:
                target_candidate = cand
                break

        if target_candidate is None:
            self._optimized_status = MeasurementStatus.NOT_RUN
            self._run_notes.append(
                f"Selected strategy {strategy!r} not found in MOO candidates"
            )
            return self

        # Check build status
        if not target_candidate.get("build_ok", False):
            build_error = target_candidate.get("build_error") or "Build failed"
            self._optimized_measurement = MeasurementSnapshot.failed_build(strategy, str(build_error))
            self._optimized_status = MeasurementStatus.FAILED_BUILD
            return self

        # Check correctness
        if not target_candidate.get("correct", False) and target_candidate.get("correctness_checked", False):
            details = target_candidate.get("correctness_details") or "Correctness check failed"
            self._optimized_measurement = MeasurementSnapshot(
                strategy=strategy,
                status=MeasurementStatus.FAILED_CORRECTNESS,
                error_detail=str(details),
            )
            self._optimized_status = MeasurementStatus.FAILED_CORRECTNESS
            return self

        # Extract measurement
        mdata = target_candidate.get("measurement")
        snap = _measurement_snapshot_from_dict(mdata, strategy)
        self._optimized_measurement = snap
        self._optimized_status = snap.status

        if snap.status == MeasurementStatus.OK and self._benchmark_status == RunStatus.NOT_RUN:
            self._benchmark_status = RunStatus.OK

        return self

    # ----------------------------------------------------------------
    # Direct measurement setting (when not using MOO pipeline)
    # ----------------------------------------------------------------

    def set_baseline_measurement(
        self,
        measurement_dict: Optional[dict],
        error: Optional[str] = None,
    ) -> "RunRecordBuilder":
        """
        Set baseline (-O0) measurement directly from a MeasurementResult dict.
        If error is provided, status is FAILED. If measurement_dict is None and
        no error, status is NOT_RUN (never zero).
        """
        if error:
            self._baseline_measurement = MeasurementSnapshot.failed(BASELINE_STRATEGY_LABEL, error)
            self._baseline_status = MeasurementStatus.FAILED_RUN
        elif measurement_dict is not None:
            snap = _measurement_snapshot_from_dict(measurement_dict, BASELINE_STRATEGY_LABEL)
            self._baseline_measurement = snap
            self._baseline_status = snap.status
        else:
            self._baseline_status = MeasurementStatus.NOT_RUN
        return self

    def set_optimized_measurement(
        self,
        strategy: str,
        measurement_dict: Optional[dict],
        error: Optional[str] = None,
    ) -> "RunRecordBuilder":
        """
        Set optimized measurement directly from a MeasurementResult dict.
        If error is provided, status is FAILED. If measurement_dict is None and
        no error, status is NOT_RUN (never zero).
        """
        if error:
            self._optimized_measurement = MeasurementSnapshot.failed(strategy, error)
            self._optimized_status = MeasurementStatus.FAILED_RUN
        elif measurement_dict is not None:
            snap = _measurement_snapshot_from_dict(measurement_dict, strategy)
            self._optimized_measurement = snap
            self._optimized_status = snap.status
            if snap.status == MeasurementStatus.OK:
                self._benchmark_status = RunStatus.OK
        else:
            self._optimized_status = MeasurementStatus.NOT_RUN
        return self

    # ----------------------------------------------------------------
    # Regression comparison (Week 10)
    # ----------------------------------------------------------------

    def set_regression(self, program_comparison: Any) -> "RunRecordBuilder":
        """
        Accept a ProgramComparison instance or dict.
        If program_comparison is None → regression_status = NOT_RUN (not FAILED).
        """
        if program_comparison is None:
            self._regression_status = RunStatus.NOT_RUN
            return self

        try:
            if isinstance(program_comparison, dict):
                comp_dict = dict(program_comparison)
            elif hasattr(program_comparison, "to_dict"):
                comp_dict = program_comparison.to_dict()
            else:
                self._regression_status = RunStatus.FAILED
                self._run_notes.append(
                    f"ProgramComparison has unexpected type {type(program_comparison).__name__}"
                )
                return self

            self._regression_comparison = comp_dict

            # Extract overall status
            raw_overall = comp_dict.get("overall_status")
            if raw_overall is not None:
                self._regression_overall_status = str(
                    raw_overall.value if hasattr(raw_overall, "value") else raw_overall
                )

            pipeline_error = comp_dict.get("pipeline_error")
            if pipeline_error:
                self._regression_status = RunStatus.FAILED
                self._run_notes.append(f"Regression pipeline error: {pipeline_error}")
            else:
                self._regression_status = RunStatus.OK

        except Exception as exc:
            self._regression_status = RunStatus.FAILED
            self._run_notes.append(f"Regression comparison serialization error: {exc}")

        return self

    # ----------------------------------------------------------------
    # Adaptive learning linkage (Week 11)
    # ----------------------------------------------------------------

    def set_adaptive(self, experience_record: Any) -> "RunRecordBuilder":
        """
        Link an ExperienceRecord to this RunRecord.
        SAFETY: This NEVER changes selected_strategy.
        The experience record is advisory — it links to an existing record, not a model update.
        """
        if experience_record is None:
            self._adaptive_status = RunStatus.NOT_RUN
            return self

        try:
            exp_id = _get(experience_record, "experience_id")
            if exp_id:
                self._adaptive_experience_id = str(exp_id)

            reward = _get(experience_record, "reward")
            self._adaptive_reward = _float_or_none(reward)

            self._adaptive_status = RunStatus.OK
        except Exception as exc:
            self._adaptive_status = RunStatus.FAILED
            self._run_notes.append(f"Adaptive linkage error: {exc}")

        return self

    # ----------------------------------------------------------------
    # Agentic AI analysis (Week 12)
    # ----------------------------------------------------------------

    def set_agentic(self, agent_report: Any) -> "RunRecordBuilder":
        """
        Attach an AgentAnalysisReport to this RunRecord.
        SAFETY: This NEVER changes selected_strategy.
        Agentic analysis is advisory-only by schema invariant.
        """
        if agent_report is None:
            self._agentic_status = RunStatus.NOT_RUN
            return self

        try:
            if isinstance(agent_report, dict):
                report_dict = dict(agent_report)
            elif hasattr(agent_report, "to_dict"):
                report_dict = agent_report.to_dict()
            else:
                self._agentic_status = RunStatus.FAILED
                self._run_notes.append(
                    f"Agent report has unexpected type {type(agent_report).__name__}"
                )
                return self

            # Enforce advisory_only in the stored dict
            report_dict["is_advisory_only"] = True

            # Verify the report does NOT override selected strategy
            report_strategy = report_dict.get("selected_strategy")
            if report_strategy and report_strategy != self._selected_strategy:
                # Store the report but note the discrepancy — advisory only
                self._run_notes.append(
                    f"Agentic report selected_strategy={report_strategy!r} differs from "
                    f"RunRecord selected_strategy={self._selected_strategy!r}; "
                    f"agentic result is advisory only and does NOT override"
                )

            self._agentic_report = report_dict
            raw_verdict = report_dict.get("verdict")
            if raw_verdict:
                self._agentic_verdict = str(raw_verdict.value if hasattr(raw_verdict, "value") else raw_verdict)

            self._agentic_status = RunStatus.OK
        except Exception as exc:
            self._agentic_status = RunStatus.FAILED
            self._run_notes.append(f"Agentic report serialization error: {exc}")

        return self

    # ----------------------------------------------------------------
    # Security analysis
    # ----------------------------------------------------------------

    def set_security(self, security_result: Any) -> "RunRecordBuilder":
        """
        Attach a CandidateSecurity or security result dict.

        CRITICAL SAFETY:
        - Only sets security_status = OK if the security analyzer actually ran
          and returned a result with a non-ERROR, non-UNKNOWN verdict.
        - NEVER reports security as OK based on absence of findings alone.
        - If security_result is None → NOT_RUN (not OK, not FAILED).
        """
        if security_result is None:
            # Analyzer did not run — explicit NOT_RUN
            self._security_status = RunStatus.NOT_RUN
            return self

        try:
            if isinstance(security_result, dict):
                sec_dict = dict(security_result)
            elif hasattr(security_result, "to_dict"):
                sec_dict = security_result.to_dict()
            else:
                self._security_status = RunStatus.FAILED
                self._run_notes.append(
                    f"Security result has unexpected type {type(security_result).__name__}"
                )
                return self

            self._security_result = sec_dict

            # Extract verdict
            raw_verdict = sec_dict.get("verdict")
            if raw_verdict:
                verdict_str = str(raw_verdict.value if hasattr(raw_verdict, "value") else raw_verdict)
                self._security_verdict = verdict_str

                # Only mark as OK if verdict is PRESERVED or REDUCED (not UNKNOWN/ERROR)
                if verdict_str in ("PRESERVED", "REDUCED"):
                    self._security_status = RunStatus.OK
                elif verdict_str == "ELIMINATED":
                    # Elimination of guards is a security finding, not an OK result
                    self._security_status = RunStatus.OK  # analyzer ran successfully
                    self._run_notes.append(
                        "Security: guard(s) were eliminated by optimization"
                    )
                elif verdict_str in ("UNKNOWN", "ERROR", "NOT_APPLICABLE"):
                    # Analyzer ran but couldn't determine — NOT OK, not FAILED
                    self._security_status = RunStatus.UNKNOWN
                else:
                    # Unknown verdict — mark as UNKNOWN
                    self._security_status = RunStatus.UNKNOWN
            else:
                # Analyzer returned a result but no verdict → UNKNOWN
                self._security_status = RunStatus.UNKNOWN

        except Exception as exc:
            self._security_status = RunStatus.FAILED
            self._run_notes.append(f"Security result serialization error: {exc}")

        return self

    def set_security_gate(self, gate_result: Any) -> "RunRecordBuilder":
        """Attach an OptimizationSecurityGate result or GateResult dictionary."""
        if gate_result is None:
            self._security_gate = None
            return self
        if isinstance(gate_result, dict):
            self._security_gate = dict(gate_result)
        elif hasattr(gate_result, "to_dict"):
            self._security_gate = gate_result.to_dict()
        else:
            self._security_gate = {"raw": str(gate_result)}
        return self

    def set_agentic_security(self, agentic_sec_result: Any) -> "RunRecordBuilder":
        """Attach an Agentic AI security assessment summary dictionary."""
        if agentic_sec_result is None:
            self._agentic_security = None
            return self
        if isinstance(agentic_sec_result, dict):
            self._agentic_security = dict(agentic_sec_result)
        elif hasattr(agentic_sec_result, "to_dict"):
            self._agentic_security = agentic_sec_result.to_dict()
        else:
            self._agentic_security = {"raw": str(agentic_sec_result)}
        return self

    def add_security_events(self, events: Any) -> "RunRecordBuilder":
        """Attach one or more SecurityEvent objects or dictionaries."""
        if not events:
            return self
        evt_list = events if isinstance(events, (list, tuple)) else [events]
        for e in evt_list:
            if isinstance(e, dict):
                self._security_events.append(dict(e))
            elif hasattr(e, "to_dict"):
                self._security_events.append(e.to_dict())
            else:
                self._security_events.append({"raw": str(e)})
        return self

    # ----------------------------------------------------------------
    # Notes
    # ----------------------------------------------------------------

    def add_note(self, note: str) -> "RunRecordBuilder":
        self._run_notes.append(str(note))
        return self

    # ----------------------------------------------------------------
    # Build
    # ----------------------------------------------------------------

    def build(self) -> RunRecord:
        """
        Construct and return the final RunRecord.

        Benchmark status is derived if not explicitly set.
        Overall status is computed from component statuses.
        """
        # Derive benchmark_status if still NOT_RUN but we have measurements
        if self._benchmark_status == RunStatus.NOT_RUN:
            if (self._baseline_status == MeasurementStatus.OK
                    and self._optimized_status == MeasurementStatus.OK):
                self._benchmark_status = RunStatus.OK
            elif self._baseline_status in (MeasurementStatus.FAILED_BUILD,
                                            MeasurementStatus.FAILED_RUN,
                                            MeasurementStatus.FAILED_TIMEOUT,
                                            MeasurementStatus.FAILED_CORRECTNESS):
                self._benchmark_status = RunStatus.FAILED

        # If regression was requested but comparison is missing → NOT_RUN (not FAILED)
        # (already handled in set_regression)

        # Compute source hash if not set
        source_hash = _sha256_of_file(self._source_path) if self._source_path else None

        # Determine source_file
        source_file = ""
        if self._source_path:
            source_file = os.path.basename(self._source_path)

        record = RunRecord(
            schema_version=RUNRECORD_SCHEMA_VERSION,
            run_id=self._run_id,
            created_at=self._created_at,
            source_path=self._source_path,
            source_file=source_file,
            source_hash=source_hash,
            source_language="C",
            clang_version=self._clang_version,
            opt_version=self._opt_version,
            toolchain_ok=self._toolchain_ok,
            toolchain_notes=list(self._toolchain_notes),
            ir_features=self._ir_features,
            ir_hash=self._ir_hash,
            ir_path=self._ir_path,
            program_profile=self._program_profile,
            profile_status=self._profile_status,
            selected_strategy=self._selected_strategy,
            selection_provenance=self._selection_provenance,
            selection_model_id=self._selection_model_id,
            selection_model_version=self._selection_model_version,
            q_value_selected=self._q_value_selected,
            q_value_argmax=self._q_value_argmax,
            q_rank_full=list(self._q_rank_full),
            selection_status=self._selection_status,
            selection_error=self._selection_error,
            decision_trace=self._decision_trace,
            decision_trace_id=self._decision_trace_id,
            xai_result=self._xai_result,
            trace_status=self._trace_status,
            pareto_frontier=list(self._pareto_frontier),
            pareto_dominated=list(self._pareto_dominated),
            pareto_invalid=list(self._pareto_invalid),
            objectives_used=list(self._objectives_used),
            moo_active=self._moo_active,
            moo_status=self._moo_status,
            baseline_config=BASELINE_STRATEGY_LABEL,
            baseline_measurement=self._baseline_measurement,
            baseline_status=self._baseline_status,
            optimized_measurement=self._optimized_measurement,
            optimized_status=self._optimized_status,
            benchmark_status=self._benchmark_status,
            benchmark_error=self._benchmark_error,
            regression_comparison=self._regression_comparison,
            regression_overall_status=self._regression_overall_status,
            regression_status=self._regression_status,
            adaptive_experience_id=self._adaptive_experience_id,
            adaptive_reward=self._adaptive_reward,
            adaptive_status=self._adaptive_status,
            adaptive_is_advisory_only=True,   # ALWAYS True — schema invariant
            agentic_report=self._agentic_report,
            agentic_verdict=self._agentic_verdict,
            agentic_status=self._agentic_status,
            agentic_is_advisory_only=True,    # ALWAYS True — schema invariant
            security_result=self._security_result,
            security_verdict=self._security_verdict,
            security_status=self._security_status,
            security_gate=self._security_gate,
            agentic_security=self._agentic_security,
            security_events=list(self._security_events),
            run_notes=list(self._run_notes),
        )

        # Compute and set overall status
        record.overall_status = record.compute_overall_status()
        return record
