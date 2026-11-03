"""
moo.multiagent.agents — Specialized Deterministic Agents for TOACD.

Implements the 6 primary domain agents:
1. CodeAnalystAgent: Extracts 8 IR features and checks source code security.
2. ProgramProfilingAgent: Produces deterministic rule-based program profile.
3. OptimizationStrategistAgent: Uses DQN + MOO selector; handles revisions based on Reviewer feedback.
4. OptimizationReviewerAgent: Evaluates proposals using provenance & profile diagnostics; provides feedback.
5. BenchmarkAgent: Executes empirical measurements without fabrication.
6. FinalDecisionAgent: Enforces OptimizationSecurityGate and generates advisory Agentic report.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    AgentMessage,
    MessageType,
    ROLE_CODE_ANALYST,
    ROLE_PROGRAM_PROFILING,
    ROLE_OPTIMIZATION_STRATEGIST,
    ROLE_OPTIMIZATION_REVIEWER,
    ROLE_BENCHMARK,
    ROLE_FINAL_DECISION,
    ROLE_ORCHESTRATOR,
    MSG_IR_FEATURES,
    MSG_PROFILE,
    MSG_STRATEGY_PROPOSAL,
    MSG_REVIEW_ACCEPT,
    MSG_REVIEW_REJECT,
    MSG_STRATEGY_REVISED,
    MSG_BENCHMARK_RESULT,
    MSG_FINAL_DECISION,
    MSG_ERROR,
)

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base class for all multi-agent components in TOACD."""

    def __init__(self, name: str) -> None:
        self.name: str = name

    def process(self, incoming: AgentMessage, step: int) -> AgentMessage:
        """Process an incoming message and return an outgoing message response."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. CodeAnalystAgent
# ---------------------------------------------------------------------------
class CodeAnalystAgent(BaseAgent):
    """
    Analyzes C source programs:
    - Extracts 8 canonical LLVM IR features via CompilerEnv
    - Performs static source security scanning via scan_source
    """

    def __init__(self, name: str = ROLE_CODE_ANALYST) -> None:
        super().__init__(name)

    def analyze(self, source_path: str, run_id: str, step: int) -> AgentMessage:
        if not source_path or not os.path.isfile(source_path):
            return AgentMessage.create(
                sender=self.name,
                recipient=ROLE_ORCHESTRATOR,
                message_type=MSG_ERROR,
                payload={
                    "error": f"Source file not found: {source_path!r}",
                    "stage": "code_analysis",
                    "recoverable": False,
                },
                run_id=run_id,
                step=step,
            )

        ir_features: Optional[Dict[str, float]] = None
        raw_feats: List[float] = []
        source_findings: List[Dict[str, Any]] = []

        # 1. IR Feature extraction
        try:
            from ml_optimizer import CompilerEnv
            from ..xai import format_ir_features

            env = CompilerEnv(source_path)
            raw_feats = (
                env.features.tolist()
                if hasattr(env.features, "tolist")
                else list(env.features)
            )
            ir_features = format_ir_features(raw_feats)
        except Exception as exc:
            logger.warning(f"[{self.name}] IR feature extraction error: {exc}")

        # 2. Source security scan
        try:
            from ..security.source_scan import scan_source
            findings = scan_source(source_path)
            for f in findings:
                source_findings.append({
                    "category": getattr(f, "category", "UNKNOWN"),
                    "pattern_id": getattr(f, "pattern_id", "UNKNOWN"),
                    "line": getattr(f, "line", 0),
                    "description": getattr(f, "description", ""),
                })
        except Exception as exc:
            logger.warning(f"[{self.name}] Source scan error: {exc}")

        if ir_features is None:
            # Fallback safe features
            ir_features = {f"feat_{i}": 0.0 for i in range(8)}

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_IR_FEATURES,
            payload={
                "source_path": source_path,
                "ir_features": ir_features,
                "raw_features": raw_feats,
                "source_findings": source_findings,
            },
            run_id=run_id,
            step=step,
        )


# ---------------------------------------------------------------------------
# 2. ProgramProfilingAgent
# ---------------------------------------------------------------------------
class ProgramProfilingAgent(BaseAgent):
    """
    Classifies programs using deterministic IR instruction-ratio heuristics.
    Reuses existing moo.program_profiler.profile_program.
    """

    def __init__(self, name: str = ROLE_PROGRAM_PROFILING) -> None:
        super().__init__(name)

    def profile(self, ir_message: AgentMessage, step: int) -> AgentMessage:
        raw_features = ir_message.payload.get("raw_features") or []
        profile_dict = None

        try:
            from ..program_profiler import profile_program

            prof = profile_program(raw_features)
            if prof is not None:
                profile_dict = prof.to_dict()
        except Exception as exc:
            logger.warning(f"[{self.name}] Profiler error: {exc}")

        if profile_dict is None:
            profile_dict = {
                "label": "unknown",
                "dominant_feature": "None",
                "dominant_feature_value": 0.0,
                "is_trivial": False,
                "profile_method": "fallback_error",
            }

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_PROFILE,
            payload={"profile": profile_dict},
            run_id=ir_message.run_id,
            step=step,
        )


# ---------------------------------------------------------------------------
# 3. OptimizationStrategistAgent
# ---------------------------------------------------------------------------
class OptimizationStrategistAgent(BaseAgent):
    """
    Proposes compiler optimization pipelines using DQN Q-values & MOO filtering.
    Listens to OptimizationReviewerAgent feedback and formulates revisions.
    """

    def __init__(self, name: str = ROLE_OPTIMIZATION_STRATEGIST) -> None:
        super().__init__(name)
        self.cached_q_rank: List[Tuple[str, float]] = []
        self.tried_strategies: List[str] = []
        self.current_trace: Optional[Any] = None
        self.current_xai: Optional[Any] = None
        self.model_id: str = "production_v0"

    def initial_proposal(
        self,
        source_path: str,
        run_id: str,
        step: int,
        forced_strategy: Optional[str] = None,
    ) -> AgentMessage:
        """Formulate initial candidate optimization strategy proposal."""
        self.tried_strategies = []
        self.cached_q_rank = []

        chosen_strategy: Optional[str] = forced_strategy
        provenance = "MANUAL" if forced_strategy else "UNKNOWN"
        trace_dict: Optional[Dict[str, Any]] = None
        xai_dict: Optional[Dict[str, Any]] = None

        if forced_strategy is None:
            try:
                from optimization_selector import select_with_provenance

                sel = select_with_provenance(source_path)
                if sel and sel.strategy:
                    chosen_strategy = sel.strategy
                    provenance = sel.provenance
                    self.model_id = sel.model_id
                    self.cached_q_rank = getattr(sel, "q_rank", []) or []
                    self.current_trace = sel.decision_trace
                    self.current_xai = sel.xai_result

                    if sel.decision_trace is not None:
                        trace_dict = (
                            sel.decision_trace.to_dict()
                            if hasattr(sel.decision_trace, "to_dict")
                            else dict(sel.decision_trace)
                        )
                    if sel.xai_result is not None:
                        xai_dict = (
                            sel.xai_result.to_dict()
                            if hasattr(sel.xai_result, "to_dict")
                            else dict(sel.xai_result)
                        )
            except Exception as exc:
                logger.warning(f"[{self.name}] Selection failed: {exc}")
                chosen_strategy = "-O2"
                provenance = "FALLBACK"
        else:
            chosen_strategy = forced_strategy
            provenance = "MANUAL"

        if not chosen_strategy:
            chosen_strategy = "-O0"
            provenance = "FALLBACK"

        self.tried_strategies.append(chosen_strategy)

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_OPTIMIZATION_REVIEWER,
            message_type=MSG_STRATEGY_PROPOSAL,
            payload={
                "strategy": chosen_strategy,
                "provenance": provenance,
                "model_id": self.model_id,
                "decision_trace": trace_dict,
                "xai_result": xai_dict,
                "q_rank": [list(pair) for pair in self.cached_q_rank],
                "revision_number": 0,
            },
            run_id=run_id,
            step=step,
        )

    def revise_proposal(
        self,
        rejection_msg: AgentMessage,
        step: int,
    ) -> AgentMessage:
        """Formulate a revised proposal based on Reviewer's rejection feedback."""
        prev_revision = int(rejection_msg.payload.get("revision_number", 0))
        feedback = rejection_msg.payload.get("feedback", "")
        rejected_strategy = rejection_msg.payload.get("strategy")

        next_candidate: Optional[str] = None
        # Select next highest Q candidate not yet tried
        for s, q in self.cached_q_rank:
            if s not in self.tried_strategies:
                next_candidate = s
                break

        # Fallback to standard safe progression if q_rank exhausted
        if not next_candidate:
            standard_ladder = ["-O2", "-O1", "-Os", "-O3", "-O0"]
            for s in standard_ladder:
                if s not in self.tried_strategies:
                    next_candidate = s
                    break

        if not next_candidate:
            next_candidate = "-O0"

        self.tried_strategies.append(next_candidate)
        new_rev = prev_revision + 1

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_OPTIMIZATION_REVIEWER,
            message_type=MSG_STRATEGY_REVISED,
            payload={
                "strategy": next_candidate,
                "provenance": "REVISED_BY_REVIEWER_FEEDBACK",
                "model_id": self.model_id,
                "decision_trace": self.current_trace.to_dict() if hasattr(self.current_trace, "to_dict") else None,
                "xai_result": self.current_xai.to_dict() if hasattr(self.current_xai, "to_dict") else None,
                "q_rank": [list(pair) for pair in self.cached_q_rank],
                "revision_number": new_rev,
                "revising_strategy": rejected_strategy,
                "rejection_feedback_addressed": feedback,
            },
            run_id=rejection_msg.run_id,
            step=step,
        )


# ---------------------------------------------------------------------------
# 4. OptimizationReviewerAgent
# ---------------------------------------------------------------------------
class OptimizationReviewerAgent(BaseAgent):
    """
    Audits proposed strategies before benchmarking.
    Runs audit_provenance_tool and analyze_ir_profile_tool from Week 12.
    Rejects with structured feedback if ALERT severity findings are detected,
    or accepts when sound.
    """

    def __init__(self, name: str = ROLE_OPTIMIZATION_REVIEWER) -> None:
        super().__init__(name)

    def review_proposal(
        self,
        proposal_msg: AgentMessage,
        step: int,
        ir_features: Optional[Dict[str, float]] = None,
        program_profile: Optional[Dict[str, Any]] = None,
    ) -> AgentMessage:
        payload = proposal_msg.payload
        strategy = payload.get("strategy", "")
        decision_trace = payload.get("decision_trace")
        revision_number = payload.get("revision_number", 0)

        findings: List[Dict[str, Any]] = []
        has_alert = False

        # Run Week 12 tools if available
        try:
            from ..agentic.schema import AgentContext, EvidenceTier
            from ..agentic.tools import audit_provenance_tool, analyze_ir_profile_tool

            tiers = [EvidenceTier.TIER_1_STATIC_SELECTION]
            context = AgentContext(
                program_id="candidate",
                source_hash="",
                selected_strategy=strategy,
                tiers_available=tiers,
                decision_trace=decision_trace,
                program_profile=program_profile,
            )

            prov_findings = audit_provenance_tool(context)
            prof_findings = analyze_ir_profile_tool(context)

            for f in prov_findings + prof_findings:
                f_dict = f.to_dict()
                findings.append(f_dict)
                if f.severity.value == "ALERT":
                    has_alert = True
        except Exception as exc:
            logger.warning(f"[{self.name}] Reviewer diagnostic execution error: {exc}")

        # Check explicit fallback mismatch alert if trace final_strategy conflicts with proposal
        if decision_trace and isinstance(decision_trace, dict):
            final_strat = decision_trace.get("final_strategy")
            if final_strat and final_strat != strategy and payload.get("provenance") != "REVISED_BY_REVIEWER_FEEDBACK":
                has_alert = True
                findings.append({
                    "category": "PROVENANCE",
                    "severity": "ALERT",
                    "message": f"Proposal strategy '{strategy}' conflicts with DecisionTrace final_strategy '{final_strat}'.",
                })

        if has_alert:
            # Reject with meaningful feedback
            feedback_reasons = [f["message"] for f in findings if f.get("severity") == "ALERT"]
            feedback_str = "; ".join(feedback_reasons)
            return AgentMessage.create(
                sender=self.name,
                recipient=ROLE_OPTIMIZATION_STRATEGIST,
                message_type=MSG_REVIEW_REJECT,
                payload={
                    "strategy": strategy,
                    "findings": findings,
                    "feedback": feedback_str,
                    "revision_number": revision_number,
                    "decision": "REJECT",
                },
                run_id=proposal_msg.run_id,
                step=step,
            )

        # Accept proposal
        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_REVIEW_ACCEPT,
            payload={
                "strategy": strategy,
                "findings": findings,
                "revision_number": revision_number,
                "decision": "ACCEPT",
            },
            run_id=proposal_msg.run_id,
            step=step,
        )


# ---------------------------------------------------------------------------
# 5. BenchmarkAgent
# ---------------------------------------------------------------------------
class BenchmarkAgent(BaseAgent):
    """
    Executes empirical performance evaluation for baseline (-O0) and accepted strategy.
    Delegates to moo.pipeline.evaluate_program; never fabricates measurements.
    """

    def __init__(self, name: str = ROLE_BENCHMARK) -> None:
        super().__init__(name)

    def benchmark(
        self,
        source_path: str,
        strategy: str,
        run_id: str,
        step: int,
        warmup_runs: int = 1,
        measure_runs: int = 3,
        timeout_s: int = 10,
    ) -> AgentMessage:
        moo_result = None
        bench_error = None
        status = "OK"

        try:
            from ..pipeline import evaluate_program

            moo_result = evaluate_program(
                source_path=source_path,
                actions=[strategy],
                warmup_runs=warmup_runs,
                measure_runs=measure_runs,
                timeout_s=timeout_s,
            )
        except Exception as exc:
            bench_error = str(exc)
            status = "FAILED"
            logger.warning(f"[{self.name}] Benchmark execution error: {exc}")

        result_dict: Optional[Dict[str, Any]] = (
            moo_result.to_dict() if moo_result is not None else None
        )

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_BENCHMARK_RESULT,
            payload={
                "strategy": strategy,
                "status": status,
                "error": bench_error,
                "moo_result": result_dict,
            },
            run_id=run_id,
            step=step,
        )


# ---------------------------------------------------------------------------
# 6. FinalDecisionAgent
# ---------------------------------------------------------------------------
class FinalDecisionAgent(BaseAgent):
    """
    Consolidates accepted proposal with the OptimizationSecurityGate.
    Ensures safe effective_strategy and executes advisory Agentic AI analysis.
    """

    def __init__(self, name: str = ROLE_FINAL_DECISION) -> None:
        super().__init__(name)

    def decide(
        self,
        source_path: str,
        selected_strategy: str,
        q_rank: List[Tuple[str, float]],
        decision_trace: Optional[Dict[str, Any]],
        run_id: str,
        step: int,
        run_security: bool = True,
        toolchain_ok: bool = True,
    ) -> AgentMessage:
        effective_strategy = selected_strategy
        fallback_occurred = False
        security_gate_result = None
        gate_events = []
        notes = []

        # Optimization Security Gate (Week 13A/14)
        if run_security and selected_strategy and toolchain_ok:
            try:
                from ..security.gate import OptimizationSecurityGate
                from ..toolchain import CLANG_PATH, OPT_PATH

                # MOO-invalid constraint filter on gate_q_rank
                gate_q_rank = q_rank
                if q_rank and decision_trace:
                    invalid = set(decision_trace.get("pareto_invalid") or [])
                    gate_q_rank = [
                        (name, q) for (name, q) in q_rank
                        if (name not in invalid) or (name == selected_strategy)
                    ]

                gate = OptimizationSecurityGate(clang_path=CLANG_PATH, opt_path=OPT_PATH)
                gate_res = gate.run_gate(
                    source_path=source_path,
                    selected_strategy=selected_strategy,
                    q_rank=gate_q_rank,
                    run_id=run_id,
                )
                security_gate_result = gate_res.to_dict() if gate_res else None
                if gate_res:
                    effective_strategy = gate_res.effective_strategy
                    fallback_occurred = gate_res.fallback_occurred
                    gate_events = [e.to_dict() for e in gate_res.security_events]
                    if fallback_occurred:
                        notes.append(
                            f"Security Gate triggered fallback: original {selected_strategy} -> effective {effective_strategy}"
                        )
            except Exception as exc:
                effective_strategy = "-O0"
                fallback_occurred = True
                notes.append(f"Security gate exception: {exc}; fail closed to -O0")
                security_gate_result = {
                    "decision": "FALLBACK",
                    "effective_strategy": "-O0",
                    "original_strategy": selected_strategy,
                    "fallback_occurred": True,
                    "unverified": True,
                    "notes": notes,
                }

        return AgentMessage.create(
            sender=self.name,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_FINAL_DECISION,
            payload={
                "selected_strategy": selected_strategy,
                "effective_strategy": effective_strategy,
                "fallback_occurred": fallback_occurred,
                "security_gate_result": security_gate_result,
                "security_events": gate_events,
                "notes": notes,
            },
            run_id=run_id,
            step=step,
        )
