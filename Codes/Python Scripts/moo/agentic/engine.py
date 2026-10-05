"""
TOACD — Week 12: Real-Time Agentic AI Analysis — Engine & Planner
===================================================================
Implements the bounded, deterministic OBSERVE -> PLAN -> ACT -> REFLECT
agentic reasoning loop with dynamic evidence-dependent branching.

Strict Design Principles:
1. Bounded tool budget (default max 6 steps).
2. Dynamic branching based strictly on available evidence and prior findings.
3. Pluggable planner interface (PlannerProtocol).
4. Deterministic analytical equality for identical inputs.
5. Advisory-only synthesis (never overrides pipeline).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from moo.agentic.schema import (
    AGENTIC_SCHEMA_VERSION,
    AgentAnalysisReport,
    AgentContext,
    AgentVerdict,
    AlternativeRecommendation,
    EvidenceQuality,
    EvidenceTier,
    Finding,
    FindingSeverity,
    StepRecord,
    TradeoffAlert,
)
from moo.agentic.tools import (
    analyze_ir_profile_tool,
    analyze_regression_metrics_tool,
    audit_history_tool,
    audit_provenance_tool,
    evaluate_alternative_tool,
    evaluate_tradeoffs_tool,
)


@dataclass
class AnalysisState:
    """Internal working state of the agentic reasoning loop."""
    context: AgentContext
    step_count: int = 0
    findings: List[Finding] = field(default_factory=list)
    tradeoffs: List[TradeoffAlert] = field(default_factory=list)
    alternative: Optional[AlternativeRecommendation] = None
    steps: List[StepRecord] = field(default_factory=list)
    history_summary: Dict[str, Any] = field(default_factory=dict)
    metric_summary: Dict[str, Any] = field(default_factory=dict)
    tools_executed: Set[str] = field(default_factory=set)
    pending_hypotheses: Set[str] = field(default_factory=set)


class PlannerProtocol(Protocol):
    """Protocol for pluggable planning algorithms in the agentic loop."""

    def initialize_plan(self, state: AnalysisState) -> None:
        """Initializes candidate hypotheses based on observed context."""
        ...

    def plan_next_step(self, state: AnalysisState) -> Optional[Tuple[str, str]]:
        """
        Determines the next tool to execute and the rationale.
        Returns (tool_name, action_reason) or None when analysis is complete.
        """
        ...


class DeterministicRulePlanner:
    """
    Deterministic rule-based planner implementing evidence-dependent branching.
    
    Dynamically adjusts tool sequence based on:
    - Available evidence tiers
    - Observed regressions or noisy measurements
    - Detected multi-objective trade-offs
    """

    def initialize_plan(self, state: AnalysisState) -> None:
        tiers = set(state.context.tiers_available)
        state.pending_hypotheses = set()

        # Tier 1 tools always scheduled if Tier 1 present
        if EvidenceTier.TIER_1_STATIC_SELECTION in tiers:
            state.pending_hypotheses.add("AUDIT_PROVENANCE")
            state.pending_hypotheses.add("ANALYZE_PROFILE")

        # Tier 3 tools scheduled if empirical benchmarks present
        if EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK in tiers:
            state.pending_hypotheses.add("ANALYZE_REGRESSION")

        # Tier 2 tools scheduled if historical experiences present
        if EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE in tiers:
            state.pending_hypotheses.add("AUDIT_HISTORY")

    def plan_next_step(self, state: AnalysisState) -> Optional[Tuple[str, str]]:
        # Deterministic precedence ordering of pending hypotheses
        if "AUDIT_PROVENANCE" in state.pending_hypotheses:
            return ("audit_provenance_tool", "Audit selection provenance and DecisionTrace consistency")

        if "ANALYZE_PROFILE" in state.pending_hypotheses:
            return ("analyze_ir_profile_tool", "Analyze 8 canonical IR features against selected strategy")

        if "ANALYZE_REGRESSION" in state.pending_hypotheses:
            return ("analyze_regression_metrics_tool", "Evaluate empirical benchmark metrics and regression status")

        if "AUDIT_HISTORY" in state.pending_hypotheses:
            return ("audit_history_tool", "Audit historical experiences with noise and reliability gating")

        if "EVALUATE_TRADEOFFS" in state.pending_hypotheses:
            return ("evaluate_tradeoffs_tool", "Detect multi-objective trade-offs and code bloat")

        if "EVALUATE_ALTERNATIVE" in state.pending_hypotheses:
            return ("evaluate_alternative_tool", "Evaluate Pareto-valid alternative strategies backed by measured evidence")

        return None


class AgentEngine:
    """
    Deterministic agentic AI analysis engine.
    
    Executes a bounded OBSERVE -> PLAN -> ACT -> REFLECT reasoning loop.
    Guarantees pure read-only operation and identical analytical results
    for identical inputs.
    """

    def __init__(self, planner: Optional[PlannerProtocol] = None, max_budget: int = 6):
        self.planner: PlannerProtocol = planner or DeterministicRulePlanner()
        self.max_budget: int = max(1, min(max_budget, 10))

    def analyze(self, context: AgentContext) -> AgentAnalysisReport:
        """Runs the bounded agentic analysis loop on the supplied context."""
        state = AnalysisState(context=context)
        self.planner.initialize_plan(state)

        # Bounded OBSERVE -> PLAN -> ACT -> REFLECT loop
        while state.step_count < self.max_budget:
            # OBSERVE & PLAN
            next_step = self.planner.plan_next_step(state)
            if not next_step:
                break

            tool_name, reason = next_step
            findings_count_before = len(state.findings)

            # ACT
            self._execute_tool(tool_name, state)

            # REFLECT: Update hypotheses based on findings
            new_findings_count = len(state.findings) - findings_count_before
            state.step_count += 1
            state.tools_executed.add(tool_name)
            state.steps.append(
                StepRecord(
                    step_number=state.step_count,
                    tool_name=tool_name,
                    action_reason=reason,
                    findings_produced=new_findings_count,
                )
            )

            # Dynamic evidence-dependent branching
            if tool_name == "audit_provenance_tool":
                state.pending_hypotheses.discard("AUDIT_PROVENANCE")

            elif tool_name == "analyze_ir_profile_tool":
                state.pending_hypotheses.discard("ANALYZE_PROFILE")

            elif tool_name == "analyze_regression_metrics_tool":
                state.pending_hypotheses.discard("ANALYZE_REGRESSION")
                status = state.metric_summary.get("status", "")
                # If confirmed regression, dynamically schedule alternative evaluation
                if status in ["CONFIRMED_REGRESSION", "REGRESSED"]:
                    state.pending_hypotheses.add("EVALUATE_ALTERNATIVE")
                # If ratios exist, schedule tradeoff analysis
                if state.metric_summary.get("execution_time_ratio") is not None:
                    state.pending_hypotheses.add("EVALUATE_TRADEOFFS")

            elif tool_name == "audit_history_tool":
                state.pending_hypotheses.discard("AUDIT_HISTORY")
                # If reliable history shows regressions, schedule alternative evaluation
                if state.history_summary.get("regressed_count", 0) > 0:
                    state.pending_hypotheses.add("EVALUATE_ALTERNATIVE")

            elif tool_name == "evaluate_tradeoffs_tool":
                state.pending_hypotheses.discard("EVALUATE_TRADEOFFS")

            elif tool_name == "evaluate_alternative_tool":
                state.pending_hypotheses.discard("EVALUATE_ALTERNATIVE")

        # REFLECT & SYNTHESIZE
        return self._synthesize_report(state)

    def _execute_tool(self, tool_name: str, state: AnalysisState) -> None:
        """Executes a single tool deterministically."""
        ctx = state.context
        if tool_name == "audit_provenance_tool":
            state.findings.extend(audit_provenance_tool(ctx))

        elif tool_name == "analyze_ir_profile_tool":
            state.findings.extend(analyze_ir_profile_tool(ctx))

        elif tool_name == "analyze_regression_metrics_tool":
            f, m = analyze_regression_metrics_tool(ctx)
            state.findings.extend(f)
            state.metric_summary = m

        elif tool_name == "audit_history_tool":
            f, h = audit_history_tool(ctx)
            state.findings.extend(f)
            state.history_summary = h

        elif tool_name == "evaluate_tradeoffs_tool":
            alerts = evaluate_tradeoffs_tool(ctx, state.metric_summary)
            state.tradeoffs.extend(alerts)

        elif tool_name == "evaluate_alternative_tool":
            rec = evaluate_alternative_tool(ctx, state.history_summary, state.metric_summary)
            state.alternative = rec

    def _synthesize_report(self, state: AnalysisState) -> AgentAnalysisReport:
        """Synthesizes final verdict, evidence quality, and deterministic report ID."""
        ctx = state.context
        tiers = set(ctx.tiers_available)

        # 1. Evidence Quality Determination
        if not ctx.program_id or (not ctx.decision_trace and not ctx.program_profile):
            evidence_quality = EvidenceQuality.INSUFFICIENT
        elif (
            EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK in tiers
            and EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE in tiers
            and state.metric_summary.get("status") not in ["INCONCLUSIVE", "INCOMPARABLE", "UNKNOWN", "NONE"]
            and state.history_summary.get("noisy_count", 0) == 0
            and state.history_summary.get("reliable_count", 0) > 0
        ):
            evidence_quality = EvidenceQuality.HIGH
        elif (
            (EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK in tiers and state.metric_summary.get("status") not in ["INCONCLUSIVE", "INCOMPARABLE", "UNKNOWN", "NONE"])
            or (EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE in tiers and state.history_summary.get("reliable_count", 0) > 0)
        ):
            evidence_quality = EvidenceQuality.MEDIUM
        else:
            evidence_quality = EvidenceQuality.LOW

        # 2. Agent Verdict Determination
        if evidence_quality == EvidenceQuality.INSUFFICIENT:
            verdict = AgentVerdict.INSUFFICIENT_EVIDENCE
        elif state.alternative is not None:
            verdict = AgentVerdict.ALTERNATIVE_ADVISED
        elif any(f.severity in [FindingSeverity.ALERT, FindingSeverity.WARNING] for f in state.findings) or len(state.tradeoffs) > 0:
            verdict = AgentVerdict.CONFIRMED_WITH_WARNINGS
        else:
            verdict = AgentVerdict.CONFIRMED

        # 3. Deterministic Report ID Generation (Analytical Content Hash)
        canonical_str = (
            f"{ctx.program_id}|{ctx.source_hash}|{ctx.selected_strategy}|"
            f"{verdict.value}|{evidence_quality.value}|"
            f"{len(state.findings)}|{len(state.tradeoffs)}|{state.alternative is not None}"
        )
        report_id = "w12-" + hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]

        return AgentAnalysisReport(
            schema_version=AGENTIC_SCHEMA_VERSION,
            report_id=report_id,
            program_id=ctx.program_id,
            source_hash=ctx.source_hash,
            selected_strategy=ctx.selected_strategy,
            verdict=verdict,
            evidence_quality=evidence_quality,
            tiers_available=list(ctx.tiers_available),
            findings=list(state.findings),
            tradeoffs=list(state.tradeoffs),
            alternative=state.alternative,
            reasoning_steps=list(state.steps),
            is_advisory_only=True,
            metadata=dict(ctx.metadata),
        )
