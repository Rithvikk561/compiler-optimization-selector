"""
moo/runrecord/orchestrator.py — Pipeline orchestrator connecting Week 8–12 modules via RunRecord.

The PipelineOrchestrator is the production integration point that:
  1. Receives a source file path and optional artifacts
  2. Orchestrates existing Week 8–12 modules in the correct data flow order
  3. Constructs a canonical RunRecord from all available artifacts
  4. Returns the RunRecord (with optional persistence)

IMPORTANT SCOPE RESTRICTIONS
-----------------------------
- Does NOT rewrite any existing Week 8–12 modules.
- Does NOT implement Week 13+ features.
- Does NOT modify any existing APIs.
- Does NOT override optimization selection.
- Agentic AI remains advisory-only.
- Adaptive learning remains advisory-only.
- No background daemons, no async.
- No network/cloud/LLM.

Data Flow
---------
  source_path
       ↓
  [optional] feature extraction / profile
       ↓
  [optional] optimization selection (selector_bridge)
       ↓
  [optional] DecisionTrace (via moo_aware_select_with_trace)
       ↓
  [optional] MOO pipeline (pipeline.evaluate_program)
       ↓
  RunRecordBuilder → RunRecord
       ↓
  [optional] regression comparison
       ↓
  [optional] adaptive experience
       ↓
  [optional] agentic analysis
       ↓
  RunRecord (final)

Usage
-----
    orch = PipelineOrchestrator()

    # Build RunRecord from already-computed artifacts
    record = orch.build_from_artifacts(
        source_path="...",
        program_profile=profile,
        selection_result=sel_result,
        decision_trace=trace,
        moo_result=moo_result,
        program_comparison=comparison,
        security_result=security,
        agent_report=agent_report,
        experience_record=exp_record,
    )

    # Or run a selection-only RunRecord (no benchmark)
    record = orch.build_from_selection(
        source_path="...",
        ir_features={...},
        program_profile=profile,
    )
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional

from .builder import RunRecordBuilder
from .schema import RunRecord, RunStatus, MeasurementStatus


class PipelineOrchestrator:
    """
    Connects existing Week 8–12 modules via the RunRecord layer.

    Provides:
    a) execute_pipeline(source_path): runs the live end-to-end production flow
    b) build_from_artifacts(...): assembles RunRecord from pre-computed artifacts
    c) build_from_selection(...): selection-only RunRecord (no benchmark)

    The orchestrator does NOT duplicate existing pipeline logic.
    It delegates to existing modules and captures their outputs.
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        """
        Parameters
        ----------
        persist_dir : optional directory for RunRecord JSON persistence.
                      If None, RunRecords are only returned in memory.
                      Set to a specific directory to save .json files.
        """
        self._persist_dir = persist_dir

    # ----------------------------------------------------------------
    # Live Production Execution Pipeline
    # ----------------------------------------------------------------

    def execute_pipeline(
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
    ) -> RunRecord:
        """
        Execute the live end-to-end production flow:
          Source -> Toolchain -> Security -> Profile -> Selection -> Benchmark
                 -> RunRecord -> Regression -> Adaptive -> Agentic

        Returns the canonical RunRecord representing this complete run.
        Never inserts fake zeros or fabricated success.
        """
        builder = RunRecordBuilder(source_path=source_path, run_id=run_id)

        # 1. Source existence check
        if not source_path or not os.path.isfile(source_path):
            builder.set_selection(None)
            builder.add_note(f"Source file not found: {source_path!r}")
            return builder.build()

        # 2. Toolchain check
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

        # 3. Secure Code Analysis & 13B Input Security Screening
        source_comments = []
        screened_comments_count = 0
        screening_events_count = 0
        screening_blocked_count = 0
        screening_error = None
        comment_screening_performed = False

        if run_security:
            try:
                from ..security.source_scan import scan_source
                from ..security.models import CandidateSecurity, CandidateVerdict
                findings = scan_source(source_path)
                has_hazards = any(getattr(f, "category", "") == "HAZARD" for f in findings)
                has_guards = any(getattr(f, "category", "") == "GUARD" for f in findings)
                if has_hazards:
                    sec_verdict = CandidateVerdict.REDUCED
                elif has_guards:
                    sec_verdict = CandidateVerdict.PRESERVED
                else:
                    sec_verdict = CandidateVerdict.NOT_APPLICABLE

                sec_result = CandidateSecurity(
                    strategy_name="source_scan",
                    verdict=sec_verdict,
                    notes=[
                        f"Source findings: {len(findings)}",
                        "scope=SOURCE_SCAN; not an optimization-candidate verdict",
                    ],
                )
                builder.set_security(sec_result)
            except Exception as exc:
                builder.add_note(f"Security analysis error: {exc}")

            # 13B Input Screening: Extract and screen source comments and program identifier
            try:
                from ..agentic_security.input_screen import extract_c_comments
                from ..agentic_security.schema import SimulatedAgentRequest, SimulatedChannel
                from ..agentic_security.guard import AgenticSecurityGuard
                with open(source_path, "r", encoding="utf-8", errors="replace") as f_src:
                    source_content = f_src.read()
                source_comments = extract_c_comments(source_content)
                comment_screening_performed = True
                screened_comments_count = len(source_comments)
                sec_guard = AgenticSecurityGuard()
                for c_idx, comment in enumerate(source_comments):
                    req = SimulatedAgentRequest(
                        request_id=f"comment_{c_idx}",
                        channel=SimulatedChannel.SOURCE_COMMENT,
                        text=comment,
                    )
                    gres = sec_guard.screen_request(req, run_id=run_id)
                    if gres.events:
                        screening_events_count += len(gres.events)
                        screening_blocked_count += sum(1 for e in gres.events if getattr(e, "blocked", False))
                        builder.add_security_events(gres.events)
            except Exception as exc:
                screening_error = str(exc)
                builder.add_note(f"Source comment security screening error: {exc}")

        # 4. IR feature extraction & Program Profile (Week 7/8)
        ir_features = None
        profile = None
        try:
            from ml_optimizer import CompilerEnv
            from ..program_profiler import profile_program
            from ..xai import format_ir_features
            env = CompilerEnv(source_path)
            raw_feats = env.features.tolist() if hasattr(env.features, "tolist") else list(env.features)
            ir_features = format_ir_features(raw_feats)
            profile = profile_program(raw_feats)
            builder.set_ir_features(features=ir_features)
            builder.set_profile(profile)
        except Exception as exc:
            builder.add_note(f"Feature/Profile extraction error: {exc}")

        # 5. Optimization Selection with Provenance
        chosen_strategy = selected_strategy
        decision_trace = None
        model_id = "production_v0"
        q_rank = None

        if chosen_strategy is None:
            try:
                from optimization_selector import select_with_provenance
                sel = select_with_provenance(source_path)
                if sel and sel.strategy:
                    chosen_strategy = sel.strategy
                    decision_trace = sel.decision_trace
                    model_id = sel.model_id
                    q_rank = getattr(sel, "q_rank", None)
                    builder.set_selection(
                        selected_strategy=chosen_strategy,
                        decision_trace=decision_trace,
                        model_id=model_id,
                    )
                else:
                    builder.set_selection(selected_strategy=None)
            except Exception as exc:
                builder.add_note(f"Optimization selection error: {exc}")
                builder.set_selection(selected_strategy=None)
        else:
            builder.set_selection(selected_strategy=chosen_strategy, model_id=model_id)

        # 5b. Week 13A/14 Optimization Security Gate & Fallback Ladder
        effective_strategy = chosen_strategy
        fallback_occurred = False

        # MOO-invalid constraint (W14 minimal/intentional)
        # Fallback is security-driven; pareto_invalid strategies are known build/correctness
        # failures. Exclude them from fallback ladder candidates, except if already chosen.
        # Dominated strategies are intentionally NOT excluded; ladder is not restricted to frontier.
        # -O0 always remains terminal fallback. gate.py is unchanged.
        gate_q_rank = q_rank
        if q_rank and decision_trace is not None:
            invalid = set(
                getattr(decision_trace, "pareto_invalid", None)
                or (decision_trace.get("pareto_invalid") if isinstance(decision_trace, dict) else [])
                or []
            )
            filtered_q_rank = [
                (name, q) for (name, q) in q_rank
                if (name not in invalid) or (name == chosen_strategy)
            ]
            excluded = [name for (name, _) in q_rank if name in invalid and name != chosen_strategy]
            if excluded:
                builder.add_note(f"[W14-FALLBACK] q_rank candidates excluded as MOO-invalid: {excluded}")
            gate_q_rank = filtered_q_rank

        if run_security and chosen_strategy and toolchain_ok:
            try:
                from ..security.gate import OptimizationSecurityGate, GateDecision
                from ..toolchain import CLANG_PATH, OPT_PATH
                gate = OptimizationSecurityGate(clang_path=CLANG_PATH, opt_path=OPT_PATH)
                gate_res = gate.run_gate(
                    source_path=source_path,
                    selected_strategy=chosen_strategy,
                    q_rank=gate_q_rank,
                    run_id=run_id,
                )
                if not gate_res or not isinstance(getattr(gate_res, "effective_strategy", None), str) or not gate_res.effective_strategy:
                    raise ValueError(f"Security gate returned invalid result or empty effective_strategy: {gate_res}")

                builder.set_security_gate(gate_res)
                if gate_res.security_events:
                    builder.add_security_events(gate_res.security_events)

                effective_strategy = gate_res.effective_strategy
                if gate_res.fallback_occurred:
                    builder.add_note(
                        f"Security Gate triggered fallback: original {chosen_strategy} -> effective {effective_strategy}"
                    )
            except Exception as exc:
                effective_strategy = "-O0"
                gate_events = []
                try:
                    from ..secevent.schema import (
                        ThreatDomain,
                        AttackType,
                        EventSource,
                        ActionAttempted,
                        ActionTaken,
                        SecurityEvent,
                    )
                    from ..secevent.risk import Signal, compute_risk_assessment
                    from ..secevent.log import SecurityEventLog

                    sig = Signal("G_EXC", "gate_exception", 8, 0.90, evidence=str(exc)[:256])
                    risk = compute_risk_assessment([sig])
                    seq = SecurityEventLog().next_sequence()
                    evt = SecurityEvent.create(
                        sequence=seq,
                        threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
                        attack_type=AttackType.GUARD_ERROR,
                        source=EventSource.OPTIMIZATION_SECURITY_GATE,
                        risk_level=risk.risk_level,
                        score=risk.score,
                        confidence=risk.confidence,
                        evidence=f"Gate exception: {exc}",
                        action_attempted=ActionAttempted.UNKNOWN_ACTION,
                        action_taken=ActionTaken.BLOCK,
                        blocked=True,
                        reason=f"Security gate failed closed on exception ({type(exc).__name__}: {exc})",
                        affected_run_id=run_id,
                        policy_rules=["VERIFICATION_INTEGRITY_FAIL_CLOSED"],
                    )
                    gate_events.append(evt)
                    builder.add_security_events([evt])
                except Exception as evt_exc:
                    builder.add_note(f"[W14-SECURITY] Failed to construct fail-closed SecurityEvent: {evt_exc}")

                from ..security.gate import GateDecision
                synthetic_gate = {
                    "decision": GateDecision.FALLBACK.value,
                    "effective_strategy": "-O0",
                    "original_strategy": chosen_strategy,
                    "candidate_security": None,
                    "fallback_occurred": True,
                    "fallback_history": [chosen_strategy, "-O0"],
                    "unverified": True,
                    "security_events": [e.to_dict() for e in gate_events],
                    "notes": [f"Security gate exception: {exc}"],
                    "gate_exception": str(type(exc).__name__),
                    "gate_error": str(exc),
                }
                builder.set_security_gate(synthetic_gate)
                builder.add_note(
                    f"[W14-SECURITY] Security gate failed ({type(exc).__name__}: {exc}); failing closed: original {chosen_strategy} -> effective -O0"
                )
        elif chosen_strategy:
            effective_strategy = chosen_strategy
            if not run_security:
                builder.add_note("Optimization security gate skipped: run_security=False")
            elif not toolchain_ok:
                builder.add_note("Optimization security gate skipped: toolchain unavailable")

        if chosen_strategy:
            fallback_occurred = (effective_strategy != chosen_strategy)
            builder.set_effective_strategy(effective_strategy, fallback_occurred)

        if fallback_occurred:
            builder.add_note(
                f"[W14-PROVENANCE] XAI/DecisionTrace describe the original selection {chosen_strategy}; the security gate substituted effective strategy {effective_strategy}."
            )

        # 6. Compilation & Benchmark Execution (using effective_strategy)
        moo_result = None
        if run_benchmarks and effective_strategy and toolchain_ok:
            try:
                from ..pipeline import evaluate_program
                moo_result = evaluate_program(
                    source_path=source_path,
                    actions=[effective_strategy],
                    warmup_runs=warmup_runs,
                    measure_runs=measure_runs,
                    timeout_s=timeout_s,
                )
                builder.set_moo_result(moo_result)
                builder.set_optimized_from_moo(moo_result, effective_strategy)
            except Exception as exc:
                builder.set_baseline_measurement(None, error=f"Benchmark execution error: {exc}")
                builder.set_optimized_measurement(effective_strategy, None, error=f"Benchmark execution error: {exc}")
        elif not toolchain_ok:
            builder.set_baseline_measurement(None, error="Toolchain not available")
            builder.set_optimized_measurement(effective_strategy or "unknown", None, error="Toolchain not available")

        # 7. Downstream: Week 10 Regression Comparison
        prog_comp = None
        if (
            run_regression
            and moo_result is not None
            and moo_result.baseline
            and moo_result.baseline.build_ok
            and effective_strategy
        ):
            try:
                from ..regression.comparator import compare_program
                from ..regression.schema import SelectionRecord
                moo_dict = moo_result.to_dict()
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
                        else ("DQN∩Pareto" if builder._selection_provenance.value == "DQN_MOO" else "DQN_fallback")
                    ),
                )
                prog_comp = compare_program(moo_dict, selected_strategy=effective_strategy, selection_record=sel_rec)
                builder.set_regression(prog_comp)
            except Exception as exc:
                builder.add_note(f"Regression comparison error: {exc}")

        # 8. Downstream: Week 11 Adaptive Learning (Advisory Only)
        # CRITICAL: If fallback occurred, adaptive learning must NOT credit the rejected model selection
        exp_rec = None
        if run_adaptive and prog_comp is not None and ir_features and not fallback_occurred:
            try:
                from ..adaptive.adapter import experience_from_program_comparison
                exp_rec = experience_from_program_comparison(
                    prog_comp,
                    features=ir_features,
                    decision_trace=decision_trace,
                )
                if exp_rec:
                    builder.set_adaptive(exp_rec)
            except Exception as exc:
                builder.add_note(f"Adaptive learning error: {exc}")
        elif fallback_occurred:
            builder.add_note("[W14-ADAPTIVE] Adaptive learning skipped because security gate rejected original candidate")

        # 9. Downstream: Week 12 Agentic AI Analysis (Advisory Only)
        output_val_performed = False
        output_val_result = "NOT_RUN"
        output_val_expected_strat = None
        output_val_reason = None
        report_quarantined = False

        if run_agentic and effective_strategy:
            try:
                from ..agentic import analyze_compilation
                from .builder import _sha256_of_file
                from ..agentic_security.output_validator import validate_agent_report
                from ..agentic_security.guard import AgenticSecurityGuard

                pid = os.path.splitext(os.path.basename(source_path))[0]
                sha = _sha256_of_file(source_path) or "unknown_sha"

                # CRITICAL: If fallback occurred, Tier 3 empirical evidence (prog_comp) must be withheld
                effective_prog_comp = None if fallback_occurred else (
                    prog_comp.to_dict() if hasattr(prog_comp, "to_dict") else prog_comp
                )

                if fallback_occurred:
                    builder.add_note(
                        f"[W14-AGENTIC] Agentic analysis describes original selection {chosen_strategy}; benchmarked strategy was {effective_strategy}; empirical (Tier 3) evidence withheld."
                    )

                agent_rep = analyze_compilation(
                    program_id=pid,
                    source_hash=sha,
                    selected_strategy=chosen_strategy,
                    decision_trace=decision_trace,
                    program_profile=profile.to_dict() if hasattr(profile, "to_dict") else profile,
                    experience_records=[exp_rec.to_dict() if hasattr(exp_rec, "to_dict") else exp_rec] if exp_rec else [],
                    program_comparison=effective_prog_comp,
                )

                if agent_rep:
                    rep_dict = agent_rep.to_dict() if hasattr(agent_rep, "to_dict") else dict(agent_rep)
                    # Agentic AI Output Security Validation
                    guard = AgenticSecurityGuard()
                    output_val_performed = True
                    output_val_expected_strat = chosen_strategy
                    val_res = guard.validate_report(rep_dict, expected_selected_strategy=chosen_strategy, run_id=run_id)
                    output_val_reason = val_res.reason
                    if val_res.allowed:
                        output_val_result = "VALIDATED"
                        builder.set_agentic(agent_rep)
                    else:
                        output_val_result = "QUARANTINED"
                        report_quarantined = True
                        builder.add_note(f"Agentic report quarantined by security: {val_res.reason}")
                        builder.add_security_events(val_res.events)
            except Exception as exc:
                output_val_performed = True
                output_val_result = "ERROR"
                output_val_reason = str(exc)
                builder.add_note(f"Agentic AI analysis error: {exc}")

        # 9b. Agentic Security Assessment Integration (Week 14)
        if run_security or run_agentic:
            agentic_sec_summary = {
                "schema": "w14.agentic_security.1",
                "input_screening": {
                    "channel": "SOURCE_COMMENT",
                    "performed": comment_screening_performed,
                    "comments_screened": screened_comments_count,
                    "events": screening_events_count,
                    "blocked": screening_blocked_count,
                    "enforcement": "LOG_ONLY",
                    "error": screening_error,
                },
                "output_validation": {
                    "performed": output_val_performed,
                    "result": output_val_result,
                    "expected_strategy": output_val_expected_strat,
                    "reason": output_val_reason,
                },
                "report_quarantined": report_quarantined,
                "action_policy": {"exercised_in_pipeline": False},
                "artifact_scan": {
                    "exercised_in_pipeline": False,
                    "reason": "AgentEngine produces no generated artifacts",
                },
            }
            builder.set_agentic_security(agentic_sec_summary)

        # 10. Assemble and persist RunRecord
        record = builder.build()
        if self._persist_dir:
            self._persist(record)

        return record

    # ----------------------------------------------------------------
    # Primary entry point: build from already-computed artifacts
    # ----------------------------------------------------------------

    def build_from_artifacts(
        self,
        source_path: Optional[str] = None,
        *,
        program_profile: Optional[Any] = None,
        selection_result: Optional[Any] = None,
        decision_trace: Optional[Any] = None,
        moo_result: Optional[Any] = None,
        selected_strategy: Optional[str] = None,
        ir_features: Optional[dict] = None,
        model_id: Optional[str] = None,
        program_comparison: Optional[Any] = None,
        security_result: Optional[Any] = None,
        agent_report: Optional[Any] = None,
        experience_record: Optional[Any] = None,
        toolchain_info: Optional[dict] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        """
        Build a RunRecord from already-computed pipeline artifacts.

        All parameters are optional. Missing artifacts produce NOT_RUN stages,
        not fake OK or zero measurements.

        Parameters
        ----------
        source_path         : absolute path to C source file
        program_profile     : ProgramProfile instance or dict (Week 7/8)
        selection_result    : SelectionResult from selector_bridge (Week 8)
        decision_trace      : DecisionTrace instance or dict (Week 7/8)
        moo_result          : MOOEvaluationResult or dict (Week 9/10 pipeline)
        selected_strategy   : override or provide strategy string
        ir_features         : canonical 8 IR features dict
        model_id            : model checkpoint identifier
        program_comparison  : ProgramComparison or dict (Week 10)
        security_result     : CandidateSecurity or dict (security subsystem)
        agent_report        : AgentAnalysisReport or dict (Week 12)
        experience_record   : ExperienceRecord or dict (Week 11)
        toolchain_info      : dict with clang_version, opt_version, etc.
        run_id              : optional explicit run ID

        Returns
        -------
        RunRecord (fully populated where data is available)
        """
        builder = RunRecordBuilder(source_path=source_path, run_id=run_id)

        # Toolchain
        if toolchain_info:
            builder.set_toolchain(
                clang_version=toolchain_info.get("clang_version"),
                opt_version=toolchain_info.get("opt_version"),
                toolchain_ok=bool(toolchain_info.get("toolchain_ok", False)),
                toolchain_notes=list(toolchain_info.get("toolchain_notes") or []),
            )

        # IR features (from explicit arg or from decision_trace or moo_result)
        effective_ir_features = ir_features
        if effective_ir_features is None and decision_trace is not None:
            dt = decision_trace if isinstance(decision_trace, dict) else (
                decision_trace.to_dict() if hasattr(decision_trace, "to_dict") else None
            )
            if dt:
                effective_ir_features = dt.get("ir_features")

        builder.set_ir_features(features=effective_ir_features)

        # Profile (Week 7/8)
        builder.set_profile(program_profile)

        # Determine selected strategy
        effective_strategy = selected_strategy
        if effective_strategy is None and selection_result is not None:
            effective_strategy = getattr(selection_result, "strategy", None)
        if effective_strategy is None and decision_trace is not None:
            dt = decision_trace if isinstance(decision_trace, dict) else (
                decision_trace.to_dict() if hasattr(decision_trace, "to_dict") else None
            )
            if dt:
                effective_strategy = dt.get("final_strategy")

        # Selection + DecisionTrace
        builder.set_selection(
            selected_strategy=effective_strategy,
            decision_trace=decision_trace,
            selection_result=selection_result,
            model_id=model_id,
        )

        # MOO result (baseline + all candidates)
        if moo_result is not None:
            builder.set_moo_result(moo_result)
            builder.set_optimized_from_moo(moo_result, effective_strategy)

        # Regression comparison (Week 10)
        builder.set_regression(program_comparison)

        # Security analysis
        builder.set_security(security_result)

        # Agentic AI analysis (Week 12) — advisory only
        builder.set_agentic(agent_report)

        # Adaptive learning linkage (Week 11) — advisory only
        builder.set_adaptive(experience_record)

        record = builder.build()

        # Persist if configured
        if self._persist_dir:
            self._persist(record)

        return record

    # ----------------------------------------------------------------
    # Selection-only RunRecord (no benchmark)
    # ----------------------------------------------------------------

    def build_from_selection(
        self,
        source_path: Optional[str],
        ir_features: Optional[dict] = None,
        program_profile: Optional[Any] = None,
        q_values: Optional[list] = None,
        actions: Optional[list] = None,
        allow_moo: bool = False,
        model_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> RunRecord:
        """
        Build a selection-only RunRecord using the existing selector bridge.

        Runs only: feature extraction → profile → selection → decision trace.
        Does NOT run the compilation or benchmark pipeline.

        Parameters
        ----------
        source_path     : absolute path to C source file
        ir_features     : canonical 8 IR features (dict or sequence)
        program_profile : ProgramProfile instance or dict
        q_values        : DQN Q-values (if pre-computed)
        actions         : list of action strings (if pre-computed)
        allow_moo       : if True, use cached MOO frontier (no live run)
        model_id        : model checkpoint identifier
        run_id          : optional explicit run ID

        Returns
        -------
        RunRecord with selection stages populated, benchmark stages NOT_RUN
        """
        builder = RunRecordBuilder(source_path=source_path, run_id=run_id)
        builder.set_ir_features(features=ir_features)
        builder.set_profile(program_profile)

        selected_strategy: Optional[str] = None
        decision_trace: Optional[Any] = None
        selection_result: Optional[Any] = None

        # Run selection if q_values and actions are provided
        if q_values is not None and actions is not None:
            try:
                from ..selector_bridge import (
                    get_pareto_frontier_for,
                    moo_aware_select_with_trace,
                )

                frontier = []
                if allow_moo and source_path:
                    try:
                        frontier = get_pareto_frontier_for(source_path)
                    except Exception:
                        frontier = []

                sel_result, trace = moo_aware_select_with_trace(
                    source_path=source_path or "",
                    q_values=list(q_values),
                    actions=list(actions),
                    frontier=frontier,
                    ir_features=ir_features,
                )
                selection_result = sel_result
                decision_trace = trace
                selected_strategy = sel_result.strategy if sel_result else None

            except ImportError:
                builder.add_note("selector_bridge not available for selection")
            except Exception as exc:
                builder.add_note(f"Selection failed: {exc}")

        builder.set_selection(
            selected_strategy=selected_strategy,
            decision_trace=decision_trace,
            selection_result=selection_result,
            model_id=model_id,
        )

        record = builder.build()

        if self._persist_dir:
            self._persist(record)

        return record

    # ----------------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------------

    def _persist(self, record: RunRecord) -> Optional[str]:
        """
        Persist a RunRecord to JSON in the configured persist_dir.
        Uses a deterministic filename: runrecord_{run_id}.json.
        Returns the path on success, None on failure.
        Does NOT overwrite existing files — each run has a unique run_id.
        """
        if not self._persist_dir:
            return None

        try:
            os.makedirs(self._persist_dir, exist_ok=True)
            filename = f"runrecord_{record.run_id}.json"
            path = os.path.join(self._persist_dir, filename)

            if os.path.exists(path):
                # Never overwrite — each run_id is unique
                return path

            data = record.to_dict()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
            return path
        except Exception:
            return None

    @staticmethod
    def load(path: str) -> Optional[RunRecord]:
        """
        Load a persisted RunRecord from a JSON file.
        Returns None on any error.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return RunRecord.from_dict(data)
        except Exception:
            return None
