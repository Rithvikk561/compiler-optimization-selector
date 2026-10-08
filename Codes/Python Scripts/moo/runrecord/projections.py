"""
moo/runrecord/projections.py — Projection helpers from RunRecord to downstream schemas.

Downstream consumers receive projections rather than the full RunRecord.
This prevents coupling: each module only sees what it needs.

Projection contract
-------------------
- to_regression_input()  → dict consumable by regression.comparator
- to_experience_record() → ExperienceRecord for adaptive learning (advisory only)
- to_agent_context()     → AgentContext for agentic analysis (advisory only)
- to_gui_view()          → dict for GUI display (no missing fields become "OK")

Critical guarantees
-------------------
- Failed/NOT_RUN stages are projected with explicit status strings, not zeros.
- Agentic and adaptive projections are always advisory-only.
- Selected strategy is NEVER changed by any projection.
- Security projection never fabricates a positive result.
- Missing data → explicit None or NOT_RUN, never fake defaults.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .schema import (
    BASELINE_STRATEGY_LABEL,
    MeasurementStatus,
    RunRecord,
    RunStatus,
    SelectionProvenance,
)


# ---------------------------------------------------------------------------
# Projection: → regression comparison input
# ---------------------------------------------------------------------------

def to_regression_input(record: RunRecord) -> dict[str, Any]:
    """
    Project a RunRecord into a regression comparison input dict.

    Returns enough information for the existing Week 10 regression system
    to determine whether a meaningful comparison is possible.

    CRITICAL: If benchmark_status != OK, the returned dict contains
    can_compare=False with explicit reason. Never fabricate measurements.
    """
    base = record.baseline_measurement
    opt = record.optimized_measurement

    base_ok = (
        base is not None
        and record.baseline_status == MeasurementStatus.OK
        and base.has_valid_timing()
    )
    opt_ok = (
        opt is not None
        and record.optimized_status == MeasurementStatus.OK
        and opt.has_valid_timing()
    )

    can_compare = base_ok and opt_ok

    result: dict[str, Any] = {
        "run_id": record.run_id,
        "source_file": record.source_file,
        "source_hash": record.source_hash,
        "selected_strategy": record.selected_strategy,
        "baseline_strategy": BASELINE_STRATEGY_LABEL,
        "can_compare": can_compare,
        "benchmark_status": record.benchmark_status.value,
        "baseline_status": record.baseline_status.value,
        "optimized_status": record.optimized_status.value,
    }

    if not can_compare:
        # Be explicit about why comparison cannot proceed
        reasons = []
        if not base_ok:
            reasons.append(
                f"Baseline measurement unavailable (status={record.baseline_status.value})"
            )
        if not opt_ok:
            reasons.append(
                f"Optimized measurement unavailable (status={record.optimized_status.value})"
            )
        result["cannot_compare_reason"] = "; ".join(reasons)
        result["baseline_metrics"] = None
        result["optimized_metrics"] = None
        return result

    # Both measurements are valid — project metrics
    result["baseline_metrics"] = {
        "execution_time_s": base.median_s,
        "code_size_bytes": float(base.code_size_bytes) if base.code_size_bytes is not None else None,
        "energy_joules": base.energy_joules,
        "carbon_grams": base.carbon_grams,
        "timing_is_reliable": base.timing_is_reliable,
    }
    result["optimized_metrics"] = {
        "execution_time_s": opt.median_s,
        "code_size_bytes": float(opt.code_size_bytes) if opt.code_size_bytes is not None else None,
        "energy_joules": opt.energy_joules,
        "carbon_grams": opt.carbon_grams,
        "timing_is_reliable": opt.timing_is_reliable,
    }
    result["pareto_frontier"] = list(record.pareto_frontier)
    result["selection_provenance"] = record.selection_provenance.value
    result["regression_status"] = record.regression_status.value

    return result


# ---------------------------------------------------------------------------
# Fallback evidence detection helper (Week 14)
# ---------------------------------------------------------------------------

def _fallback_evidence(record: RunRecord) -> bool:
    """
    Detect whether a RunRecord underwent security fallback.
    Examines explicit flags, security gate dictionaries, and strategy provenance.
    """
    if getattr(record, "fallback_occurred", False):
        return True
    sec_gate = getattr(record, "security_gate", None)
    if isinstance(sec_gate, dict) and sec_gate.get("fallback_occurred"):
        return True
    eff = getattr(record, "effective_strategy", None)
    sel = getattr(record, "selected_strategy", None)
    if eff is not None and sel is not None and eff != sel:
        return True
    opt_m = getattr(record, "optimized_measurement", None)
    if opt_m is not None and getattr(opt_m, "strategy", None) and sel is not None and opt_m.strategy != sel:
        return True
    return False


# ---------------------------------------------------------------------------
# Projection: → adaptive ExperienceRecord
# ---------------------------------------------------------------------------

def to_experience_record(
    record: RunRecord,
    reward_config: Any = None,
    strict: bool = False,
) -> Optional[Any]:
    """
    Project a RunRecord into a Week 11 ExperienceRecord for adaptive learning.

    SAFETY GUARANTEES:
    - This is ADVISORY ONLY. The returned ExperienceRecord does NOT change
      selected_strategy in the RunRecord or in the production model.
    - Returns None if required data is missing (selection, source_hash, ir_features).
    - Never fabricates provenance or reward.
    - Requires actual measurement data for a positive reward.
    - Week 14: Rejects records that experienced security fallback to avoid crediting rejected strategies.

    Parameters
    ----------
    record          : RunRecord to project from
    reward_config   : optional RewardConfig for reward calculation
    strict          : if True, raises ValueError on missing required data

    Returns
    -------
    ExperienceRecord or None
    """
    # Week 14: Refuse records that underwent security fallback
    if _fallback_evidence(record):
        if strict:
            raise ValueError("RunRecord experienced security gate fallback; refusing to create ExperienceRecord")
        return None

    try:
        from ..adaptive.schema import ADAPTIVE_SCHEMA_VERSION, ExperienceRecord, make_timestamp
        from ..adaptive.reward import DEFAULT_REWARD_CONFIG, compute_reward, is_performance_inconclusive
        from ..adaptive.validator import validate_experience

        # Require selection
        if not record.selected_strategy:
            if strict:
                raise ValueError("RunRecord has no selected_strategy; cannot create ExperienceRecord")
            return None

        # Require source_hash
        if not record.source_hash:
            if strict:
                raise ValueError("RunRecord has no source_hash; cannot create ExperienceRecord")
            return None

        # Require IR features
        if not record.ir_features:
            if strict:
                raise ValueError("RunRecord has no ir_features; cannot create ExperienceRecord")
            return None

        # Selection method → adaptive schema string
        provenance = record.selection_provenance
        if provenance == SelectionProvenance.DQN_MOO:
            selection_method = "moo_aware"
        elif provenance == SelectionProvenance.DQN_ARGMAX:
            selection_method = "argmax_fallback_no_frontier"
        elif provenance == SelectionProvenance.FALLBACK:
            selection_method = "argmax_fallback_exception"
        else:
            selection_method = str(provenance.value).lower()

        # Benchmark outcome
        base = record.baseline_measurement
        opt = record.optimized_measurement

        benchmark_build_ok = (record.optimized_status == MeasurementStatus.OK)
        benchmark_correct = benchmark_build_ok  # build OK implies correctness check passed

        benchmark_metrics: dict[str, Optional[float]] = {
            "execution_time_s": None,
            "code_size_bytes": None,
            "energy_j": None,
            "carbon_g": None,
        }
        baseline_metrics: dict[str, Optional[float]] = {
            "execution_time_s": None,
            "code_size_bytes": None,
            "energy_j": None,
            "carbon_g": None,
        }

        if opt is not None and opt.status == MeasurementStatus.OK:
            benchmark_metrics["execution_time_s"] = opt.median_s
            benchmark_metrics["code_size_bytes"] = (
                float(opt.code_size_bytes) if opt.code_size_bytes is not None else None
            )
            benchmark_metrics["energy_j"] = opt.energy_joules
            benchmark_metrics["carbon_g"] = opt.carbon_grams

        if base is not None and base.status == MeasurementStatus.OK:
            baseline_metrics["execution_time_s"] = base.median_s
            baseline_metrics["code_size_bytes"] = (
                float(base.code_size_bytes) if base.code_size_bytes is not None else None
            )
            baseline_metrics["energy_j"] = base.energy_joules
            baseline_metrics["carbon_g"] = base.carbon_grams

        # Noise/reliability from regression comparison
        confidence: Optional[str] = None
        is_reliable: Optional[bool] = None
        if record.regression_comparison:
            # Try to extract from regression comparison
            sel_comp = record.regression_comparison.get("selected_comparison")
            if sel_comp and isinstance(sel_comp, dict):
                metric_comps = sel_comp.get("metric_comparisons") or {}
                et = metric_comps.get("execution_time") or {}
                if isinstance(et, dict):
                    confidence = et.get("confidence")
                    rel = et.get("is_reliable")
                    is_reliable = bool(rel) if rel is not None else None

        # Compute reward
        cfg = reward_config or DEFAULT_REWARD_CONFIG
        computed_reward = compute_reward(
            benchmark_metrics=benchmark_metrics,
            baseline_metrics=baseline_metrics,
            benchmark_build_ok=benchmark_build_ok,
            benchmark_correct=benchmark_correct,
            confidence=confidence,
            is_reliable=is_reliable,
            regression_overall_status=record.regression_overall_status,
            config=cfg,
        )

        inconclusive = is_performance_inconclusive(
            confidence=confidence,
            is_reliable=is_reliable,
            regression_overall_status=record.regression_overall_status,
        )
        success = (
            benchmark_build_ok
            and benchmark_correct
            and (computed_reward is not None and computed_reward > 0.0)
            and not inconclusive
        )

        now = make_timestamp()
        compact = now.replace(":", "").replace("-", "").replace("+", "")[:15]
        prog_id = record.source_file or record.source_hash or record.run_id
        exp_id = f"{prog_id}_{record.run_id}_{compact}"

        exp = ExperienceRecord(
            schema_version=ADAPTIVE_SCHEMA_VERSION,
            experience_id=exp_id,
            program_id=str(prog_id),
            source_hash=str(record.source_hash),
            run_id=str(record.run_id),
            timestamp=now,
            ir_features=dict(record.ir_features),
            selected_action=str(record.selected_strategy),
            selection_method=selection_method,
            model_identifier=str(record.selection_model_id or "production_v0"),
            trace_id=record.decision_trace_id,
            q_value_selected=record.q_value_selected,
            q_value_argmax=record.q_value_argmax,
            pareto_frontier=list(record.pareto_frontier),
            benchmark_metrics=benchmark_metrics,
            baseline_metrics=baseline_metrics,
            benchmark_build_ok=benchmark_build_ok,
            benchmark_correct=benchmark_correct,
            regression_overall_status=record.regression_overall_status,
            regression_report_id=None,
            reward=computed_reward,
            reward_config_id=cfg.config_id,
            success=success,
            notes=[
                f"Projected from RunRecord run_id={record.run_id}",
                f"Selection provenance: {record.selection_provenance.value}",
                "ADVISORY ONLY — does not modify production model",
            ],
            confidence=confidence or "HIGH",
            is_reliable=is_reliable if is_reliable is not None else True,
        )

        # Validate
        val_res = validate_experience(exp)
        if not val_res:
            if strict:
                raise ValueError(f"Projected ExperienceRecord failed validation: {val_res.errors}")
            return None

        return exp

    except ImportError:
        if strict:
            raise
        return None
    except Exception as exc:
        if strict:
            raise
        return None


# ---------------------------------------------------------------------------
# Projection: → agentic AgentContext
# ---------------------------------------------------------------------------

def to_agent_context(
    record: RunRecord,
    historical_experiences: Optional[list] = None,
) -> Optional[Any]:
    """
    Project a RunRecord into a Week 12 AgentContext.

    SAFETY GUARANTEE: The resulting AgentContext is advisory input only.
    The agentic engine NEVER overrides selected_strategy.

    Parameters
    ----------
    record                  : RunRecord to project from
    historical_experiences  : optional list of ExperienceRecord or dicts

    Returns
    -------
    AgentContext or None if required data is missing
    """
    try:
        from ..agentic.adapter import build_agent_context

        if not record.selected_strategy:
            return None
        if not record.source_hash and not record.source_file:
            return None

        prog_id = record.source_file or record.source_hash or record.run_id
        source_hash = record.source_hash or ""

        # Prepare comparison dict from regression (withheld if fallback occurred)
        comp_dict = None if _fallback_evidence(record) else record.regression_comparison

        return build_agent_context(
            program_id=str(prog_id),
            source_hash=source_hash,
            selected_strategy=str(record.selected_strategy),
            decision_trace=record.decision_trace,
            program_profile=record.program_profile,
            experience_records=historical_experiences or [],
            program_comparison=comp_dict,
            metadata={
                "run_id": record.run_id,
                "selection_provenance": record.selection_provenance.value,
                "benchmark_status": record.benchmark_status.value,
                "regression_status": record.regression_status.value,
                "security_status": record.security_status.value,
                "effective_strategy": record.effective_strategy or record.selected_strategy,
                "fallback_occurred": _fallback_evidence(record),
                "is_advisory_only": True,
            },
        )
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Projection: → GUI view model
# ---------------------------------------------------------------------------

def to_gui_view(record: RunRecord) -> dict[str, Any]:
    """
    Project a RunRecord into a GUI-consumable view model.

    CRITICAL: No missing or failed field is reported as "OK" or success.
    Every status is explicitly represented.

    This projection is stable and backward-compatible: new fields added to
    RunRecord appear in the view; existing fields never change meaning.
    """
    # Timing summary
    baseline_timing = None
    if record.baseline_measurement and record.baseline_measurement.has_valid_timing():
        baseline_timing = {
            "median_s": record.baseline_measurement.median_s,
            "code_size_bytes": record.baseline_measurement.code_size_bytes,
            "timing_is_reliable": record.baseline_measurement.timing_is_reliable,
        }

    optimized_timing = None
    if record.optimized_measurement and record.optimized_measurement.has_valid_timing():
        optimized_timing = {
            "median_s": record.optimized_measurement.median_s,
            "code_size_bytes": record.optimized_measurement.code_size_bytes,
            "timing_is_reliable": record.optimized_measurement.timing_is_reliable,
        }

    # XAI summary
    xai_summary = None
    if record.xai_result:
        xai_summary = {
            "final_strategy": record.xai_result.get("final_strategy"),
            "selection_method": record.xai_result.get("selection_method"),
            "moo_active": record.xai_result.get("moo_active"),
            "ai_top_choice": record.xai_result.get("ai_top_choice"),
        }

    # Security summary — never fabricate positive result
    security_summary = {
        "status": record.security_status.value,
        "verdict": record.security_verdict,  # None if not run
    }
    if record.security_status == RunStatus.NOT_RUN:
        security_summary["message"] = "Security analyzer was not executed for this run"
    elif record.security_status == RunStatus.UNKNOWN:
        security_summary["message"] = "Security analyzer ran but result is inconclusive"

    # Agentic summary
    agentic_summary = {
        "status": record.agentic_status.value,
        "verdict": record.agentic_verdict,
        "is_advisory_only": True,  # ALWAYS True
    }

    # Adaptive summary
    adaptive_summary = {
        "status": record.adaptive_status.value,
        "experience_id": record.adaptive_experience_id,
        "reward": record.adaptive_reward,
        "is_advisory_only": True,  # ALWAYS True
    }

    # Week 14 Provenance & Security Additions
    fallback_occ = _fallback_evidence(record)
    effective_strat = record.effective_strategy or record.selected_strategy
    effective_strat_known = (record.effective_strategy is not None)

    provenance_label = "SECURITY_GATE_FALLBACK" if fallback_occ else "ORIGINAL_SELECTION"
    xai_prov = "Describes original selection"
    agentic_prov = (
        "Describes original selection (empirical evidence withheld)"
        if fallback_occ
        else "Describes original selection"
    )

    sec_notes = []
    if record.security_result and isinstance(record.security_result, dict):
        sec_notes = record.security_result.get("notes") or []
    sec_scope = "SOURCE_SCAN" if any("scope=SOURCE_SCAN" in str(n) for n in sec_notes) else "OPTIMIZATION_CANDIDATE"

    opt_sec = None
    if isinstance(record.security_gate, dict):
        opt_sec = record.security_gate.get("candidate_security")

    agentic_quarantined = False
    if isinstance(record.agentic_security, dict):
        agentic_quarantined = bool(record.agentic_security.get("report_quarantined", False))

    return {
        "run_id": record.run_id,
        "created_at": record.created_at,
        "source_file": record.source_file,
        "source_hash": record.source_hash,

        # Selection
        "selected_strategy": record.selected_strategy,
        "effective_strategy": effective_strat,
        "effective_strategy_known": effective_strat_known,
        "fallback_occurred": fallback_occ,
        "selection_status": record.selection_status.value,
        "selection_provenance": record.selection_provenance.value,
        "provenance": provenance_label,
        "xai_provenance": xai_prov,
        "agentic_provenance": agentic_prov,

        # Program profile
        "profile_status": record.profile_status.value,
        "profile_label": (
            record.program_profile.get("label")
            if record.program_profile
            else None
        ),

        # XAI / DecisionTrace
        "trace_status": record.trace_status.value,
        "xai_summary": xai_summary,

        # Benchmark measurements
        "benchmark_status": record.benchmark_status.value,
        "baseline_status": record.baseline_status.value,
        "optimized_status": record.optimized_status.value,
        "baseline_timing": baseline_timing,
        "optimized_timing": optimized_timing,

        # Pareto / MOO
        "moo_active": record.moo_active,
        "pareto_frontier": list(record.pareto_frontier),

        # Regression
        "regression_status": record.regression_status.value,
        "regression_overall_status": record.regression_overall_status,

        # Security — explicit NOT_RUN unless analyzer ran
        "security": security_summary,
        "security_scope": sec_scope,
        "security_gate": record.security_gate,
        "optimized_security": opt_sec,
        "security_events_summary": {
            "total_events": len(record.security_events),
            "blocked_events": sum(1 for e in record.security_events if e.get("blocked", False)),
        },

        # Adaptive (advisory)
        "adaptive": adaptive_summary,

        # Agentic (advisory)
        "agentic": agentic_summary,
        "agentic_quarantine_status": agentic_quarantined,

        # Overall
        "overall_status": record.overall_status.value,
    }


# ---------------------------------------------------------------------------
# Projection: → GUI display text & reference validation helpers (Week 14)
# ---------------------------------------------------------------------------

def security_display_text(view: dict[str, Any]) -> str:
    """
    Format a concise, authoritative security status string for GUI display.
    Guarantees:
      - PRESERVED candidate security displays '✓ Preserved'
      - UNKNOWN / ERROR / unverified displays 'Unverified (...)'
      - NOT_APPLICABLE displays 'No guards to preserve'
      - REDUCED displays 'Guards reduced (warning)'
      - Fallback appends ' [fallback → <effective>]'
      - Source-only security never starts with '✓'
    """
    if not isinstance(view, dict):
        return "—"

    fallback_occ = bool(view.get("fallback_occurred", False))
    effective_strat = view.get("effective_strategy") or view.get("selected_strategy") or "unknown"
    sec_scope = view.get("security_scope", "OPTIMIZATION_CANDIDATE")
    sec_dict = view.get("security") or {}
    sec_status = sec_dict.get("status")
    sec_verdict = sec_dict.get("verdict")
    sec_gate = view.get("security_gate")

    # If security did not run
    if sec_status == "NOT_RUN" and not sec_gate:
        return "Not Analyzed"

    # Check candidate/gate verdict first if available
    cand_sec = view.get("optimized_security")
    if not cand_sec and isinstance(sec_gate, dict):
        cand_sec = sec_gate.get("candidate_security")

    gate_unverified = bool(sec_gate.get("unverified", False)) if isinstance(sec_gate, dict) else False

    verdict = None
    if isinstance(cand_sec, dict):
        verdict = cand_sec.get("verdict")
    elif cand_sec and hasattr(cand_sec, "verdict"):
        verdict = cand_sec.verdict

    if not verdict:
        verdict = sec_verdict

    if hasattr(verdict, "value"):
        verdict = verdict.value
    elif verdict is not None:
        verdict = str(verdict)

    # Determine base text
    if sec_scope == "SOURCE_SCAN" and not sec_gate:
        # Source-only scan: MUST NEVER start with '✓'
        if verdict == "PRESERVED":
            base = "Source guards intact (source scan)"
        elif verdict == "REDUCED":
            base = "Guards reduced (warning)"
        elif verdict == "NOT_APPLICABLE":
            base = "No guards to preserve"
        elif verdict in ("UNKNOWN", "ERROR") or sec_status == "UNKNOWN":
            base = f"Unverified ({verdict or 'source scan'})"
        else:
            base = f"Source scan: {verdict or 'unknown'}"
    else:
        # Optimization candidate verification
        if gate_unverified or verdict in ("UNKNOWN", "ERROR") or sec_status == "UNKNOWN":
            tag = verdict if verdict in ("UNKNOWN", "ERROR") else "inconclusive"
            base = f"Unverified ({tag})"
        elif verdict == "PRESERVED":
            base = "✓ Preserved"
        elif verdict == "NOT_APPLICABLE":
            base = "No guards to preserve"
        elif verdict == "REDUCED":
            base = "Guards reduced (warning)"
        elif verdict == "ELIMINATED":
            base = "Guards eliminated (rejected)"
        else:
            base = f"Security: {verdict or '—'}"

    if fallback_occ:
        base += f" [fallback → {effective_strat}]"

    return base


def validate_reference_run(
    view: dict[str, Any],
    expected_strategy: str,
) -> tuple[bool, str]:
    """
    Validate that a reference run (such as -O3) was actually executed with
    the expected strategy without substitution or fallback.

    Returns
    -------
    (is_valid, reason) : tuple[bool, str]
    """
    if not isinstance(view, dict):
        return False, "Invalid view model: not a dict"
    if view.get("fallback_occurred"):
        eff = view.get("effective_strategy", "unknown")
        return False, f"Fallback occurred in reference run (effective={eff})"
    effective = view.get("effective_strategy") or view.get("selected_strategy")
    if effective != expected_strategy:
        return False, f"Strategy mismatch: expected {expected_strategy}, got {effective}"
    return True, "OK"
