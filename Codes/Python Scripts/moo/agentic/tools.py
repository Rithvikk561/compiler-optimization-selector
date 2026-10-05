"""
TOACD — Week 12: Real-Time Agentic AI Analysis — Deterministic Tools
=====================================================================
Read-only, side-effect-free diagnostic tools used by the bounded agentic
reasoning loop.

Strict Design Principles:
1. Pure read-only inspection (inputs are never mutated).
2. Adherence to canonical IR profile features (no hallucinated features).
3. Noise-aware history and regression handling (respects Week 10/11 semantics).
4. Strictly bounded execution (max records examined M <= 10).
5. Advisory-only recommendations with verified numerical evidence.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from moo.agentic.schema import (
    AlternativeRecommendation,
    EvidenceTier,
    Finding,
    FindingSeverity,
    TradeoffAlert,
    AgentContext,
)

VALID_ACTIONS: List[str] = ["-O0", "-O1", "-O2", "-O3", "-Os", "-Oz"]
MAX_HISTORY_EXAMINED: int = 10


def audit_provenance_tool(context: AgentContext) -> List[Finding]:
    """Audits selection provenance and method consistency from DecisionTrace."""
    findings: List[Finding] = []
    trace = context.decision_trace

    if not trace or not isinstance(trace, dict):
        findings.append(
            Finding(
                category="DATA_GAP",
                severity=FindingSeverity.WARNING,
                message="DecisionTrace unavailable for provenance audit.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
            )
        )
        return findings

    method = str(trace.get("selection_method", "")).lower()
    final_strat = str(trace.get("final_strategy", ""))

    # Strategy identity check
    if final_strat and final_strat != context.selected_strategy:
        findings.append(
            Finding(
                category="PROVENANCE",
                severity=FindingSeverity.ALERT,
                message=(
                    f"Selected strategy '{context.selected_strategy}' conflicts with "
                    f"trace final_strategy '{final_strat}'."
                ),
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"trace_strategy": final_strat, "context_strategy": context.selected_strategy},
            )
        )

    # Selection provenance classification
    if "fallback" in method or "default" in method:
        findings.append(
            Finding(
                category="PROVENANCE",
                severity=FindingSeverity.WARNING,
                message=f"Fallback selection mechanism used ({method}); MOO frontier or Q-values were unavailable.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"selection_method": method},
            )
        )
    elif "moo" in method or "pareto" in method:
        frontier = trace.get("pareto_frontier", [])
        findings.append(
            Finding(
                category="PROVENANCE",
                severity=FindingSeverity.INFO,
                message=f"Selected strategy is supported by multi-objective Pareto frontier ({len(frontier)} candidates).",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"selection_method": method, "frontier_size": len(frontier)},
            )
        )
    elif "argmax" in method or "q" in method:
        findings.append(
            Finding(
                category="PROVENANCE",
                severity=FindingSeverity.INFO,
                message="Selected strategy is supported by Q-network argmax estimation.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"selection_method": method},
            )
        )
    else:
        findings.append(
            Finding(
                category="PROVENANCE",
                severity=FindingSeverity.INFO,
                message=f"Selection mechanism recorded as '{method}'.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"selection_method": method},
            )
        )

    return findings


def analyze_ir_profile_tool(context: AgentContext) -> List[Finding]:
    """Analyzes the 8 canonical IR features against the selected optimization strategy."""
    findings: List[Finding] = []
    profile = context.program_profile

    if not profile or not isinstance(profile, dict):
        findings.append(
            Finding(
                category="DATA_GAP",
                severity=FindingSeverity.INFO,
                message="ProgramProfile unavailable for IR structural intelligence.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
            )
        )
        return findings

    # Only inspect canonical features established in Weeks 7–8
    det_profile = str(profile.get("deterministic_profile", "unknown")).lower()
    inst_count = profile.get("instruction_count", 0)
    loop_count = profile.get("loop_count", 0)
    branch_ratio = profile.get("branch_ratio", 0.0)
    mem_ratio = profile.get("memory_ops_ratio", 0.0)
    strat = context.selected_strategy

    if det_profile == "small_leaf_routine" and strat in ["-O3"]:
        findings.append(
            Finding(
                category="IR_PROFILE",
                severity=FindingSeverity.INFO,
                message="Small leaf routine selected with -O3; inlining and loop vectorization may yield diminishing returns.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"profile": det_profile, "instruction_count": inst_count},
            )
        )
    elif det_profile == "control_flow_heavy" and strat in ["-O3"]:
        findings.append(
            Finding(
                category="IR_PROFILE",
                severity=FindingSeverity.WARNING,
                message="Control-flow heavy routine selected with -O3; high branch density risks code bloat with minimal speedup.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"profile": det_profile, "branch_ratio": branch_ratio},
            )
        )
    elif det_profile == "compute_intensive" and strat in ["-O2", "-O3"]:
        findings.append(
            Finding(
                category="IR_PROFILE",
                severity=FindingSeverity.INFO,
                message="Compute intensive routine aligns well with aggressive optimization strategy.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"profile": det_profile, "loop_count": loop_count},
            )
        )
    elif det_profile == "memory_intensive" and strat in ["-Os", "-Oz"]:
        findings.append(
            Finding(
                category="IR_PROFILE",
                severity=FindingSeverity.INFO,
                message="Memory intensive routine selected with size-optimizing strategy; helps minimize cache pressure.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"profile": det_profile, "memory_ops_ratio": mem_ratio},
            )
        )
    else:
        findings.append(
            Finding(
                category="IR_PROFILE",
                severity=FindingSeverity.INFO,
                message=f"IR profile '{det_profile}' observed with {inst_count} instructions and {loop_count} loops.",
                evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                details={"profile": det_profile, "instruction_count": inst_count, "loop_count": loop_count},
            )
        )

    return findings


def audit_history_tool(context: AgentContext) -> Tuple[List[Finding], Dict[str, Any]]:
    """Evaluates historical experiences with strict noise-aware gating (Week 10/11 semantics)."""
    findings: List[Finding] = []
    summary: Dict[str, Any] = {
        "records_examined": 0,
        "reliable_count": 0,
        "noisy_count": 0,
        "regressed_count": 0,
        "avg_reward": 0.0,
    }

    records = context.historical_experiences
    if not records:
        findings.append(
            Finding(
                category="DATA_GAP",
                severity=FindingSeverity.INFO,
                message="No historical experiences available for this source hash.",
                evidence_tier=EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE,
            )
        )
        return findings, summary

    # Deterministic stable sort: timestamp descending, experience_id ascending
    sorted_records = sorted(
        records,
        key=lambda r: (str(r.get("timestamp_iso", "")), str(r.get("experience_id", ""))),
        reverse=True,
    )[:MAX_HISTORY_EXAMINED]

    summary["records_examined"] = len(sorted_records)
    reliable_rewards: List[float] = []

    for r in sorted_records:
        strat = r.get("selected_strategy") or r.get("selected_action")
        if strat != context.selected_strategy:
            continue

        is_reliable = r.get("is_reliable", True)
        confidence = str(r.get("confidence", "HIGH")).upper()
        overall_status = str(r.get("regression_overall_status", "")).upper()
        reward = r.get("reward")

        # Noise-aware gating: inconclusive or unreliable measurements are not proof of regression
        if not is_reliable or confidence == "INCONCLUSIVE" or overall_status == "INCONCLUSIVE":
            summary["noisy_count"] += 1
            continue

        summary["reliable_count"] += 1
        if reward is not None:
            reliable_rewards.append(float(reward))

        # Check for confirmed regression
        if overall_status in ["REGRESSED", "CONFIRMED_REGRESSION"] or (reward is not None and reward < -0.2):
            summary["regressed_count"] += 1

    if summary["noisy_count"] > 0:
        findings.append(
            Finding(
                category="NOISE",
                severity=FindingSeverity.INFO,
                message=f"Observed {summary['noisy_count']} noisy/inconclusive historical records; quarantined from regression gating.",
                evidence_tier=EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE,
                details={"noisy_records": summary["noisy_count"]},
            )
        )

    if reliable_rewards:
        summary["avg_reward"] = sum(reliable_rewards) / len(reliable_rewards)

    if summary["regressed_count"] > 0:
        findings.append(
            Finding(
                category="REGRESSION",
                severity=FindingSeverity.WARNING,
                message=(
                    f"Historical experience shows {summary['regressed_count']} reliable regression occurrences "
                    f"for strategy '{context.selected_strategy}' (avg reward: {summary['avg_reward']:.3f})."
                ),
                evidence_tier=EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE,
                details={"regressed_count": summary["regressed_count"], "avg_reward": summary["avg_reward"]},
            )
        )
    elif summary["reliable_count"] > 0:
        findings.append(
            Finding(
                category="HISTORY",
                severity=FindingSeverity.INFO,
                message=(
                    f"Historical experience confirms stable outcomes across {summary['reliable_count']} reliable runs "
                    f"(avg reward: {summary['avg_reward']:.3f})."
                ),
                evidence_tier=EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE,
                details={"reliable_count": summary["reliable_count"], "avg_reward": summary["avg_reward"]},
            )
        )

    return findings, summary


def analyze_regression_metrics_tool(context: AgentContext) -> Tuple[List[Finding], Dict[str, Any]]:
    """Analyzes Week 10 empirical benchmark regression metrics against -O0 baseline."""
    findings: List[Finding] = []
    summary: Dict[str, Any] = {
        "status": "NONE",
        "execution_time_ratio": None,
        "code_size_ratio": None,
        "memory_overhead_ratio": None,
    }

    comp = context.program_comparison
    if not comp or not isinstance(comp, dict):
        findings.append(
            Finding(
                category="DATA_GAP",
                severity=FindingSeverity.INFO,
                message="Empirical benchmark/regression comparison not available.",
                evidence_tier=EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
            )
        )
        return findings, summary

    overall_status = str(comp.get("overall_status") or "UNKNOWN").upper()
    summary["status"] = overall_status

    # Extract metric comparisons for the selected strategy
    strat_comps = comp.get("strategy_comparisons")
    if not isinstance(strat_comps, dict):
        strat_comps = {}
    selected_comp = strat_comps.get(context.selected_strategy) or comp.get("selected_comparison")
    if not isinstance(selected_comp, dict):
        selected_comp = {}
    metric_comps = selected_comp.get("metric_comparisons")
    if not isinstance(metric_comps, dict):
        metric_comps = {}

    for metric_name, m_data in metric_comps.items():
        if isinstance(m_data, dict):
            ratio = m_data.get("ratio")
            if ratio is not None:
                if "time" in metric_name:
                    summary["execution_time_ratio"] = float(ratio)
                elif "size" in metric_name:
                    summary["code_size_ratio"] = float(ratio)
                elif "memory" in metric_name or "rss" in metric_name:
                    summary["memory_overhead_ratio"] = float(ratio)

    if overall_status in ["CONFIRMED_REGRESSION", "REGRESSED"]:
        findings.append(
            Finding(
                category="REGRESSION",
                severity=FindingSeverity.ALERT,
                message=f"Empirical benchmark confirms performance regression for '{context.selected_strategy}'.",
                evidence_tier=EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
                details=summary,
            )
        )
    elif overall_status == "INCONCLUSIVE":
        findings.append(
            Finding(
                category="NOISE",
                severity=FindingSeverity.WARNING,
                message="Empirical benchmark metrics exhibit high measurement noise; regression status is INCONCLUSIVE.",
                evidence_tier=EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
                details=summary,
            )
        )
    elif overall_status in ["IMPROVED", "NO_REGRESSION"]:
        findings.append(
            Finding(
                category="REGRESSION",
                severity=FindingSeverity.INFO,
                message=f"Empirical benchmark confirms valid performance improvement for '{context.selected_strategy}'.",
                evidence_tier=EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
                details=summary,
            )
        )
    elif overall_status == "INCOMPARABLE":
        findings.append(
            Finding(
                category="DATA_GAP",
                severity=FindingSeverity.WARNING,
                message="Empirical metrics are incomparable with baseline (e.g. execution error or missing metrics).",
                evidence_tier=EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
                details=summary,
            )
        )

    return findings, summary


def evaluate_tradeoffs_tool(
    context: AgentContext,
    metric_summary: Dict[str, Any],
) -> List[TradeoffAlert]:
    """Detects multi-objective conflicts between execution time, code size, and memory."""
    alerts: List[TradeoffAlert] = []

    exec_ratio = metric_summary.get("execution_time_ratio")
    size_ratio = metric_summary.get("code_size_ratio")

    if exec_ratio is not None and size_ratio is not None:
        # Speed gained at significant binary size bloat
        if exec_ratio < 0.90 and size_ratio > 1.25:
            alerts.append(
                TradeoffAlert(
                    objective_favored="execution_time",
                    objective_degraded="code_size",
                    ratio=size_ratio,
                    threshold=1.25,
                    description=(
                        f"Execution time improved to {exec_ratio:.2f}x baseline, but binary size "
                        f"expanded by {(size_ratio - 1.0) * 100:.1f}% (> 25% threshold)."
                    ),
                )
            )
        # Code size minimized at significant runtime speed penalty
        elif size_ratio < 0.85 and exec_ratio > 1.15:
            alerts.append(
                TradeoffAlert(
                    objective_favored="code_size",
                    objective_degraded="execution_time",
                    ratio=exec_ratio,
                    threshold=1.15,
                    description=(
                        f"Code size reduced to {size_ratio:.2f}x baseline, but runtime slowed "
                        f"by {(exec_ratio - 1.0) * 100:.1f}% (> 15% threshold)."
                    ),
                )
            )

    return alerts


def evaluate_alternative_tool(
    context: AgentContext,
    history_summary: Dict[str, Any],
    metric_summary: Dict[str, Any],
) -> Optional[AlternativeRecommendation]:
    """
    Evaluates potential alternative compiler strategies with strict validation.
    
    Requirements:
    1. Member of VALID_ACTIONS.
    2. Differs from context.selected_strategy.
    3. Pareto-frontier valid if frontier is present in DecisionTrace.
    4. Backed by measured empirical evidence.
    5. Advisory only (never overrides).
    """
    comp = context.program_comparison
    if not comp or not isinstance(comp, dict):
        return None

    # Check whether the current selection has a confirmed regression or severe tradeoff
    status = metric_summary.get("status", "")
    regressed_in_history = history_summary.get("regressed_count", 0) > 0
    if status not in ["CONFIRMED_REGRESSION", "REGRESSED"] and not regressed_in_history:
        return None

    strat_comps = comp.get("strategy_comparisons")
    if not isinstance(strat_comps, dict):
        return None

    trace = context.decision_trace or {}
    frontier = trace.get("pareto_frontier", [])

    best_candidate: Optional[str] = None
    best_time_ratio: float = 1.0
    best_size_ratio: float = 1.0

    for cand, c_data in strat_comps.items():
        if cand not in VALID_ACTIONS or cand == context.selected_strategy:
            continue

        # If frontier exists, candidate must be on it
        if frontier and cand not in frontier:
            continue

        m_comps = c_data.get("metric_comparisons", {}) if isinstance(c_data, dict) else {}
        t_ratio = m_comps.get("execution_time", {}).get("ratio")
        s_ratio = m_comps.get("code_size", {}).get("ratio")

        if t_ratio is not None and t_ratio < 1.0:
            if best_candidate is None or t_ratio < best_time_ratio:
                best_candidate = cand
                best_time_ratio = float(t_ratio)
                best_size_ratio = float(s_ratio) if s_ratio is not None else 1.0

    if best_candidate is not None:
        evidence = {
            "execution_time_ratio": best_time_ratio,
            "code_size_ratio": best_size_ratio,
        }
        return AlternativeRecommendation(
            strategy=best_candidate,
            justification=(
                f"Candidate '{best_candidate}' avoids confirmed regression of '{context.selected_strategy}' "
                f"with measured execution time ratio of {best_time_ratio:.3f}x baseline."
            ),
            numerical_evidence=evidence,
            pareto_verified=bool(frontier and best_candidate in frontier),
            is_advisory_only=True,
        )

    return None
