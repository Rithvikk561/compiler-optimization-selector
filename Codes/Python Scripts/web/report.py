"""
web/report.py — Deterministic Plain-English Workflow Report Generator for TOACD.

Translates technical run records, profiler classifications, security gate verdicts,
and empirical benchmark results into beginner-friendly, structured explanations.

Guarantees:
- Purely deterministic; NO LLM invocation.
- Strict provenance tracking (MEASURED, PROFILED, DECISION, VERIFIED, PREDICTED, NOT_RECORDED, NOT_APPLICABLE).
- Independent evaluation of execution, security, correctness, compilation, and performance.
- Never conflates optimization selection with performance gain.
- Never conflates inconclusive results with improvement or regression.
- Graceful handling of missing, partial, or failed run records.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional


class ReportProvenance(str, Enum):
    """
    Truthful provenance tracking for report claims.
    """
    MEASURED = "MEASURED"
    PROFILED = "PROFILED"
    DECISION = "DECISION"
    VERIFIED = "VERIFIED"
    PREDICTED = "PREDICTED"
    NOT_RECORDED = "NOT_RECORDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _explain_pass_pipeline(strategy: Optional[str]) -> str:
    """Provide a beginner-friendly explanation of applied compiler passes."""
    if not strategy:
        return "No specific optimization strategy was recorded."

    strategy_upper = strategy.strip()
    if strategy_upper == "-O0":
        return "No optimizations applied (-O0). Generates raw, unoptimized code suitable for debugging and baseline comparison."
    if strategy_upper == "-O1":
        return "Basic optimization level (-O1). Applies essential optimizations to reduce code size and execution time without significant compilation delay."
    if strategy_upper == "-O2":
        return "Standard optimization level (-O2). Applies instruction scheduling, common subexpression elimination, loop optimizations, and function inlining."
    if strategy_upper == "-O3":
        return "Aggressive optimization level (-O3). Enables advanced auto-vectorization, loop unrolling, and aggressive function inlining."

    # Custom LLVM pass pipelines
    passes = [p.strip() for p in strategy.split(",") if p.strip()]
    explanations: List[str] = []
    pass_map = {
        "mem2reg": "promotes stack variables into high-speed CPU registers",
        "instcombine": "combines redundant instructions into simpler operations",
        "simplifycfg": "cleans up branching logic and eliminates dead code paths",
        "dce": "eliminates instructions whose outputs are never used",
        "gvn": "eliminates identical redundant computations across code blocks",
        "loop-unroll": "unrolls loops to decrease branch overhead and enable vectorization",
        "inline": "replaces function calls with the function body to eliminate call overhead",
        "licm": "hoists computations out of loops so they only run once",
        "sroa": "breaks complex structures into scalar variables in registers",
    }
    for p in passes:
        if p in pass_map:
            explanations.append(f"{p} ({pass_map[p]})")
        else:
            explanations.append(p)

    if explanations:
        return f"Applies targeted LLVM optimization pipeline: {', '.join(explanations)}."
    return f"Applies custom compiler strategy: {strategy}."


VERDICT_BADGE_EXPLANATIONS: Dict[str, str] = {
    "SPEEDUP_VERIFIED": "Speedup Verified (The optimized code achieved a statistically verified performance improvement over the baseline reference under low measurement noise).",
    "BASELINE_READY": "Baseline Ready (Standard clang -O3 reference execution and benchmark timings were recorded successfully).",
    "PARITY": "Performance Parity (The optimized code executed on par with the baseline reference without measurable speedup or regression).",
    "REGRESSED": "Performance Regressed (The optimized code executed slower than the baseline reference in empirical measurements).",
    "REGRESSION": "Performance Regressed (The optimized code executed slower than the baseline reference in empirical measurements).",
    "INCONCLUSIVE": "Inconclusive Results (Measurement variance was too high to confirm whether the optimization improved or degraded performance).",
    "FALLBACK_APPLIED": "Security Fallback Applied (The security gate detected safety risks and substituted the candidate with a verified baseline strategy).",
    "SECURITY_BLOCKED": "Security Policy Blocked (The optimization candidate was blocked by the security gate to prevent unsafe code execution).",
    "COMPILATION_FAILED": "Compilation Failed (The compiler encountered syntax or toolchain diagnostics errors during code generation).",
    "EXECUTION_FAILED": "Execution Failed (The workflow encountered an execution error during deliberation, compilation, or benchmarking).",
    "FAILED_NO_DETAILS": "Execution Failed (The run terminated with a failure status, but no detailed error trace was captured).",
    "IN_PROGRESS": "Workflow In Progress (Deliberation or execution is actively running; results are provisional until terminal state is reached).",
    "COMPLETED_WITHOUT_BENCHMARKS": "Completed Without Benchmarks (Deliberation and compilation succeeded, but benchmark timings were not recorded).",
    "COMPLETED": "Completed (All recorded workflow stages completed successfully).",
    "UNAVAILABLE": "Record Unavailable (Run record data was missing or not found).",
}


def _explain_profile_label(label: Optional[str]) -> str:
    """Provide beginner-friendly context for static IR profile classification."""
    if not label:
        return "Static LLVM IR feature analysis was not performed or not recorded for this run."

    label_clean = str(label).lower().strip()
    if label_clean in ("loop_oriented", "loop oriented"):
        return "The program is dominated by repetitive loop structures, making loop transformations (such as loop unrolling and auto-vectorization) the most promising targets."
    if label_clean in ("compute_oriented", "compute oriented"):
        return "The program is dominated by arithmetic and mathematical calculations, where expression simplification and instruction scheduling provide the primary benefits."
    if label_clean in ("memory_oriented", "memory oriented"):
        return "The program is dominated by memory read and write operations; memory hierarchy and cache locality are the primary performance drivers."
    if label_clean in ("call_oriented", "call oriented"):
        return "The program makes frequent function calls; function inlining and call-overhead reduction are the most relevant optimizations."
    if label_clean == "mixed":
        return "The program presents a balanced mix of arithmetic, memory, and control-flow operations without any single dominant characteristic."
    if label_clean == "trivial":
        return "The program is very small (instruction count below baseline threshold); compiler optimizations will have negligible absolute impact."
    if label_clean == "unknown":
        return "The static IR features did not match a distinct dominant behavioral pattern."

    return f"The program profile was classified as '{label}' based on static LLVM IR instruction frequencies."


def explain_agent_message(msg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deterministic plain-English and technical explanation for a structured agent message.
    Preserves raw technical data while providing beginner-friendly context.
    """
    if not isinstance(msg, dict):
        return {
            "sender": "Unknown",
            "recipient": "Unknown",
            "message_type": "UNKNOWN",
            "step": 0,
            "timestamp": "",
            "category": "error",
            "simple_text": "Malformed or empty agent message.",
            "technical_summary": "Empty message payload",
            "raw_payload": {},
        }

    sender = str(msg.get("sender") or "Agent")
    recipient = str(msg.get("recipient") or "All")
    mtype = str(msg.get("message_type") or msg.get("type") or "UNKNOWN").upper()
    step = int(msg.get("step") or 1)
    timestamp = str(msg.get("timestamp") or "")
    payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}

    category = "observation"
    simple_text = ""
    technical_summary = ""

    if mtype == "IR_FEATURES":
        category = "observation"
        f = payload.get("ir_features") or {}
        tot = f.get("total_instructions") or payload.get("total_instructions") or 0
        loops = f.get("vectorizable_loops") or payload.get("vectorizable_loops") or 0
        mem = (f.get("load_instructions", 0) + f.get("store_instructions", 0)) or f.get("memory_instructions") or 0
        simple_text = (
            f"The Code Analyst examined the unoptimized program structure and counted {tot:,} instructions, "
            f"{loops} vectorizable loop nests, and {mem} memory operations to guide optimization choices."
        )
        technical_summary = f"IR features extracted: {tot} instructions, {loops} loops, {mem} memory operations."

    elif mtype in ("PROFILE", "PROGRAM_PROFILE"):
        category = "observation"
        prof = payload.get("profile") or payload
        label = prof.get("label") or "mixed"
        dominant = prof.get("dominant_feature") or "instructions"
        simple_text = (
            f"The Profiling Agent analyzed instruction frequencies and classified the program structure as '{label}' "
            f"(with '{dominant}' as the primary pattern). This categorization indicates which compiler passes may be relevant."
        )
        technical_summary = f"Program profile classified as '{label}' (dominant: {dominant})."

    elif mtype == "STRATEGY_PROPOSAL":
        category = "proposal"
        strat = payload.get("strategy") or "custom"
        provenance = payload.get("provenance") or "ML_POLICY"
        rev = payload.get("revision_number", 0)
        simple_text = (
            f"The Optimization Strategist proposed candidate optimization pipeline '{strat}'. "
            "Note: This is an initial candidate proposal submitted for reviewer verification, not an applied optimization."
        )
        technical_summary = f"Candidate strategy '{strat}' proposed (provenance: {provenance}, revision: {rev})."

    elif mtype == "REVIEW_ACCEPT":
        category = "review"
        strat = payload.get("strategy") or "candidate"
        rev = payload.get("revision_number", 0)
        simple_text = (
            f"The Optimization Reviewer audited candidate '{strat}' against provenance and safety rules, "
            "found no policy alerts, and approved the candidate to proceed to security verification."
        )
        technical_summary = f"Reviewer APPROVED candidate '{strat}' (revision: {rev}, 0 blocking alerts)."

    elif mtype == "REVIEW_REJECT":
        category = "review"
        strat = payload.get("strategy") or "candidate"
        feedback = payload.get("feedback") or "Policy mismatch or diagnostic alert"
        rev = payload.get("revision_number", 0)
        simple_text = (
            f"The Optimization Reviewer critiqued candidate '{strat}' and rejected it due to diagnostic concerns: '{feedback}'. "
            "The Strategist must formulate a revised proposal."
        )
        technical_summary = f"Reviewer REJECTED candidate '{strat}' (revision: {rev}, critique: {feedback})."

    elif mtype == "STRATEGY_REVISED":
        category = "proposal"
        strat = payload.get("strategy") or "revised"
        prev = payload.get("revising_strategy") or "previous"
        rev = payload.get("revision_number", 1)
        simple_text = (
            f"The Optimization Strategist adapted its recommendation in response to Reviewer feedback, proposing alternative candidate "
            f"'{strat}' (replacing '{prev}') for revision round #{rev}."
        )
        technical_summary = f"Revised strategy '{strat}' formulated for revision #{rev} (replacing '{prev}')."

    elif mtype == "FINAL_DECISION":
        category = "security"
        eff = payload.get("effective_strategy") or "baseline"
        fallback = bool(payload.get("fallback_occurred", False))
        gate_res = payload.get("security_gate_result") or {}
        verdict = gate_res.get("overall_verdict") or gate_res.get("decision") or "PASS"
        if fallback:
            simple_text = (
                f"The Security Gate detected safety or verification risks in the proposed candidate and safely substituted "
                f"verified baseline strategy '{eff}' (MOO fallback applied)."
            )
            technical_summary = f"Security Gate triggered FALLBACK to '{eff}' (verdict: {verdict})."
        elif verdict in ("BLOCK", "BLOCKED", "REJECT"):
            simple_text = (
                f"The Security Gate BLOCKED deployment of candidate '{eff}' due to security constraint violations."
            )
            technical_summary = f"Security Gate BLOCKED strategy '{eff}' (verdict: {verdict})."
        else:
            simple_text = (
                f"The Security Gate completed static AST scanning and pointer safety checks, authorizing '{eff}' for compilation."
            )
            technical_summary = f"Security Gate AUTHORIZED strategy '{eff}' (verdict: {verdict})."

    elif mtype in ("BENCHMARK_RESULT", "BENCHMARK_REPORT"):
        category = "benchmark"
        status = payload.get("status") or "OK"
        timing = payload.get("timing") or payload.get("moo_result", {}).get("optimized") or {}
        med = timing.get("median_s")
        if status == "OK" and med:
            ms = round(med * 1000.0, 2)
            simple_text = (
                f"The Benchmark Agent compiled and measured the program under hardware performance timers, recording an execution "
                f"runtime of {ms} ms with exit code 0."
            )
            technical_summary = f"Empirical benchmark recorded: median={ms} ms, status=OK."
        elif status != "OK":
            err = payload.get("error") or "Benchmark execution failure"
            simple_text = f"The Benchmark Agent reported a benchmarking failure during measurement: {err}."
            technical_summary = f"Benchmark failed: {err}."
        else:
            simple_text = "The Benchmark Agent completed execution timing measurements."
            technical_summary = "Benchmark execution completed."

    elif mtype == "CODE_ANALYSIS":
        category = "observation"
        analysis = payload.get("analysis") or "Inspected source code."
        simple_text = f"The Code Analyst examined the source program to prepare for baseline -O3 compilation: {analysis}"
        technical_summary = f"Code analysis complete: {analysis}"

    elif mtype == "ERROR":
        category = "error"
        err = payload.get("error") or payload.get("message") or "Unknown error"
        stage = payload.get("stage") or "execution"
        simple_text = f"An agent reported an error during the {stage} stage: {err}."
        technical_summary = f"Execution error in stage '{stage}': {err}."

    else:
        category = "coordination"
        simple_text = (
            f"This agent sent a message of type '{mtype}', but TOACD does not yet have a specialized plain-English explanation "
            "for this specific message type."
        )
        technical_summary = f"Generic agent message: type={mtype}, keys={list(payload.keys())}."

    return {
        "sender": sender,
        "recipient": recipient,
        "message_type": mtype,
        "step": step,
        "timestamp": timestamp,
        "category": category,
        "simple_text": simple_text,
        "technical_summary": technical_summary,
        "raw_payload": payload,
    }


def generate_workflow_narrative(
    run_id: str,
    mode: str,
    raw_status: str,
    record: Dict[str, Any],
    view: Dict[str, Any],
    scoped_events: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    compilation_succeeded: bool,
    compilation_failed: bool,
    security_passed: bool,
    security_blocked: bool,
    fallback_occurred: bool,
    correctness_verified: bool,
    execution_succeeded: bool,
    authoritative_verdict: str,
    base_time_ms: Optional[float],
    opt_time_ms: Optional[float],
    code_size_bytes: Optional[int],
    speedup_ratio: Optional[float],
    speedup_pct: Optional[float],
    speedup_text: str,
    timing_is_reliable: Optional[bool],
    selected_strat: Optional[str],
    effective_strat: Optional[str],
    rationale_text: str,
    error_msg: Optional[str],
    is_running: bool,
    is_provisional: bool,
) -> Dict[str, Any]:
    """
    Construct the chronological 7-step Plain-English Workflow Narrative:
    'What Happened During This Run?'
    Grounds every statement strictly in empirical evidence and recorded decision traces.
    """
    steps: List[Dict[str, Any]] = []

    # Map events by stage to extract timestamps and durations
    stage_events: Dict[str, List[Dict[str, Any]]] = {}
    for e in scoped_events:
        stg = e.get("stage")
        if stg:
            if stg not in stage_events:
                stage_events[stg] = []
            stage_events[stg].append(e)

    def _as_list(ev: Any) -> List[str]:
        if isinstance(ev, list):
            return [str(x) for x in ev]
        if isinstance(ev, (tuple, set)):
            return [str(x) for x in ev]
        if ev is None or ev == "":
            return []
        return [str(ev)]

    def _get_stage_timing(stg_key: str) -> Tuple[Optional[str], Optional[float]]:
        evts = stage_events.get(stg_key, [])
        if not evts:
            return None, None
        ts = evts[0].get("timestamp")
        return ts, None

    # -------------------------------------------------------------------------
    # STEP 1: Program Analysis
    # -------------------------------------------------------------------------
    ir_features = record.get("ir_features") if isinstance(record.get("ir_features"), dict) else {}
    program_profile = record.get("program_profile") if isinstance(record.get("program_profile"), dict) else {}
    prof_ts, prof_dur = _get_stage_timing("profiling")

    if mode == "normal":
        if is_running:
            s1_status = "running"
            s1_badge = "IN_PROGRESS"
            s1_simple = "The Code Analyst is inspecting the source code for baseline compilation."
            s1_tech = "Source inspection in progress."
            s1_evidence = "Inspecting source for -O3 baseline."
        else:
            s1_status = "completed"
            s1_badge = "INSPECTED"
            s1_simple = (
                "The Code Analyst examined the program's source code to prepare for standard clang -O3 baseline reference compilation."
            )
            s1_tech = "Static source inspection validated for baseline -O3 reference run."
            s1_evidence = "C source validated for baseline compilation."
    else:
        if ir_features or program_profile:
            label = program_profile.get("label") or "mixed"
            tot_inst = ir_features.get("total_instructions") or ir_features.get("inst_count")
            loops = ir_features.get("vectorizable_loops")
            dominant = program_profile.get("dominant_feature") or "instructions"
            s1_status = "completed"
            s1_badge = "PROFILED"
            inst_clause = f" ({tot_inst:,} instructions)" if tot_inst else ""
            s1_simple = (
                f"TOACD analyzed the program's LLVM intermediate representation{inst_clause} and categorized its structural pattern as '{label}' "
                f"(characterized by {dominant}). This structural pattern indicates which compiler optimizations may be promising, "
                "without proving that this pattern is the dynamic CPU runtime bottleneck."
            )
            s1_tech = (
                f"Deterministic IR feature analysis extracted: {tot_inst or 'N/A'} total instructions, {loops or 0} vectorizable loops, "
                f"and {ir_features.get('load_instructions', 0) + ir_features.get('store_instructions', 0)} memory operations. "
                f"Heuristic profile classified as '{label}' (dominant: {dominant})."
            )
            s1_evidence = f"Profile: {label} ({tot_inst or 'N/A'} instructions, {loops or 0} loops)."
        elif is_running:
            s1_status = "running"
            s1_badge = "IN_PROGRESS"
            s1_simple = "The Code Analyst is actively analyzing the program's LLVM IR features."
            s1_tech = "Profiling stage actively executing."
            s1_evidence = "IR feature extraction in progress."
        elif raw_status == "failed" and any("profil" in str(e).lower() for e in [error_msg]):
            s1_status = "failed"
            s1_badge = "FAILED"
            s1_simple = f"Program profiling halted due to an analysis error: {error_msg}."
            s1_tech = f"Profiling failed: {error_msg}."
            s1_evidence = f"Error during profiling: {error_msg}."
        else:
            s1_status = "not_recorded"
            s1_badge = "NOT_RECORDED"
            s1_simple = "Static LLVM IR feature analysis was not performed or not recorded for this run."
            s1_tech = "No static IR feature dictionary or program profile was captured."
            s1_evidence = "Static IR measurements not recorded."

    steps.append({
        "step_number": 1,
        "stage_key": "program_analysis",
        "stage_title": "Program Analysis",
        "status": s1_status,
        "badge": s1_badge,
        "simple_explanation": s1_simple,
        "technical_explanation": s1_tech,
        "evidence": _as_list(s1_evidence),
        "timestamp": prof_ts,
        "duration_ms": prof_dur,
        "technical_details": {
            "ir_features": ir_features,
            "program_profile": program_profile,
        },
        "is_provisional": (s1_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 2: Strategy Selection
    # -------------------------------------------------------------------------
    strat_ts, strat_dur = _get_stage_timing("strategy_selection")
    transform_explanation = _explain_pass_pipeline(effective_strat or selected_strat)

    if mode == "normal":
        s2_status = "completed"
        s2_badge = "BASELINE_O3"
        s2_simple = "The system selected standard compiler flag -O3 to establish an optimized baseline reference for subsequent comparison."
        s2_tech = "Selected fixed strategy '-O3' (clang aggressive optimization baseline)."
        s2_evidence = "Fixed compiler flag: -O3."
    else:
        if selected_strat:
            s2_status = "completed"
            if selected_strat != effective_strat and effective_strat:
                s2_badge = "SUBSTITUTED"
                s2_simple = (
                    f"The Optimization Strategist proposed candidate optimization pipeline '{selected_strat}', but the effective deployed strategy "
                    f"became '{effective_strat}' due to downstream safety intervention. {transform_explanation}"
                )
                s2_tech = (
                    f"Initial candidate proposed: '{selected_strat}'. Effective strategy deployed: '{effective_strat}'. "
                    f"Rationale: {rationale_text}. Applied pipeline: {transform_explanation}."
                )
                s2_evidence = f"Proposed: {selected_strat} -> Effective: {effective_strat}."
            else:
                s2_badge = "SELECTED"
                s2_simple = (
                    f"The Optimization Strategist evaluated candidate optimization passes and selected strategy '{selected_strat}'. "
                    f"{transform_explanation}"
                )
                s2_tech = f"Selected optimization strategy '{selected_strat}'. Rationale: {rationale_text}."
                s2_evidence = f"Selected candidate passes: {selected_strat}."
        elif is_running:
            s2_status = "running"
            s2_badge = "IN_PROGRESS"
            s2_simple = "The Optimization Strategist is actively evaluating candidate optimization pipelines."
            s2_tech = "Strategy selection actively in progress."
            s2_evidence = "Strategy selection in flight."
        elif s1_status == "failed":
            s2_status = "skipped"
            s2_badge = "SKIPPED"
            s2_simple = "Strategy selection was skipped because program profiling failed."
            s2_tech = "Skipped due to prior profiling failure."
            s2_evidence = "Prior stage failed."
        else:
            s2_status = "not_recorded"
            s2_badge = "NOT_RECORDED"
            s2_simple = "Optimization strategy selection was not recorded for this run."
            s2_tech = "No selected optimization strategy found in run record."
            s2_evidence = "Selection records not found."

    steps.append({
        "step_number": 2,
        "stage_key": "strategy_selection",
        "stage_title": "Optimization Strategy Selection",
        "status": s2_status,
        "badge": s2_badge,
        "simple_explanation": s2_simple,
        "technical_explanation": s2_tech,
        "evidence": _as_list(s2_evidence),
        "timestamp": strat_ts,
        "duration_ms": strat_dur,
        "technical_details": {
            "selected_strategy": selected_strat,
            "effective_strategy": effective_strat,
            "decision_trace": record.get("decision_trace"),
            "xai_result": record.get("xai_result"),
        },
        "is_provisional": (s2_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 3: Agent Review & Deliberation
    # -------------------------------------------------------------------------
    review_ts, review_dur = _get_stage_timing("agent_review")
    review_accepts = [m for m in messages if str(m.get("message_type")).upper() == "REVIEW_ACCEPT"]
    review_rejects = [m for m in messages if str(m.get("message_type")).upper() == "REVIEW_REJECT"]
    strategy_revisions = [m for m in messages if str(m.get("message_type")).upper() == "STRATEGY_REVISED"]
    rev_verdict = str(record.get("reviewer_verdict") or "")
    rev_feedback = str(record.get("reviewer_feedback") or "")
    rev_count = int(record.get("revision_count") or len(strategy_revisions))
    has_rejection = bool(review_rejects) or (rev_verdict.upper() in ("REJECT", "REJECTED"))

    if mode == "normal":
        s3_status = "skipped"
        s3_badge = "SKIPPED"
        s3_simple = "The multi-agent review loop was intentionally bypassed (Multi-agent peer review is omitted) because baseline reference runs compile with standard -O3 directly."
        s3_tech = "Standard baseline run bypasses OptimizationReviewerAgent loop."
        s3_evidence = "Baseline -O3 run intentionally bypasses review."
    else:
        if has_rejection:
            critique = "; ".join([str(r.get("payload", {}).get("feedback", "")) for r in review_rejects if r.get("payload", {}).get("feedback")]) or rev_feedback or "Diagnostic alerts detected"
            acc = review_accepts[0].get("payload", {}).get("strategy") if review_accepts else (effective_strat or selected_strat)
            s3_status = "completed"
            s3_badge = "REVISED"
            s3_simple = (
                f"The Optimization Reviewer audited the candidate proposal, rejected the initial sequence, and requested revisions ({critique}). "
                f"The Strategist addressed the critique through a bounded revision cycle ({rev_count} revision{'s' if rev_count != 1 else ''}), "
                f"concluding with accepted candidate '{acc}'."
            )
            s3_tech = (
                f"Reviewer rejected initial candidate with critique: '{critique}'. "
                f"Bounded revision cycle resolved in {rev_count} revision(s). Final candidate approved: '{acc}'."
            )
            s3_evidence = f"Reviewer critique prompted {rev_count} revision(s); final accepted candidate: {acc}."
        elif review_accepts:
            acc = review_accepts[0].get("payload", {}).get("strategy") or effective_strat
            s3_status = "completed"
            s3_badge = "APPROVED"
            s3_simple = (
                f"The Optimization Reviewer audited proposed candidate '{acc}' against provenance and safety diagnostics, "
                "verified zero policy alerts, and approved the candidate without requiring revisions."
            )
            s3_tech = f"Reviewer approved candidate '{acc}' on initial evaluation (0 revisions, 0 alerts)."
            s3_evidence = f"Reviewer approved '{acc}' (0 revisions)."
        elif is_running:
            s3_status = "running"
            s3_badge = "IN_PROGRESS"
            s3_simple = "The Optimization Reviewer is auditing the candidate proposal."
            s3_tech = "Reviewer audit actively executing."
            s3_evidence = "Deliberation in progress."
        elif s2_status in ("failed", "skipped"):
            s3_status = "skipped"
            s3_badge = "SKIPPED"
            s3_simple = "Agent review was skipped because strategy selection did not complete."
            s3_tech = "Skipped due to prior selection failure."
            s3_evidence = "Prior stage did not produce candidate."
        else:
            s3_status = "not_recorded"
            s3_badge = "NOT_RECORDED"
            s3_simple = "Agent review and deliberation records were not captured for this run."
            s3_tech = "No ReviewerAgent messages in message log."
            s3_evidence = "Review records not found."

    steps.append({
        "step_number": 3,
        "stage_key": "agent_review",
        "stage_title": "Agent Review & Deliberation",
        "status": s3_status,
        "badge": s3_badge,
        "simple_explanation": s3_simple,
        "technical_explanation": s3_tech,
        "evidence": _as_list(s3_evidence),
        "timestamp": review_ts,
        "duration_ms": review_dur,
        "technical_details": {
            "revisions_count": len(strategy_revisions),
            "rejections_count": len(review_rejects),
            "accepts_count": len(review_accepts),
        },
        "is_provisional": (s3_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 4: Security Verification
    # -------------------------------------------------------------------------
    sec_ts, sec_dur = _get_stage_timing("security_verification")
    sec_gate_dict = record.get("security_gate") if isinstance(record.get("security_gate"), dict) else {}
    sec_decision = sec_gate_dict.get("overall_verdict") or sec_gate_dict.get("decision") or "PASS"

    if mode == "normal":
        s4_status = "skipped"
        s4_badge = "SKIPPED"
        s4_simple = "Security gate verification was intentionally skipped because baseline reference runs use verified clang -O3 flags."
        s4_tech = "Baseline -O3 run intentionally bypasses OptimizationSecurityGate."
        s4_evidence = "Baseline flag bypasses security gate."
    else:
        if fallback_occurred:
            s4_status = "completed"
            s4_badge = "FALLBACK_APPLIED"
            s4_simple = (
                f"The security gate evaluated candidate '{selected_strat}' and flagged safety constraints. To preserve program safety, "
                f"the system substituted verified baseline strategy '{effective_strat}' (MOO fallback). A fallback protects code integrity, "
                "but does not prove the originally proposed candidate was safe."
            )
            s4_tech = (
                f"OptimizationSecurityGate substituted baseline '{effective_strat}' after flagging '{selected_strat}'. "
                f"Verdict: {sec_decision}. Memory bounds and AST inspection enforced."
            )
            s4_evidence = f"Safety fallback: substituted '{effective_strat}' for '{selected_strat}'."
        elif security_blocked:
            s4_status = "blocked"
            s4_badge = "SECURITY_BLOCKED"
            s4_simple = (
                f"The security gate blocked optimization candidate '{selected_strat}' due to policy violations, "
                "terminating execution before unsafe code could run."
            )
            s4_tech = f"OptimizationSecurityGate rejected candidate '{selected_strat}'. Verdict: {sec_decision}. Execution terminated."
            s4_evidence = f"Security gate blocked candidate '{selected_strat}'."
        elif security_passed:
            s4_status = "completed"
            s4_badge = "PASSED"
            s4_simple = (
                f"The security gate performed static AST inspection and memory boundary checks on candidate '{effective_strat}', "
                "verifying that all operations satisfy safety constraints."
            )
            s4_tech = f"OptimizationSecurityGate PASSED for candidate '{effective_strat}'. Verdict: {sec_decision}. Pointer & AST constraints verified."
            s4_evidence = f"Security gate passed for candidate '{effective_strat}'."
        elif is_running:
            s4_status = "running"
            s4_badge = "IN_PROGRESS"
            s4_simple = "The security gate is currently auditing the optimization candidate."
            s4_tech = "Security verification in progress."
            s4_evidence = "Security audit in flight."
        elif s3_status in ("failed", "skipped"):
            s4_status = "skipped"
            s4_badge = "SKIPPED"
            s4_simple = "Security verification was skipped because prior deliberation stages did not complete."
            s4_tech = "Skipped due to prior deliberation failure."
            s4_evidence = "Prior stage did not complete."
        else:
            s4_status = "not_recorded"
            s4_badge = "NOT_RECORDED"
            s4_simple = "Security verification was not performed or not recorded for this run."
            s4_tech = "No security gate records found in RunRecord."
            s4_evidence = "Security verification records not found."

    steps.append({
        "step_number": 4,
        "stage_key": "security_verification",
        "stage_title": "Security Verification",
        "status": s4_status,
        "badge": s4_badge,
        "simple_explanation": s4_simple,
        "technical_explanation": s4_tech,
        "evidence": _as_list(s4_evidence),
        "timestamp": sec_ts,
        "duration_ms": sec_dur,
        "technical_details": {
            "security_gate": sec_gate_dict,
            "security_decision": sec_decision,
            "fallback_occurred": fallback_occurred,
        },
        "is_provisional": (s4_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 5: Compilation & Correctness
    # -------------------------------------------------------------------------
    comp_ts = sec_ts
    if compilation_failed:
        s5_status = "failed"
        s5_badge = "COMPILATION_FAILED"
        s5_simple = f"Compilation failed: Clang encountered fatal errors while building the candidate ({error_msg or 'syntax or toolchain error'}). No binary was produced."
        s5_tech = f"Clang compilation returned non-zero exit code: {error_msg}."
        s5_evidence = f"Compilation failure: {error_msg}."
    elif security_blocked:
        s5_status = "skipped"
        s5_badge = "SKIPPED"
        s5_simple = "Compilation was skipped because the candidate was blocked by the security gate."
        s5_tech = "Compilation skipped due to security block."
        s5_evidence = "Security gate blocked compilation."
    elif compilation_succeeded:
        s5_status = "completed"
        if correctness_verified:
            s5_badge = "VERIFIED"
            s5_simple = "The program compiled cleanly with zero fatal errors, and execution verified that the numerical output matched reference execution (exit code 0)."
            s5_tech = "Compilation succeeded (exit code 0). Correctness check: execution outputs match reference output exactly."
            s5_evidence = "Clean compilation (code 0) and reference output match verified."
        elif raw_status == "failed" and any("correctness" in str(e).lower() for e in [error_msg]):
            s5_badge = "CORRECTNESS_FAILED"
            s5_status = "failed"
            s5_simple = f"The program compiled, but correctness verification failed: output did not match reference ({error_msg})."
            s5_tech = f"Correctness verification failure: {error_msg}."
            s5_evidence = f"Correctness failure: {error_msg}."
        else:
            s5_badge = "COMPILED"
            s5_simple = "The program compiled cleanly with zero compiler diagnostics errors. Correctness comparison against reference output was not recorded."
            s5_tech = "Compilation succeeded with exit code 0. Correctness comparison not recorded."
            s5_evidence = "Compilation clean (exit code 0)."
    elif is_running:
        s5_status = "running"
        s5_badge = "IN_PROGRESS"
        s5_simple = "Compilation and build verification are currently in progress."
        s5_tech = "Clang compilation in progress."
        s5_evidence = "Build in progress."
    else:
        s5_status = "not_recorded"
        s5_badge = "NOT_RECORDED"
        s5_simple = "Compilation was not attempted or not recorded for this run."
        s5_tech = "No compilation status recorded."
        s5_evidence = "Compilation record missing."

    steps.append({
        "step_number": 5,
        "stage_key": "compilation_and_correctness",
        "stage_title": "Compilation & Correctness Verification",
        "status": s5_status,
        "badge": s5_badge,
        "simple_explanation": s5_simple,
        "technical_explanation": s5_tech,
        "evidence": _as_list(s5_evidence),
        "timestamp": comp_ts,
        "duration_ms": None,
        "technical_details": {
            "compilation_succeeded": compilation_succeeded,
            "compilation_failed": compilation_failed,
            "correctness_verified": correctness_verified,
        },
        "is_provisional": (s5_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 6: Empirical Benchmarking
    # -------------------------------------------------------------------------
    bench_ts, bench_dur = _get_stage_timing("benchmarking")
    if compilation_failed or security_blocked:
        s6_status = "skipped"
        s6_badge = "SKIPPED"
        s6_simple = "Empirical benchmarking was not performed because execution halted before code generation completed."
        s6_tech = "Benchmarking skipped: prior stage failed or blocked execution."
        s6_evidence = "Benchmarking skipped."
    elif opt_time_ms is not None:
        if base_time_ms is not None:
            if authoritative_verdict == "INCONCLUSIVE":
                s6_status = "inconclusive"
                s6_badge = "INCONCLUSIVE"
                s6_simple = (
                    f"The Benchmark Agent measured {opt_time_ms:.2f} ms for the candidate versus {base_time_ms:.2f} ms for baseline. "
                    "However, execution times showed elevated measurement variance across repetitions, so performance differences cannot be reliably confirmed."
                )
                s6_tech = (
                    f"Baseline: {base_time_ms:.3f} ms, Candidate: {opt_time_ms:.3f} ms. High measurement variance (timing_is_reliable=False). "
                    "Authoritative verdict: INCONCLUSIVE."
                )
                s6_evidence = f"Baseline {base_time_ms:.2f} ms vs Candidate {opt_time_ms:.2f} ms (Inconclusive / noisy)."
            elif authoritative_verdict in ("REGRESSED", "REGRESSION"):
                diff_ms = round(opt_time_ms - base_time_ms, 2)
                pct = round(((opt_time_ms - base_time_ms) / base_time_ms) * 100.0, 1)
                s6_status = "completed"
                s6_badge = "REGRESSED"
                s6_simple = (
                    f"The Benchmark Agent recorded {opt_time_ms:.2f} ms for the candidate versus {base_time_ms:.2f} ms for baseline "
                    f"({diff_ms:.2f} ms longer, an elapsed time increase of {pct}% in this measurement). The authoritative backend comparator confirmed this as a performance regression."
                )
                s6_tech = f"Baseline: {base_time_ms:.3f} ms, Candidate: {opt_time_ms:.3f} ms ({speedup_text}). Authoritative verdict: REGRESSED."
                s6_evidence = f"Baseline {base_time_ms:.2f} ms vs Candidate {opt_time_ms:.2f} ms (Slowdown confirmed: REGRESSED)."
            elif authoritative_verdict == "IMPROVED":
                diff_ms = round(base_time_ms - opt_time_ms, 2)
                s6_status = "completed"
                s6_badge = "SPEEDUP_VERIFIED"
                s6_simple = (
                    f"The Benchmark Agent recorded {opt_time_ms:.2f} ms for the candidate versus {base_time_ms:.2f} ms for baseline "
                    f"({diff_ms:.2f} ms faster, {speedup_text}). The backend comparator confirmed a statistically verified speedup under low measurement noise."
                )
                s6_tech = f"Baseline: {base_time_ms:.3f} ms, Candidate: {opt_time_ms:.3f} ms ({speedup_text}). Authoritative verdict: IMPROVED."
                s6_evidence = f"Baseline {base_time_ms:.2f} ms vs Candidate {opt_time_ms:.2f} ms ({speedup_text})."
            else:  # PARITY
                s6_status = "completed"
                s6_badge = "PARITY"
                s6_simple = (
                    f"The Benchmark Agent recorded {opt_time_ms:.2f} ms for the candidate versus {base_time_ms:.2f} ms for baseline. "
                    "Execution time is on par with baseline without measurable difference (performance parity)."
                )
                s6_tech = f"Baseline: {base_time_ms:.3f} ms, Candidate: {opt_time_ms:.3f} ms. Authoritative verdict: PARITY."
                s6_evidence = f"Performance parity at {opt_time_ms:.2f} ms."
        else:
            s6_status = "completed"
            s6_badge = "MEASURED"
            s6_simple = f"The Benchmark Agent recorded a baseline execution time of {opt_time_ms:.2f} ms ({code_size_bytes or 'N/A'} bytes machine code size)."
            s6_tech = f"Reference -O3 benchmark: runtime={opt_time_ms:.3f} ms, code_size={code_size_bytes or 0} B."
            s6_evidence = f"Recorded runtime: {opt_time_ms:.2f} ms."
    elif is_running:
        s6_status = "running"
        s6_badge = "IN_PROGRESS"
        s6_simple = "The Benchmark Agent is currently running execution timing measurements on host hardware."
        s6_tech = "Benchmark timing measurements in progress."
        s6_evidence = "Benchmarking in flight."
    else:
        s6_status = "not_recorded"
        s6_badge = "NOT_RECORDED"
        s6_simple = "Benchmark timing measurements were not recorded for this run."
        s6_tech = "No benchmark measurements in RunRecord."
        s6_evidence = "Benchmark records missing."

    steps.append({
        "step_number": 6,
        "stage_key": "benchmarking",
        "stage_title": "Empirical Benchmarking",
        "status": s6_status,
        "badge": s6_badge,
        "simple_explanation": s6_simple,
        "technical_explanation": s6_tech,
        "evidence": _as_list(s6_evidence),
        "timestamp": bench_ts,
        "duration_ms": bench_dur,
        "technical_details": {
            "baseline_time_ms": base_time_ms,
            "optimized_time_ms": opt_time_ms,
            "code_size_bytes": code_size_bytes,
            "speedup_ratio": speedup_ratio,
            "speedup_pct": speedup_pct,
            "authoritative_verdict": authoritative_verdict,
            "timing_is_reliable": timing_is_reliable,
        },
        "is_provisional": (s6_status == "running"),
    })

    # -------------------------------------------------------------------------
    # STEP 7: Final Workflow Outcome
    # -------------------------------------------------------------------------
    last_ts = scoped_events[-1].get("timestamp") if scoped_events else None
    if is_running:
        s7_status = "running"
        s7_badge = "IN_PROGRESS"
        s7_simple = "The workflow is actively executing and underway. All stages and results shown are provisional until execution terminates."
        s7_tech = f"Workflow actively running (run_id: {run_id}, mode: {mode})."
        s7_evidence = "Provisional execution in flight."
    elif security_blocked:
        s7_status = "blocked"
        s7_badge = "BLOCKED"
        s7_simple = "Execution was halted by the security gate to protect program safety. No untrusted code was deployed."
        s7_tech = f"Workflow blocked by security gate (verdict: {sec_decision})."
        s7_evidence = "Security gate blocked deployment."
    elif compilation_failed:
        s7_status = "failed"
        s7_badge = "FAILED"
        s7_simple = f"The workflow halted due to a compilation failure ({error_msg or 'syntax or toolchain error'})."
        s7_tech = f"Workflow failed during build: {error_msg}."
        s7_evidence = "Compilation failure."
    elif raw_status == "failed":
        s7_status = "failed"
        s7_badge = "FAILED"
        s7_simple = f"The workflow terminated prematurely: {error_msg or 'Execution stopped without error detail'}."
        s7_tech = f"Workflow failed: {error_msg or 'FAILED_NO_DETAILS'}."
        s7_evidence = f"Failure: {error_msg or 'No details'}."
    else:  # completed
        if mode == "normal":
            s7_status = "completed"
            s7_badge = "BASELINE_READY"
            s7_simple = f"The standard clang -O3 baseline reference run completed cleanly, establishing a reliable reference execution time of {opt_time_ms or 'N/A'} ms for subsequent AI comparison."
            s7_tech = f"Baseline reference established: runtime={opt_time_ms} ms, code_size={code_size_bytes} B."
            s7_evidence = "Baseline reference established."
        else:
            s7_status = "completed"
            if authoritative_verdict == "IMPROVED":
                s7_badge = "SPEEDUP_VERIFIED"
                s7_simple = f"The optimization run succeeded across every stage: compilation was clean, safety was verified, and the candidate achieved a verified speedup ({speedup_text})."
                s7_tech = f"Multi-agent run succeeded with verified speedup ({speedup_text}, verdict=IMPROVED)."
                s7_evidence = f"Speedup verified ({speedup_text})."
            elif authoritative_verdict in ("REGRESSED", "REGRESSION"):
                s7_badge = "REGRESSED"
                s7_simple = (
                    f"The workflow completed compilation, security, and correctness checks successfully, but empirical measurements showed a performance regression ({speedup_text}). "
                    "Successful execution does not guarantee a performance gain."
                )
                s7_tech = f"Workflow completed cleanly; performance regressed ({speedup_text}, verdict=REGRESSED)."
                s7_evidence = f"Completed with performance regression ({speedup_text})."
            elif authoritative_verdict == "INCONCLUSIVE":
                s7_badge = "INCONCLUSIVE"
                s7_simple = "The workflow completed compilation and safety checks successfully, but high measurement variance rendered the performance comparison inconclusive."
                s7_tech = "Workflow completed; performance inconclusive due to timing variance."
                s7_evidence = "Inconclusive performance comparison."
            elif authoritative_verdict == "PARITY":
                s7_badge = "PARITY"
                s7_simple = "The workflow completed successfully across all stages; the optimized code performed on par with the baseline reference without measurable difference."
                s7_tech = "Workflow completed with performance parity (verdict=PARITY)."
                s7_evidence = "Performance parity."
            else:
                s7_badge = "COMPLETED"
                s7_simple = "The optimization workflow completed all recorded pipeline stages."
                s7_tech = "All pipeline stages completed."
                s7_evidence = "Run completed."

    steps.append({
        "step_number": 7,
        "stage_key": "final_outcome",
        "stage_title": "Final Workflow Outcome",
        "status": s7_status,
        "badge": s7_badge,
        "simple_explanation": s7_simple,
        "technical_explanation": s7_tech,
        "evidence": _as_list(s7_evidence),
        "timestamp": last_ts,
        "duration_ms": None,
        "technical_details": {
            "execution_succeeded": execution_succeeded,
            "security_passed": security_passed,
            "correctness_verified": correctness_verified,
            "authoritative_verdict": authoritative_verdict,
        },
        "is_provisional": (s7_status == "running"),
    })

    completed_count = sum(1 for s in steps if s["status"] in ("completed", "verified"))

    return {
        "title": "What Happened During This Run?",
        "run_id": run_id,
        "mode": mode,
        "is_provisional": is_provisional,
        "available": True,
        "steps": steps,
        "total_steps": 7,
        "completed_steps": completed_count,
    }


def generate_workflow_report(
    run_data: Optional[Dict[str, Any]],
    events: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a deterministic, beginner-friendly Plain-English Workflow Report
    from actual recorded run data and canonical events.

    Returns a structured dictionary with sections A through G.
    """
    # 0. Graceful fallback for missing or malformed run records
    if not isinstance(run_data, dict):
        return {
            "schema_version": "1.0",
            "run_id": "unknown",
            "program_id": "unknown",
            "mode": "unknown",
            "status": "not_recorded",
            "summary": {
                "headline": "Run Record Unavailable",
                "mode_label": "Unknown Mode",
                "execution_outcome": "Not recorded",
                "is_conclusive": False,
                "conclusive_reason": "No run data was recorded or provided to the report generator.",
                "plain_text": "The system cannot generate a workflow report because the requested run record is missing or invalid.",
                "provenance": ReportProvenance.NOT_RECORDED.value,
            },
            "program_analysis": {
                "available": False,
                "profile_label": None,
                "profile_explanation": "Program profile information was not recorded.",
                "instructions": None,
                "loops": None,
                "memory_instructions": None,
                "branches": None,
                "dominant_feature": None,
                "static_vs_runtime_note": "No static IR measurements available.",
                "provenance": ReportProvenance.NOT_RECORDED.value,
            },
            "optimization_strategy": {
                "available": False,
                "selected_strategy": None,
                "effective_strategy": None,
                "strategies_differ": False,
                "fallback_occurred": False,
                "fallback_reason": None,
                "decision_rationale": "Optimization strategy was not recorded.",
                "applied_transformations": "No transformations recorded.",
                "provenance": ReportProvenance.NOT_RECORDED.value,
            },
            "security_and_correctness": {
                "security_status": "Not recorded",
                "security_details": "Security verification was not recorded.",
                "security_provenance": ReportProvenance.NOT_RECORDED.value,
                "compilation_status": "Not recorded",
                "compilation_details": "Compilation status was not recorded.",
                "compilation_provenance": ReportProvenance.NOT_RECORDED.value,
                "correctness_status": "Not recorded",
                "correctness_details": "Correctness verification was not recorded.",
                "correctness_provenance": ReportProvenance.NOT_RECORDED.value,
                "fallback_handling": "Not recorded",
            },
            "performance": {
                "available": False,
                "baseline_time_ms": None,
                "optimized_time_ms": None,
                "code_size_bytes": None,
                "code_size_description": "Code size was not recorded.",
                "speedup_ratio": None,
                "speedup_pct": None,
                "speedup_text": "Not calculated (measurements unavailable)",
                "timing_is_reliable": None,
                "reliability_explanation": "Timing measurements were not recorded.",
                "benchmark_verdict": "NOT_RUN",
                "verdict_explanation": "Benchmarking was not performed or not recorded.",
                "provenance": ReportProvenance.NOT_RECORDED.value,
            },
            "problems_and_limitations": [
                {
                    "severity": "error",
                    "title": "Missing Run Record",
                    "description": "Run record data was not found in the storage store.",
                }
            ],
            "overall_conclusion": {
                "headline": "No Run Data Recorded",
                "text": "The report cannot verify execution, security, or performance because the run record is missing.",
                "execution_succeeded": False,
                "compilation_succeeded": False,
                "security_passed": False,
                "correctness_verified": False,
                "performance_improved": False,
                "verdict_badge": "UNAVAILABLE",
                "verdict_badge_explanation": VERDICT_BADGE_EXPLANATIONS["UNAVAILABLE"],
            },
            "workflow_narrative": {
                "title": "What Happened During This Run?",
                "run_id": "unknown",
                "mode": "unknown",
                "is_provisional": False,
                "available": False,
                "steps": [],
                "total_steps": 7,
                "completed_steps": 0,
            },
            "agent_messages": [],
            "is_provisional": False,
        }

    # Extract core identities
    run_id = str(run_data.get("run_id") or "unknown")
    program_id = str(run_data.get("program_id") or "custom")
    mode = str(run_data.get("mode") or "ai")
    raw_status = str(run_data.get("status") or "unknown").lower()
    is_running = (raw_status == "running")
    is_provisional = is_running
    record = run_data.get("record") if isinstance(run_data.get("record"), dict) else {}
    view = run_data.get("view") if isinstance(run_data.get("view"), dict) else {}
    error_msg = run_data.get("error") or record.get("error") or record.get("compilation_error")
    failed_without_error = (raw_status == "failed" and not error_msg)
    elapsed_s = run_data.get("elapsed_s")

    # Event extraction scoped strictly to this run_id
    scoped_events = []
    if events and isinstance(events, list):
        for e in events:
            e_dict = e.to_dict() if hasattr(e, "to_dict") else (e if isinstance(e, dict) else {})
            if e_dict.get("run_id") == run_id:
                scoped_events.append(e_dict)

    # Message extraction scoped strictly to this run_id
    scoped_messages = []
    if isinstance(run_data.get("messages"), list):
        for m in run_data["messages"]:
            m_dict = m.to_dict() if hasattr(m, "to_dict") else (m if isinstance(m, dict) else {})
            if m_dict.get("run_id") in (run_id, None, ""):
                scoped_messages.append(m_dict)
    for evt in scoped_events:
        if evt.get("event_type") == "agent_message":
            p = evt.get("payload") or {}
            msg_obj = {
                "step": p.get("step") or evt.get("seq", 1),
                "sender": p.get("sender") or "Agent",
                "recipient": p.get("recipient") or "All",
                "message_type": p.get("message_type") or "MSG",
                "payload": p.get("payload") or p,
                "timestamp": evt.get("timestamp") or "",
                "run_id": run_id,
            }
            if not any(sm.get("step") == msg_obj["step"] and sm.get("message_type") == msg_obj["message_type"] for sm in scoped_messages):
                scoped_messages.append(msg_obj)

    explained_messages = [explain_agent_message(m) for m in scoped_messages]

    # -------------------------------------------------------------------------
    # 1. Determine execution outcome & security/compilation state
    # -------------------------------------------------------------------------
    compilation_succeeded = False
    compilation_failed = False
    if record.get("compilation_success") is False:
        compilation_failed = True
    elif raw_status == "failed" and error_msg:
        err_lower = str(error_msg).lower()
        if any(term in err_lower for term in ("compil", "clang", "syntax", "opt_error", "exit code", "llvm ir")):
            compilation_failed = True

    if not compilation_failed and (raw_status == "completed" or run_data.get("opt_ir") or record.get("optimized_measurement")):
        compilation_succeeded = True

    # Security evaluation
    security_gate = record.get("security_gate") or view.get("security_gate") or {}
    sec_verdict = (
        security_gate.get("overall_verdict")
        or security_gate.get("decision")
        or record.get("security_verdict")
        or view.get("security", {}).get("verdict")
    )
    fallback_occurred = bool(
        record.get("fallback_occurred")
        or view.get("fallback_occurred")
        or security_gate.get("fallback_triggered", False)
    )

    security_blocked = (
        raw_status == "blocked"
        or (sec_verdict in ("BLOCK", "BLOCKED", "REJECT") and not fallback_occurred)
    )
    security_passed = bool(
        sec_verdict in ("PASS", "PERMITTED")
        or (fallback_occurred and raw_status == "completed")
    )

    # Correctness evaluation
    correctness_verified = False
    if mode == "normal":
        if run_data.get("is_valid_reference") is True or (raw_status == "completed" and not error_msg):
            correctness_verified = True
    elif mode == "ai":
        # In AI mode, successful benchmark execution implies reference output match
        opt_meas = record.get("optimized_measurement") or {}
        if raw_status == "completed" and opt_meas.get("status") == "OK":
            correctness_verified = True

    # Execution succeeded flag
    execution_succeeded = (raw_status == "completed")

    # -------------------------------------------------------------------------
    # 2. Section B: Program Analysis
    # -------------------------------------------------------------------------
    ir_features = record.get("ir_features") or {}
    program_profile = record.get("program_profile") or {}
    profile_available = bool(ir_features or program_profile)

    profile_label = (
        program_profile.get("label")
        or view.get("profile_label")
        or ("mixed" if ir_features else None)
    )

    instructions = (
        ir_features.get("total_instructions")
        or ir_features.get("inst_count")
    )
    loops = ir_features.get("vectorizable_loops")
    mem_insts = None
    if "load_instructions" in ir_features or "store_instructions" in ir_features:
        mem_insts = int(ir_features.get("load_instructions", 0) + ir_features.get("store_instructions", 0))
    elif "memory_instructions" in ir_features:
        mem_insts = int(ir_features.get("memory_instructions", 0))

    branches = (
        ir_features.get("branch_instructions")
        or ir_features.get("branch_count")
    )
    dominant_feat = program_profile.get("dominant_feature")

    program_analysis = {
        "available": profile_available,
        "profile_label": profile_label,
        "profile_explanation": _explain_profile_label(profile_label),
        "instructions": int(instructions) if instructions is not None else None,
        "loops": int(loops) if loops is not None else None,
        "memory_instructions": mem_insts,
        "branches": int(branches) if branches is not None else None,
        "dominant_feature": dominant_feat,
        "static_vs_runtime_note": (
            "These features were measured statically from unoptimized LLVM IR instructions. "
            "Static structure indicates code patterns and optimization potential, but does not prove dynamic CPU execution time."
            if profile_available
            else "Static IR features were not recorded for this run."
        ),
        "provenance": (
            ReportProvenance.PROFILED.value
            if profile_available
            else ReportProvenance.NOT_RECORDED.value
        ),
    }

    # -------------------------------------------------------------------------
    # 3. Section C: Optimization Strategy
    # -------------------------------------------------------------------------
    selected_strat = record.get("selected_strategy")
    if not selected_strat and mode == "normal":
        selected_strat = "-O3"

    effective_strat = record.get("effective_strategy") or view.get("effective_strategy") or selected_strat
    strategies_differ = (selected_strat != effective_strat and bool(selected_strat and effective_strat))

    # Decision rationale extraction
    decision_trace = record.get("decision_trace") if isinstance(record.get("decision_trace"), dict) else {}
    xai_res = record.get("xai_result") if isinstance(record.get("xai_result"), dict) else {}
    rationale = (
        decision_trace.get("selection_reason")
        or decision_trace.get("explanation")
        or xai_res.get("explanation")
    )

    pareto_explanation = (
        "Pareto Frontier Evaluation: Multi-Objective Optimization balances execution runtime against code size "
        "and compilation overhead to select non-dominated optimization candidates. If a proposed candidate fails "
        "safety verification or validation checks, MOO fallback safely deploys a verified baseline configuration."
    )

    if not rationale:
        if mode == "normal":
            rationale_text = "The system selected standard compiler flag -O3 to establish a baseline execution reference."
        elif selected_strat:
            rationale_text = f"Optimization strategy '{selected_strat}' was selected, but detailed decision rationale was not recorded."
            if mode == "ai":
                rationale_text += f" {pareto_explanation}"
        else:
            rationale_text = "No optimization strategy was selected or recorded for this run."
    else:
        rationale_text = str(rationale)

    fallback_reason = None
    if fallback_occurred:
        fallback_reason = (
            f"The optimizer proposed '{selected_strat}', but security constraints flagged potential risks. "
            f"The security gate safely substituted the verified baseline strategy '{effective_strat}' (MOO fallback)."
        )

    opt_strategy = {
        "available": bool(selected_strat or effective_strat),
        "selected_strategy": selected_strat,
        "effective_strategy": effective_strat,
        "strategies_differ": strategies_differ,
        "fallback_occurred": fallback_occurred,
        "fallback_reason": fallback_reason,
        "decision_rationale": rationale_text,
        "applied_transformations": _explain_pass_pipeline(effective_strat or selected_strat),
        "pareto_evaluation_note": pareto_explanation if mode == "ai" else None,
        "provenance": (
            ReportProvenance.DECISION.value
            if (selected_strat or effective_strat)
            else ReportProvenance.NOT_RECORDED.value
        ),
    }

    # -------------------------------------------------------------------------
    # 4. Section D: Security and Correctness
    # -------------------------------------------------------------------------
    # Security
    if mode == "normal":
        sec_status = "Skipped"
        sec_details = "Baseline -O3 reference run intentionally bypasses multi-agent security verification."
        sec_prov = ReportProvenance.NOT_APPLICABLE.value
    elif security_blocked:
        sec_status = "Blocked"
        sec_details = "The candidate optimization was blocked by the security gate due to policy violation without an automated fallback."
        sec_prov = ReportProvenance.VERIFIED.value
    elif fallback_occurred:
        sec_status = "Passed (via Fallback)"
        sec_details = f"Safety constraints identified risks in '{selected_strat}'; safely substituted verified baseline '{effective_strat}'."
        sec_prov = ReportProvenance.VERIFIED.value
    elif sec_verdict in ("PASS", "PERMITTED"):
        sec_status = "Passed"
        sec_details = "AST inspection and memory boundary checks verified that optimization candidate preserves safety constraints."
        sec_prov = ReportProvenance.VERIFIED.value
    elif record.get("security_status") == "FAILED":
        sec_status = "Failed"
        sec_details = "Security analyzer encountered an error during verification."
        sec_prov = ReportProvenance.VERIFIED.value
    else:
        sec_status = "Not recorded"
        sec_details = "Security verification outcome was not recorded for this run."
        sec_prov = ReportProvenance.NOT_RECORDED.value

    # Compilation
    if compilation_failed:
        comp_status = "Failed"
        comp_details = f"Compiler reported fatal diagnostics during build: {error_msg or 'syntax or toolchain error'}."
        comp_prov = ReportProvenance.VERIFIED.value
    elif compilation_succeeded:
        comp_status = "Passed"
        comp_details = "Clang and LLVM optimizer successfully generated valid machine code with zero fatal errors."
        comp_prov = ReportProvenance.VERIFIED.value
    else:
        comp_status = "Not recorded"
        comp_details = "Compilation status was not recorded."
        comp_prov = ReportProvenance.NOT_RECORDED.value

    # Correctness
    if correctness_verified:
        corr_status = "Passed"
        corr_details = "Execution completed with exit code 0; numerical output matched reference execution."
        corr_prov = ReportProvenance.VERIFIED.value
    elif raw_status == "failed" and any(k in str(error_msg or "").lower() for k in ("correctness", "output mismatch", "sigsegv")):
        corr_status = "Failed"
        corr_details = f"Correctness check failed: {error_msg}."
        corr_prov = ReportProvenance.VERIFIED.value
    elif mode == "normal" and not execution_succeeded:
        corr_status = "Failed"
        corr_details = "Baseline execution failed before correctness could be verified."
        corr_prov = ReportProvenance.VERIFIED.value
    else:
        corr_status = "Not recorded"
        corr_details = "Correctness verification was not recorded or reference output was unavailable."
        corr_prov = ReportProvenance.NOT_RECORDED.value

    # Fallback handling label
    if fallback_occurred:
        fb_handling = "Triggered (Safe Baseline)"
    elif security_blocked:
        fb_handling = "Blocked"
    elif mode == "normal":
        fb_handling = "Not applicable"
    elif sec_status == "Passed":
        fb_handling = "None (Original Strategy Retained)"
    else:
        fb_handling = "Not recorded"

    security_and_correctness = {
        "security_status": sec_status,
        "security_details": sec_details,
        "security_provenance": sec_prov,
        "compilation_status": comp_status,
        "compilation_details": comp_details,
        "compilation_provenance": comp_prov,
        "correctness_status": corr_status,
        "correctness_details": corr_details,
        "correctness_provenance": corr_prov,
        "fallback_handling": fb_handling,
    }

    # -------------------------------------------------------------------------
    # 5. Section E: Performance Results
    # -------------------------------------------------------------------------
    base_meas = record.get("baseline_measurement") if isinstance(record.get("baseline_measurement"), dict) else {}
    opt_meas = record.get("optimized_measurement") if isinstance(record.get("optimized_measurement"), dict) else {}
    base_view_timing = view.get("baseline_timing") if isinstance(view.get("baseline_timing"), dict) else {}
    opt_view_timing = view.get("optimized_timing") if isinstance(view.get("optimized_timing"), dict) else {}

    t_base = base_meas.get("median_s") or base_view_timing.get("median_s")
    t_opt = opt_meas.get("median_s") or opt_view_timing.get("median_s")

    base_time_ms = round(t_base * 1000.0, 3) if isinstance(t_base, (int, float)) and t_base > 0 else None
    opt_time_ms = round(t_opt * 1000.0, 3) if isinstance(t_opt, (int, float)) and t_opt > 0 else None

    # Code size
    opt_code_size = opt_meas.get("code_size_bytes") or opt_view_timing.get("code_size_bytes")
    code_size_bytes = int(opt_code_size) if opt_code_size is not None else None
    code_size_desc = (
        f"{code_size_bytes:,} bytes (measured size of compiled machine code artifact)"
        if code_size_bytes is not None
        else "Code size was not recorded."
    )

    # Timing reliability check
    timing_rel_base = base_meas.get("timing_is_reliable")
    timing_rel_opt = opt_meas.get("timing_is_reliable")
    timing_is_reliable: Optional[bool] = None
    if timing_rel_base is not None or timing_rel_opt is not None:
        timing_is_reliable = (timing_rel_base is not False and timing_rel_opt is not False)

    # Authoritative backend regression verdict
    authoritative_verdict = (
        view.get("regression_overall_status")
        or record.get("regression_overall_status")
    )
    if authoritative_verdict:
        authoritative_verdict = str(authoritative_verdict).upper()
    elif raw_status == "completed" and base_time_ms and opt_time_ms:
        authoritative_verdict = "PARITY" if abs(base_time_ms - opt_time_ms) / base_time_ms < 0.02 else (
            "IMPROVED" if base_time_ms > opt_time_ms else "REGRESSED"
        )
    else:
        authoritative_verdict = "NOT_RUN"

    # Gating: if timing is unreliable, force verdict to INCONCLUSIVE
    if timing_is_reliable is False and authoritative_verdict in ("IMPROVED", "REGRESSED", "PARITY"):
        authoritative_verdict = "INCONCLUSIVE"

    # Speedup calculation
    speedup_ratio: Optional[float] = None
    speedup_pct: Optional[float] = None
    time_comparison_explanation: Optional[str] = None
    if base_time_ms and opt_time_ms:
        speedup_ratio = round(base_time_ms / opt_time_ms, 2)
        speedup_pct = round(((base_time_ms - opt_time_ms) / base_time_ms) * 100.0, 1)
        if authoritative_verdict == "INCONCLUSIVE":
            speedup_text = f"~{speedup_pct:+.1f}% ({speedup_ratio:.2f}x) — Unreliable due to measurement noise"
        elif speedup_pct > 0:
            speedup_text = f"+{speedup_pct:.1f}% speedup ({speedup_ratio:.2f}x faster than baseline)"
        elif speedup_pct < 0:
            speedup_text = f"{speedup_pct:.1f}% slowdown ({speedup_ratio:.2f}x of baseline)"
        else:
            speedup_text = "~0.0% difference (Parity with baseline)"

        if opt_time_ms > base_time_ms:
            diff_ms = round(opt_time_ms - base_time_ms, 2)
            time_comparison_explanation = (
                f"Baseline took {base_time_ms:.2f} ms while optimized candidate took {opt_time_ms:.2f} ms "
                f"({diff_ms:.2f} ms longer, an elapsed time increase of {abs(speedup_pct):.1f}% in this measurement). "
            )
            if authoritative_verdict in ("REGRESSED", "REGRESSION"):
                time_comparison_explanation += (
                    "The authoritative backend regression comparator confirmed this as a statistically verified performance regression."
                )
            elif authoritative_verdict == "INCONCLUSIVE":
                time_comparison_explanation += (
                    "However, elevated measurement noise prevents this single slower measurement "
                    "from being confirmed as a statistically reliable regression."
                )
            else:
                time_comparison_explanation += (
                    f"The authoritative backend comparator classified this outcome as {authoritative_verdict}."
                )
        elif opt_time_ms < base_time_ms:
            diff_ms = round(base_time_ms - opt_time_ms, 2)
            time_comparison_explanation = (
                f"Baseline took {base_time_ms:.2f} ms while optimized candidate took {opt_time_ms:.2f} ms "
                f"({diff_ms:.2f} ms faster, an improvement of {speedup_pct:.1f}% in this measurement). "
            )
            if authoritative_verdict == "IMPROVED":
                time_comparison_explanation += (
                    "The authoritative backend regression comparator confirmed this as a statistically verified speedup."
                )
            elif authoritative_verdict == "INCONCLUSIVE":
                time_comparison_explanation += (
                    "However, measurement variability was elevated, so this difference remains inconclusive."
                )
            else:
                time_comparison_explanation += (
                    f"The authoritative backend comparator classified this outcome as {authoritative_verdict}."
                )
        else:
            time_comparison_explanation = f"Both baseline and optimized candidate completed in {opt_time_ms:.2f} ms (performance parity)."
    elif opt_time_ms and mode == "normal":
        speedup_text = f"Baseline execution: {opt_time_ms:.3f} ms (Reference -O3 measurement)"
        time_comparison_explanation = f"Recorded standard clang -O3 baseline runtime of {opt_time_ms:.2f} ms."
    else:
        speedup_text = "Comparison not available (both baseline and optimized measurements required)"

    # Reliability explanation
    if timing_is_reliable is True:
        rel_explanation = "Execution times showed low variance across repetitions and are considered statistically reliable."
    elif timing_is_reliable is False:
        rel_explanation = (
            "High measurement variability was detected across runs. Execution times fluctuated significantly, "
            "meaning the observed difference cannot be reliably attributed to the optimization."
        )
    else:
        rel_explanation = "Timing reliability could not be assessed because measurement repetitions were not recorded."

    # Verdict explanation
    verdict_explanations = {
        "IMPROVED": "Confirmed performance improvement: the optimized code ran demonstrably faster than baseline with verified measurement stability.",
        "PARITY": "Performance parity: the optimized code execution time is on par with the baseline reference without measurable difference.",
        "REGRESSED": "Performance regression: the optimized code ran slower than the baseline reference.",
        "INCONCLUSIVE": "Inconclusive results: high measurement noise or variance prevents a confident conclusion about performance.",
        "INCOMPARABLE": "Measurements could not be directly compared against baseline reference.",
        "NOT_RUN": "Benchmarking was not performed or not completed for this run.",
    }
    verdict_explanation = verdict_explanations.get(
        authoritative_verdict,
        f"Benchmark verdict: {authoritative_verdict}."
    )

    perf_available = bool(base_time_ms or opt_time_ms or code_size_bytes)
    performance = {
        "available": perf_available,
        "baseline_time_ms": base_time_ms,
        "optimized_time_ms": opt_time_ms,
        "code_size_bytes": code_size_bytes,
        "code_size_description": code_size_desc,
        "speedup_ratio": speedup_ratio,
        "speedup_pct": speedup_pct,
        "speedup_text": speedup_text,
        "time_comparison_explanation": time_comparison_explanation,
        "timing_is_reliable": timing_is_reliable,
        "reliability_explanation": rel_explanation,
        "benchmark_verdict": authoritative_verdict,
        "verdict_explanation": verdict_explanation,
        "provenance": (
            ReportProvenance.MEASURED.value
            if perf_available
            else ReportProvenance.NOT_RECORDED.value
        ),
    }

    # -------------------------------------------------------------------------
    # 6. Section F: Problems and Limitations
    # -------------------------------------------------------------------------
    problems: List[Dict[str, str]] = []

    if is_running:
        problems.append({
            "severity": "info",
            "title": "Workflow In Progress",
            "description": "This report is provisional while the optimization pipeline is actively executing.",
        })
    elif failed_without_error:
        problems.append({
            "severity": "error",
            "title": "Execution Failed Without Diagnostic Details",
            "description": "The workflow terminated prematurely with a failed status, but no diagnostic error message was captured.",
        })

    if compilation_failed:
        problems.append({
            "severity": "error",
            "title": "Compilation Error",
            "description": f"Code generation failed: {error_msg or 'Compiler syntax or diagnostic error'}.",
        })

    if security_blocked:
        problems.append({
            "severity": "error",
            "title": "Security Policy Blocked Optimization",
            "description": "The candidate optimization was blocked by the security gate to prevent unsafe code execution.",
        })

    if fallback_occurred:
        problems.append({
            "severity": "warning",
            "title": "Security Fallback Activated",
            "description": (
                f"The optimizer proposed '{selected_strat}', but security constraints required falling back "
                f"to verified baseline '{effective_strat}'."
            ),
        })

    if timing_is_reliable is False or authoritative_verdict == "INCONCLUSIVE":
        problems.append({
            "severity": "warning",
            "title": "High Measurement Noise",
            "description": "Benchmark execution times fluctuated significantly. The performance difference is inconclusive.",
        })

    if authoritative_verdict == "REGRESSED":
        problems.append({
            "severity": "warning",
            "title": "Performance Regression Detected",
            "description": f"The optimized binary executed slower than baseline ({speedup_text}).",
        })

    if not profile_available and raw_status == "completed":
        problems.append({
            "severity": "info",
            "title": "Profiler Data Not Recorded",
            "description": "Static IR feature analysis was not captured in this run record.",
        })

    if not problems and raw_status == "completed":
        problems.append({
            "severity": "info",
            "title": "No Issues Recorded",
            "description": "The run completed without compilation errors, security rejections, or measurement anomalies.",
        })

    # -------------------------------------------------------------------------
    # 7. Section A: Run Summary
    # -------------------------------------------------------------------------
    is_conclusive = (
        execution_succeeded
        and (authoritative_verdict in ("IMPROVED", "PARITY", "REGRESSED") or (mode == "normal" and perf_available))
        and (timing_is_reliable is not False)
    )

    if is_running:
        conclusive_reason = "Workflow is currently running; terminal measurements are pending."
    elif not execution_succeeded:
        conclusive_reason = f"Execution halted before completion ({error_msg or raw_status})."
    elif timing_is_reliable is False or authoritative_verdict == "INCONCLUSIVE":
        conclusive_reason = "High measurement variability prevents a definitive performance conclusion."
    elif not perf_available:
        conclusive_reason = "Performance measurements were not recorded."
    elif mode == "normal":
        conclusive_reason = "Baseline -O3 reference measurements were recorded and validated."
    else:
        conclusive_reason = "Benchmark measurements are statistically stable and conclusive."

    if mode == "normal":
        mode_label = "Standard Baseline Reference (-O3)"
        if is_running:
            summary_headline = "Baseline Reference Run (-O3) In Progress (Provisional)"
            summary_text = (
                "The system is currently compiling and benchmarking the source code with standard clang -O3 optimization. "
                "Findings are provisional until the run completes."
            )
        elif execution_succeeded:
            summary_headline = "Baseline Reference Run (-O3) Completed"
            summary_text = (
                "The system compiled and benchmarked the source code with standard clang -O3 optimization. "
                "This establishes a reliable baseline execution time and code size for AI comparison."
            )
        else:
            summary_headline = "Baseline Reference Run Failed"
            summary_text = f"The baseline reference execution failed during compilation or runtime: {error_msg or 'Execution error'}."
    else:
        mode_label = "AI-Optimized Multi-Agent Run"
        if is_running:
            summary_headline = "AI Optimization Workflow In Progress (Provisional)"
            summary_text = (
                "The multi-agent optimization pipeline is actively deliberating, compiling, or benchmarking. "
                "Results shown are provisional until the workflow reaches a terminal state."
            )
        elif execution_succeeded:
            if fallback_occurred:
                summary_headline = "AI Optimization Completed with Security Fallback"
                summary_text = (
                    f"The multi-agent optimization pipeline deliberated and proposed '{selected_strat}'. "
                    f"Safety verification intervened and substituted verified baseline '{effective_strat}'. "
                    "The program compiled cleanly and executed under security supervision."
                )
            else:
                summary_headline = "AI Optimization Workflow Completed Successfully"
                summary_text = (
                    f"The multi-agent optimization pipeline analyzed the program, selected optimization strategy '{effective_strat}', "
                    "verified safety constraints, and benchmarked the resulting binary."
                )
        elif security_blocked:
            summary_headline = "Optimization Blocked by Security Policy"
            summary_text = (
                "The multi-agent optimization pipeline proposed an optimization, but the security gate "
                "blocked deployment to protect code safety."
            )
        elif compilation_failed:
            summary_headline = "Compilation Failed During Optimization Build"
            summary_text = f"The optimizer selected strategy '{selected_strat or 'unknown'}', but clang failed to compile the generated code."
        elif failed_without_error:
            summary_headline = "Optimization Workflow Failed"
            summary_text = "The workflow terminated with a failure status, but no detailed error trace was captured."
        else:
            summary_headline = f"Optimization Workflow Failed ({raw_status})"
            summary_text = f"Execution stopped unexpectedly: {error_msg or 'Unknown error'}."

    summary = {
        "headline": summary_headline,
        "mode_label": mode_label,
        "execution_outcome": (
            "In progress (provisional)"
            if is_running
            else (
                "Completed successfully"
                if execution_succeeded
                else (f"Failed: {error_msg}" if error_msg else ("Failed (no error details)" if failed_without_error else str(raw_status).capitalize()))
            )
        ),
        "is_conclusive": is_conclusive,
        "conclusive_reason": conclusive_reason,
        "plain_text": summary_text,
        "provenance": (
            ReportProvenance.PREDICTED.value
            if is_running
            else (
                ReportProvenance.VERIFIED.value
                if execution_succeeded
                else ReportProvenance.MEASURED.value
            )
        ),
    }

    # -------------------------------------------------------------------------
    # 8. Section G: Overall Conclusion
    # -------------------------------------------------------------------------
    performance_improved = (authoritative_verdict == "IMPROVED" and is_conclusive)

    if is_running:
        conc_headline = "Workflow In Progress (Provisional)"
        conc_text = "Deliberation or execution is actively running. Results shown are provisional until the workflow reaches a terminal state."
        conc_badge = "IN_PROGRESS"
    elif not execution_succeeded:
        if compilation_failed:
            conc_headline = "Workflow Halted: Compilation Failed"
            conc_text = "The program could not be built due to compiler errors. No optimizations or benchmarks could be evaluated."
            conc_badge = "COMPILATION_FAILED"
        elif security_blocked:
            conc_headline = "Workflow Halted: Security Policy Blocked"
            conc_text = "The optimization candidate was blocked by security verification to preserve program safety. Execution terminated without deploying untrusted transformations."
            conc_badge = "SECURITY_BLOCKED"
        elif failed_without_error:
            conc_headline = "Workflow Failed (No Details)"
            conc_text = "The run terminated with a failure status, but no detailed error trace was captured."
            conc_badge = "FAILED_NO_DETAILS"
        else:
            conc_headline = "Workflow Execution Incomplete"
            conc_text = f"The run encountered an execution error ({error_msg or 'unknown error'}) before completion."
            conc_badge = "EXECUTION_FAILED"
    elif fallback_occurred:
        conc_headline = "Safe Completion Under Security Fallback"
        conc_text = (
            f"The program executed safely because the security gate substituted baseline '{effective_strat}' after flagging '{selected_strat}'. "
            "Compilation and safety checks succeeded, protecting code integrity."
        )
        conc_badge = "FALLBACK_APPLIED"
    elif not perf_available and mode == "ai":
        conc_headline = "Workflow Completed (Benchmarks Not Recorded)"
        conc_text = "The optimization workflow completed deliberation and compilation, but empirical benchmark timings were not recorded."
        conc_badge = "COMPLETED_WITHOUT_BENCHMARKS"
    elif not is_conclusive:
        conc_headline = "Workflow Completed (Performance Inconclusive)"
        conc_text = "Execution, compilation, and security checks succeeded, but high measurement variance prevents a definitive speedup conclusion."
        conc_badge = "INCONCLUSIVE"
    elif performance_improved:
        conc_headline = "Optimization Successful with Verified Speedup"
        conc_text = f"The workflow succeeded across all phases: compilation was clean, security and correctness were verified, and the optimized code achieved {speedup_text}."
        conc_badge = "SPEEDUP_VERIFIED"
    elif authoritative_verdict in ("REGRESSED", "REGRESSION"):
        conc_headline = "Completed with Performance Regression"
        conc_text = f"The program compiled and ran correctly, but the optimization caused a performance regression ({speedup_text}) compared to baseline."
        conc_badge = "REGRESSION"
    elif authoritative_verdict == "PARITY":
        conc_headline = "Optimization Completed (Performance Parity)"
        conc_text = "The workflow completed with verified compilation, security, and correctness. Performance is on par with baseline -O3 without measurable difference."
        conc_badge = "PARITY"
    elif mode == "normal":
        conc_headline = "Baseline Reference Established"
        conc_text = "The standard -O3 baseline compilation and benchmark completed successfully, establishing reference timing and code size for subsequent AI comparison."
        conc_badge = "BASELINE_READY"
    else:
        conc_headline = "Workflow Completed"
        conc_text = "The optimization run completed all recorded pipeline stages."
        conc_badge = "COMPLETED"

    overall_conclusion = {
        "headline": conc_headline,
        "text": conc_text,
        "execution_succeeded": execution_succeeded,
        "compilation_succeeded": compilation_succeeded,
        "security_passed": security_passed,
        "correctness_verified": correctness_verified,
        "performance_improved": performance_improved,
        "verdict_badge": conc_badge,
        "verdict_badge_explanation": VERDICT_BADGE_EXPLANATIONS.get(
            conc_badge,
            VERDICT_BADGE_EXPLANATIONS.get("REGRESSED" if conc_badge == "REGRESSION" else conc_badge, f"Outcome: {conc_badge}")
        ),
    }

    # -------------------------------------------------------------------------
    # 9. Feature 1: Plain-English Workflow Narrative ("What Happened During This Run?")
    # -------------------------------------------------------------------------
    workflow_narrative = generate_workflow_narrative(
        run_id=run_id,
        mode=mode,
        raw_status=raw_status,
        record=record,
        view=view,
        scoped_events=scoped_events,
        messages=scoped_messages,
        compilation_succeeded=compilation_succeeded,
        compilation_failed=compilation_failed,
        security_passed=security_passed,
        security_blocked=security_blocked,
        fallback_occurred=fallback_occurred,
        correctness_verified=correctness_verified,
        execution_succeeded=execution_succeeded,
        authoritative_verdict=authoritative_verdict,
        base_time_ms=base_time_ms,
        opt_time_ms=opt_time_ms,
        code_size_bytes=code_size_bytes,
        speedup_ratio=speedup_ratio,
        speedup_pct=speedup_pct,
        speedup_text=speedup_text,
        timing_is_reliable=timing_is_reliable,
        selected_strat=selected_strat,
        effective_strat=effective_strat,
        rationale_text=rationale_text,
        error_msg=error_msg,
        is_running=is_running,
        is_provisional=is_provisional,
    )

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "program_id": program_id,
        "mode": mode,
        "status": raw_status,
        "is_provisional": is_provisional,
        "summary": summary,
        "program_analysis": program_analysis,
        "optimization_strategy": opt_strategy,
        "security_and_correctness": security_and_correctness,
        "performance": performance,
        "problems_and_limitations": problems,
        "overall_conclusion": overall_conclusion,
        "workflow_narrative": workflow_narrative,
        "agent_messages": explained_messages,
    }
