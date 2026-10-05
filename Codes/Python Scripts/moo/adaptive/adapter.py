"""
moo/adaptive/adapter.py — Canonical conversion from Week 9 / Week 10 artifacts to ExperienceRecord.

Bridges Week 10 Optimization Regression (moo.regression) and Week 9 Benchmarks
(moo.bench) into Week 11 Adaptive Self-Learning (moo.adaptive).

Handles all naming mismatches explicitly:
  - source_sha256 (Week 9/10)        → source_hash (Week 11)
  - selected_strategy (Week 10)      → selected_action (Week 11)
  - selection_source (Week 10)       → selection_method (Week 11)
  - execution_time (Week 9/10)       → execution_time_s (Week 11)
  - code_size (Week 9/10)            → code_size_bytes (Week 11)
  - energy (Week 9/10)               → energy_j (Week 11)
  - carbon (Week 9/10)               → carbon_g (Week 11)

Noise & reliability preservation:
  - Captures confidence, is_reliable, and regression_overall_status from Week 10.
  - Passes them to compute_reward() to prevent noisy/inconclusive measurements
    from receiving a normal-strength learning reward.

Fail-safe design:
  - When required provenance is missing, the helper fails safely rather than
    inventing or fabricating values (strict=False returns None; strict=True raises ValueError).
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

from .learner import _canonical_feature_order
from .reward import DEFAULT_REWARD_CONFIG, RewardConfig, compute_reward, is_performance_inconclusive
from .schema import ADAPTIVE_SCHEMA_VERSION, ExperienceRecord, make_timestamp
from .validator import validate_experience


# ---------------------------------------------------------------------------
# Metric Name Mappings
# ---------------------------------------------------------------------------

_METRIC_KEY_MAP = {
    "execution_time": "execution_time_s",
    "execution_time_s": "execution_time_s",
    "code_size": "code_size_bytes",
    "code_size_bytes": "code_size_bytes",
    "energy": "energy_j",
    "energy_j": "energy_j",
    "carbon": "carbon_g",
    "carbon_g": "carbon_g",
}


def experience_from_program_comparison(
    comparison: Any,
    *,
    features: Optional[Mapping[str, float] | Sequence[float]] = None,
    run_id: Optional[str] = None,
    program_record: Optional[Any] = None,
    decision_trace: Optional[Any] = None,
    experience_id: Optional[str] = None,
    reward_config: Optional[RewardConfig] = None,
    strict: bool = False,
) -> Optional[ExperienceRecord]:
    """
    Construct a validated ExperienceRecord from a Week 10 ProgramComparison
    (and optional Week 9 ProgramRecord or Week 7/8 DecisionTrace).

    Parameters
    ----------
    comparison
        ProgramComparison dataclass or dict from Week 10 regression.
    features
        Canonical 8 IR feature vector (dict or sequence of floats).
        If None, attempts extraction from program_record or decision_trace.
    run_id
        Benchmark run identifier string. If None, attempts extraction
        from program_record.
    program_record
        Optional Week 9 ProgramRecord or dict providing run_id and features.
    decision_trace
        Optional DecisionTrace or dict providing trace_id, ir_features, Q-values.
    experience_id
        Optional explicit experience_id. If omitted, formatted automatically.
    reward_config
        Optional RewardConfig. Defaults to DEFAULT_REWARD_CONFIG.
    strict
        If True, raises ValueError on missing provenance or invalid data.
        If False (default), returns None on failure (fail-safe).

    Returns
    -------
    ExperienceRecord or None (if strict=False and conversion failed).
    """
    try:
        return _convert(
            comparison=comparison,
            features=features,
            run_id=run_id,
            program_record=program_record,
            decision_trace=decision_trace,
            experience_id=experience_id,
            reward_config=reward_config,
            strict=strict,
        )
    except Exception as exc:
        if strict:
            raise
        return None


def _convert(
    comparison: Any,
    features: Optional[Mapping[str, float] | Sequence[float]],
    run_id: Optional[str],
    program_record: Optional[Any],
    decision_trace: Optional[Any],
    experience_id: Optional[str],
    reward_config: Optional[RewardConfig],
    strict: bool,
) -> Optional[ExperienceRecord]:
    # 1. Program identity
    program_id = _get_attr_or_key(comparison, "program_id")
    if not program_id:
        if strict:
            raise ValueError("ProgramComparison has no program_id")
        return None

    # 2. Selection Provenance (Week 10 SelectionRecord)
    # Week 10 explicitly enforces that an AI selection must have a SelectionRecord.
    # We refuse to fabricate an AI selection if provenance is omitted.
    provenance = _get_attr_or_key(comparison, "selection_provenance")
    if provenance is None:
        if strict:
            raise ValueError(
                f"ProgramComparison for {program_id!r} has no selection_provenance; "
                "cannot fabricate provenance"
            )
        return None

    source_sha256 = _get_attr_or_key(provenance, "source_sha256")
    if not source_sha256 or len(str(source_sha256)) < 32:
        if strict:
            raise ValueError(
                f"selection_provenance for {program_id!r} has missing or invalid source_sha256"
            )
        return None
    source_hash = str(source_sha256)

    selected_strategy = (
        _get_attr_or_key(provenance, "selected_strategy")
        or _get_attr_or_key(comparison, "selected_strategy")
    )
    if not selected_strategy:
        if strict:
            raise ValueError(f"No selected_strategy found for {program_id!r}")
        return None
    selected_action = str(selected_strategy)

    selection_source = _get_attr_or_key(provenance, "selection_source") or "moo_aware"
    selection_method = str(selection_source)

    model_identifier = _get_attr_or_key(provenance, "model_identifier") or "production_v0"
    trace_id = _get_attr_or_key(provenance, "trace_id")
    if not trace_id and decision_trace:
        trace_id = _get_attr_or_key(decision_trace, "trace_id")

    # 3. Strategy Comparison (Outcome)
    selected_comp = _get_attr_or_key(comparison, "selected_comparison")
    if selected_comp is None:
        # Fallback to strategy_comparisons[selected_strategy]
        strats = _get_attr_or_key(comparison, "strategy_comparisons") or {}
        selected_comp = strats.get(selected_action)

    if selected_comp is None:
        if strict:
            raise ValueError(
                f"No StrategyComparison found for selected strategy {selected_action!r}"
            )
        return None

    build_ok = bool(_get_attr_or_key(selected_comp, "is_valid", True))
    correct = build_ok  # StrategyComparison is_valid requires successful build and run

    # Extract metric comparisons
    metric_comps = _get_attr_or_key(selected_comp, "metric_comparisons") or {}

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

    confidence: Optional[str] = None
    is_reliable: Optional[bool] = None

    for raw_name, m_comp in metric_comps.items():
        mapped_key = _METRIC_KEY_MAP.get(raw_name)
        if not mapped_key:
            continue
        t_val = _get_attr_or_key(m_comp, "target_value")
        b_val = _get_attr_or_key(m_comp, "baseline_value")
        benchmark_metrics[mapped_key] = float(t_val) if _is_finite_num(t_val) else None
        baseline_metrics[mapped_key] = float(b_val) if _is_finite_num(b_val) else None

        if raw_name == "execution_time":
            confidence = _get_attr_or_key(m_comp, "confidence")
            rel = _get_attr_or_key(m_comp, "is_reliable")
            is_reliable = bool(rel) if rel is not None else True

    # 4. Regression status
    raw_status = _get_attr_or_key(comparison, "overall_status")
    regression_overall_status: Optional[str] = None
    if raw_status is not None:
        regression_overall_status = str(raw_status.value if hasattr(raw_status, "value") else raw_status)

    pareto_frontier = list(_get_attr_or_key(comparison, "pareto_frontier") or [])

    # 5. Extract IR Features (state)
    ir_features = _resolve_features(
        features=features,
        program_record=program_record,
        decision_trace=decision_trace,
    )
    if not ir_features:
        if strict:
            raise ValueError(
                f"No canonical IR features available for {program_id!r}; "
                "cannot formulate DQN state vector"
            )
        return None

    # 6. Resolve run_id
    effective_run_id = run_id
    if not effective_run_id and program_record:
        effective_run_id = _get_attr_or_key(program_record, "run_id")
    if not effective_run_id:
        effective_run_id = "run_unspecified"

    # 7. Experience ID and timestamp
    now = make_timestamp()
    compact_ts = now.replace(":", "").replace("-", "").replace("+", "")[:15]
    if not experience_id:
        experience_id = f"{program_id}_{effective_run_id}_{compact_ts}"

    # 8. Q-values if decision trace is available
    q_value_selected: Optional[float] = None
    q_value_argmax: Optional[float] = None
    if decision_trace:
        q_value_selected = _get_attr_or_key(decision_trace, "ai_top_q")
        q_value_argmax = q_value_selected

    # 9. Deterministic Noise-Aware Reward
    cfg = reward_config or DEFAULT_REWARD_CONFIG
    computed_reward = compute_reward(
        benchmark_metrics=benchmark_metrics,
        baseline_metrics=baseline_metrics,
        benchmark_build_ok=build_ok,
        benchmark_correct=correct,
        confidence=confidence,
        is_reliable=is_reliable,
        regression_overall_status=regression_overall_status,
        config=cfg,
    )

    # 10. Success check
    inconclusive = is_performance_inconclusive(
        confidence=confidence,
        is_reliable=is_reliable,
        regression_overall_status=regression_overall_status,
    )
    success = (
        build_ok
        and correct
        and (computed_reward is not None and computed_reward > 0.0)
        and not inconclusive
    )

    exp = ExperienceRecord(
        schema_version=ADAPTIVE_SCHEMA_VERSION,
        experience_id=experience_id,
        program_id=str(program_id),
        source_hash=source_hash,
        run_id=str(effective_run_id),
        timestamp=now,
        ir_features=ir_features,
        selected_action=selected_action,
        selection_method=selection_method,
        model_identifier=str(model_identifier),
        trace_id=str(trace_id) if trace_id else None,
        q_value_selected=float(q_value_selected) if _is_finite_num(q_value_selected) else None,
        q_value_argmax=float(q_value_argmax) if _is_finite_num(q_value_argmax) else None,
        pareto_frontier=pareto_frontier,
        benchmark_metrics=benchmark_metrics,
        baseline_metrics=baseline_metrics,
        benchmark_build_ok=build_ok,
        benchmark_correct=correct,
        regression_overall_status=regression_overall_status,
        regression_report_id=None,
        reward=computed_reward,
        reward_config_id=cfg.config_id,
        success=success,
        notes=[
            f"Converted from Week 10 ProgramComparison for {program_id}",
            f"Provenance: {selection_method} via {model_identifier}",
        ],
        confidence=confidence or "HIGH",
        is_reliable=is_reliable if is_reliable is not None else True,
    )

    # Validate output
    val_res = validate_experience(exp)
    if not val_res:
        if strict:
            raise ValueError(f"Converted ExperienceRecord failed validation: {val_res.errors}")
        return None

    return exp


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _get_attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_finite_num(v: Any) -> bool:
    if v is None or isinstance(v, bool):
        return False
    try:
        f = float(v)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def _resolve_features(
    features: Optional[Mapping[str, float] | Sequence[float]],
    program_record: Optional[Any],
    decision_trace: Optional[Any],
) -> Optional[dict[str, float]]:
    # 1. Explicit features arg
    if features is not None:
        if isinstance(features, dict):
            return {str(k): float(v) for k, v in features.items() if _is_finite_num(v)}
        if isinstance(features, (list, tuple)):
            canonical = _canonical_feature_order()
            return {name: float(val) for name, val in zip(canonical, features) if _is_finite_num(val)}

    # 2. From Week 9 ProgramRecord
    if program_record is not None:
        feats = _get_attr_or_key(program_record, "features")
        if isinstance(feats, dict) and feats:
            return {str(k): float(v) for k, v in feats.items() if _is_finite_num(v)}

    # 3. From DecisionTrace
    if decision_trace is not None:
        feats = _get_attr_or_key(decision_trace, "ir_features")
        if isinstance(feats, dict) and feats:
            return {str(k): float(v) for k, v in feats.items() if _is_finite_num(v)}

    return None
