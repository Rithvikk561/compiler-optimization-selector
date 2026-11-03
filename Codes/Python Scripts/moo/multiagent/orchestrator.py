"""
moo.multiagent.orchestrator — Central Multi-Agent Workflow Coordinator for TOACD.

Coordinates specialized agents:
  CodeAnalyst -> ProgramProfiling -> Strategist <-> Reviewer (Feedback/Revision Loop)
  -> FinalDecision (Security Gate) -> Benchmark -> RunRecord Synthesis

Preserves all safety bounds:
- Bounded revisions (MAX_REVISIONS = 2)
- Monotonic step increments
- Immutable message logging
- RunRecord compatibility and deterministic execution
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..runrecord.builder import RunRecordBuilder
from ..runrecord.schema import RunRecord, RunStatus, MeasurementStatus

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
from .message_log import MessageLog
from .agents import (
    CodeAnalystAgent,
    ProgramProfilingAgent,
    OptimizationStrategistAgent,
    OptimizationReviewerAgent,
    BenchmarkAgent,
    FinalDecisionAgent,
)

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    Coordinates multi-agent compilation optimization pipeline.
    """

    MAX_REVISIONS: int = 2
    MAX_STEP_BUDGET: int = 20

    def __init__(
        self,
        code_analyst: Optional[CodeAnalystAgent] = None,
        profiling_agent: Optional[ProgramProfilingAgent] = None,
        strategist: Optional[OptimizationStrategistAgent] = None,
        reviewer: Optional[OptimizationReviewerAgent] = None,
        benchmark_agent: Optional[BenchmarkAgent] = None,
        decision_agent: Optional[FinalDecisionAgent] = None,
    ) -> None:
        self.code_analyst = code_analyst or CodeAnalystAgent()
        self.profiling_agent = profiling_agent or ProgramProfilingAgent()
        self.strategist = strategist or OptimizationStrategistAgent()
        self.reviewer = reviewer or OptimizationReviewerAgent()
        self.benchmark_agent = benchmark_agent or BenchmarkAgent()
        self.decision_agent = decision_agent or FinalDecisionAgent()

    def run(
        self,
        source_path: str,
        *,
        selected_strategy: Optional[str] = None,
        run_benchmarks: bool = True,
        run_security: bool = True,
        run_regression: bool = True,
        run_adaptive: bool = True,
        run_agentic: bool = True,
        warmup_runs: int = 1,
        measure_runs: int = 3,
        timeout_s: int = 10,
        run_id: Optional[str] = None,
        max_revisions: Optional[int] = None,
        on_message: Optional[Callable[[AgentMessage], None]] = None,
        on_stage: Optional[Callable[[str, str, Optional[Dict[str, Any]]], None]] = None,
    ) -> Tuple[RunRecord, MessageLog]:
        """
        Execute the multi-agent optimization coordination workflow.
        Returns the assembled RunRecord and the complete chronological MessageLog.
        """
        active_run_id = run_id or f"ma_{uuid.uuid4().hex[:12]}"
        log = MessageLog(run_id=active_run_id)
        current_step = 1

        def emit(msg: AgentMessage) -> None:
            log.append(msg)
            if on_message is not None:
                try:
                    on_message(msg)
                except Exception as exc:
                    logger.debug("on_message handler error: %s", exc)

        def emit_stage(stage: str, status: str, payload: Optional[Dict[str, Any]] = None) -> None:
            if on_stage is not None:
                try:
                    on_stage(stage, status, payload or {})
                except Exception as exc:
                    logger.debug("on_stage handler error: %s", exc)

        builder = RunRecordBuilder(source_path=source_path, run_id=active_run_id)
        max_rev = max_revisions if max_revisions is not None else self.MAX_REVISIONS

        # --- STEP 1: CodeAnalystAgent (Profiling Stage Start) ---
        emit_stage("profiling", "started", {"source_path": source_path})
        msg_ca = self.code_analyst.analyze(source_path, run_id=active_run_id, step=current_step)
        emit(msg_ca)
        current_step += 1

        if msg_ca.message_type == MSG_ERROR:
            emit_stage("profiling", "failed", {"error": msg_ca.payload.get("error", "CodeAnalyst failure")})
            builder.set_selection(None)
            builder.add_note(msg_ca.payload.get("error", "CodeAnalyst failure"))
            # Attach message log to notes
            builder.add_note(f"[MULTIAGENT_LOG] {log.to_json()}")
            return builder.build(), log

        ir_features = msg_ca.payload.get("ir_features")
        builder.set_ir_features(features=ir_features)

        # Toolchain check
        clang_v, opt_v, toolchain_ok, toolchain_notes = None, None, False, []
        try:
            from ..toolchain import verify_toolchain
            clang_info, opt_info, incomp = verify_toolchain()
            toolchain_ok = bool(getattr(clang_info, "found", False))
            clang_v = clang_info.version_string if getattr(clang_info, "found", False) else None
            opt_v = opt_info.version_string if getattr(opt_info, "found", False) else None
            toolchain_notes = [f"[{i.kind}] {i.detail}" for i in incomp]
            if not getattr(clang_info, "found", False):
                toolchain_notes.append("clang not found")
            if not getattr(opt_info, "found", False):
                toolchain_notes.append("opt not found")
        except Exception as exc:
            toolchain_ok = False
            toolchain_notes = [f"Toolchain probe error: {exc}"]

        builder.set_toolchain(
            clang_version=clang_v,
            opt_version=opt_v,
            toolchain_ok=toolchain_ok,
            toolchain_notes=toolchain_notes,
        )

        # --- STEP 2: ProgramProfilingAgent ---
        msg_profile = self.profiling_agent.profile(msg_ca, step=current_step)
        emit(msg_profile)
        current_step += 1

        profile_dict = msg_profile.payload.get("profile")
        builder.set_profile(profile_dict)
        emit_stage("profiling", "completed", {"features": ir_features, "profile": profile_dict})

        # --- STEP 3: OptimizationStrategistAgent Initial Proposal ---
        emit_stage("strategy_selection", "started")
        msg_proposal = self.strategist.initial_proposal(
            source_path=source_path,
            run_id=active_run_id,
            step=current_step,
            forced_strategy=selected_strategy,
        )
        emit(msg_proposal)
        current_step += 1
        emit_stage("strategy_selection", "completed", {
            "strategy": msg_proposal.payload.get("strategy"),
            "confidence": msg_proposal.payload.get("confidence"),
        })

        # --- STEP 4: Reviewer <-> Strategist Feedback Loop ---
        emit_stage("agent_review", "started")
        accepted_strategy = None
        final_proposal_payload = msg_proposal.payload
        revisions_count = 0

        current_proposal_msg = msg_proposal

        while current_step <= self.MAX_STEP_BUDGET:
            msg_review = self.reviewer.review_proposal(
                current_proposal_msg,
                step=current_step,
                ir_features=ir_features,
                program_profile=profile_dict,
            )
            emit(msg_review)
            current_step += 1

            if msg_review.message_type == MSG_REVIEW_ACCEPT:
                accepted_strategy = msg_review.payload.get("strategy")
                final_proposal_payload = current_proposal_msg.payload
                break

            elif msg_review.message_type == MSG_REVIEW_REJECT:
                revisions_count += 1
                if revisions_count > max_rev:
                    # Enforce strict revision limit: forced acceptance of current candidate
                    builder.add_note(
                        f"[MULTIAGENT_REVIEW] Max revisions ({max_rev}) exhausted; accepting '{current_proposal_msg.payload.get('strategy')}'."
                    )
                    accepted_strategy = current_proposal_msg.payload.get("strategy")
                    final_proposal_payload = current_proposal_msg.payload
                    break

                # Strategist Formulates Revision
                msg_revised = self.strategist.revise_proposal(msg_review, step=current_step)
                emit(msg_revised)
                current_step += 1
                current_proposal_msg = msg_revised
            else:
                # Unexpected message type: fail safe to proposal strategy
                accepted_strategy = current_proposal_msg.payload.get("strategy")
                final_proposal_payload = current_proposal_msg.payload
                break

        if not accepted_strategy:
            accepted_strategy = "-O0"

        emit_stage("agent_review", "completed", {
            "strategy": accepted_strategy,
            "revisions": revisions_count,
        })

        # Record selection in RunRecordBuilder
        q_rank_tuples = [
            (item[0], item[1]) for item in (final_proposal_payload.get("q_rank") or [])
        ]
        builder.set_selection(
            selected_strategy=accepted_strategy,
            decision_trace=final_proposal_payload.get("decision_trace"),
            model_id=final_proposal_payload.get("model_id"),
        )

        # --- STEP 5: FinalDecisionAgent (Security Gate) ---
        emit_stage("security_verification", "started")
        msg_final = self.decision_agent.decide(
            source_path=source_path,
            selected_strategy=accepted_strategy,
            q_rank=q_rank_tuples,
            decision_trace=final_proposal_payload.get("decision_trace"),
            run_id=active_run_id,
            step=current_step,
            run_security=run_security,
            toolchain_ok=toolchain_ok,
        )
        emit(msg_final)
        current_step += 1

        effective_strategy = msg_final.payload.get("effective_strategy") or accepted_strategy
        fallback_occurred = bool(msg_final.payload.get("fallback_occurred", False))
        gate_res = msg_final.payload.get("security_gate_result")

        if gate_res:
            builder.set_security_gate(gate_res)

        builder.set_effective_strategy(effective_strategy, fallback_occurred=fallback_occurred)
        for n in msg_final.payload.get("notes") or []:
            builder.add_note(n)

        sec_verdict = gate_res.get("decision") if isinstance(gate_res, dict) else (
            getattr(gate_res, "decision", "PASS") if gate_res else "PASS"
        )
        if sec_verdict in ("BLOCK", "BLOCKED", "REJECT") and not fallback_occurred:
            emit_stage("security_verification", "blocked", {
                "effective_strategy": effective_strategy,
                "fallback_occurred": False,
                "verdict": sec_verdict,
            })
        else:
            emit_stage("security_verification", "completed", {
                "effective_strategy": effective_strategy,
                "fallback_occurred": fallback_occurred,
                "verdict": sec_verdict,
            })

        # --- STEP 6: BenchmarkAgent ---
        moo_result = None
        if run_benchmarks and effective_strategy and toolchain_ok:
            emit_stage("benchmarking", "started", {"strategy": effective_strategy})
            msg_bench = self.benchmark_agent.benchmark(
                source_path=source_path,
                strategy=effective_strategy,
                run_id=active_run_id,
                step=current_step,
                warmup_runs=warmup_runs,
                measure_runs=measure_runs,
                timeout_s=timeout_s,
            )
            emit(msg_bench)
            current_step += 1

            if msg_bench.payload.get("status") == "OK" and msg_bench.payload.get("moo_result"):
                raw_mr = msg_bench.payload.get("moo_result")
                builder.set_moo_result(raw_mr)
                builder.set_optimized_from_moo(raw_mr, effective_strategy)
                moo_result = raw_mr
                base_reliable = raw_mr.get("baseline", {}).get("timing_is_reliable", True) if isinstance(raw_mr.get("baseline"), dict) else True
                opt_reliable = raw_mr.get("optimized", {}).get("timing_is_reliable", True) if isinstance(raw_mr.get("optimized"), dict) else True
                timing_reliable = (base_reliable is not False and opt_reliable is not False)
                emit_stage("benchmarking", "completed", {
                    "strategy": effective_strategy,
                    "status": "OK",
                    "timing_is_reliable": timing_reliable,
                })
            else:
                err_msg = msg_bench.payload.get("error") or "Benchmark failure"
                builder.set_baseline_measurement(None, error=err_msg)
                builder.set_optimized_measurement(effective_strategy, None, error=err_msg)
                emit_stage("benchmarking", "failed", {"error": err_msg})
        elif not toolchain_ok:
            builder.set_baseline_measurement(None, error="Toolchain not available")
            builder.set_optimized_measurement(effective_strategy or "unknown", None, error="Toolchain not available")
            emit_stage("benchmarking", "skipped", {"reason": "Toolchain not available"})
        else:
            emit_stage("benchmarking", "skipped", {"reason": "Benchmarks disabled"})

        # --- STEP 7: Downstream Regression Comparison ---
        prog_comp = None
        baseline_is_ok = False
        if moo_result is not None:
            if isinstance(moo_result, dict):
                baseline_is_ok = bool(moo_result.get("baseline", {}).get("build_ok", False))
            else:
                baseline_is_ok = bool(getattr(getattr(moo_result, "baseline", None), "build_ok", False))

        if run_regression and baseline_is_ok and effective_strategy:
            emit_stage("regression_analysis", "started")
            try:
                from ..regression.comparator import compare_program
                from ..regression.schema import SelectionRecord
                moo_dict = dict(moo_result) if isinstance(moo_result, dict) else moo_result.to_dict()
                pid = os.path.splitext(os.path.basename(source_path))[0]
                moo_dict["program_id"] = pid
                sha = moo_dict.get("source_sha256") or "unknown_sha"
                sel_rec = SelectionRecord(
                    program_id=pid,
                    source_sha256=sha,
                    selected_strategy=effective_strategy,
                    selection_source=(
                        "security_gate_fallback"
                        if fallback_occurred
                        else ("multiagent_revision" if revisions_count > 0 else "DQN_MOO")
                    ),
                )
                prog_comp = compare_program(moo_dict, selected_strategy=effective_strategy, selection_record=sel_rec)
                builder.set_regression(prog_comp)
                emit_stage("regression_analysis", "completed", {
                    "overall_status": prog_comp.overall_status.value if hasattr(prog_comp.overall_status, "value") else str(prog_comp.overall_status),
                })
            except Exception as exc:
                builder.add_note(f"Regression comparison error: {exc}")
                emit_stage("regression_analysis", "failed", {"error": str(exc)})
        else:
            emit_stage("regression_analysis", "skipped", {
                "reason": "Regression analysis skipped (benchmarks missing or disabled)"
            })

        # --- STEP 8: Downstream Adaptive Learning (Advisory Only) ---
        if run_adaptive and prog_comp is not None and ir_features and not fallback_occurred:
            try:
                from ..adaptive.adapter import experience_from_program_comparison
                exp_rec = experience_from_program_comparison(
                    prog_comp,
                    features=ir_features,
                    decision_trace=final_proposal_payload.get("decision_trace"),
                )
                if exp_rec:
                    builder.set_adaptive(exp_rec)
            except Exception as exc:
                builder.add_note(f"Adaptive learning error: {exc}")

        # --- STEP 9: Downstream Agentic AI Analysis (Advisory Only) ---
        if run_agentic and effective_strategy:
            try:
                from ..agentic import analyze_compilation
                from ..runrecord.builder import _sha256_of_file
                pid = os.path.splitext(os.path.basename(source_path))[0]
                sha = _sha256_of_file(source_path) or "unknown_sha"

                effective_prog_comp = None if fallback_occurred else (
                    prog_comp.to_dict() if hasattr(prog_comp, "to_dict") else prog_comp
                )

                rep = analyze_compilation(
                    program_id=pid,
                    source_hash=sha,
                    selected_strategy=effective_strategy,
                    decision_trace=final_proposal_payload.get("decision_trace"),
                    program_profile=profile_dict,
                    program_comparison=effective_prog_comp,
                )
                if rep:
                    builder.set_agentic(rep)
            except Exception as exc:
                builder.add_note(f"Agentic AI analysis error: {exc}")

        # Attach chronological multiagent message log in notes for GUI / downstream retrieval
        builder.add_note(f"[MULTIAGENT_LOG] {log.to_json()}")

        return builder.build(), log
