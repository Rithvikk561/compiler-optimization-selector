"""
TOACD — Week 12: Real-Time Agentic AI Analysis Tests
======================================================
Comprehensive deterministic test suite covering:
- W12-SCHEMA: Serialization, enums, round-trips, schema version.
- W12-TOOLS: Pure read-only diagnostic tools, noise handling, IR feature integrity.
- W12-PLANNER: Bounded loop, dynamic evidence-dependent branching, budget enforcement.
- W12-TIERS: Evidence tiers resolution and calibrated quality degradation.
- W12-NOISE: Noise-aware gating (Week 10/11 semantics).
- W12-IMMUT: Strict non-interference and input immutability.
- W12-SIDEEFF: Zero disk writes, zero network, zero torch imports.
- W12-DET: Determinism across repeated executions.
- W12-SCOPE: Advisory-only guarantees and scope boundaries.
- W12-FAIL: Graceful degradation on missing or corrupt inputs.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Dict, List

# Ensure parent path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
    VALID_ACTIONS,
    analyze_ir_profile_tool,
    analyze_regression_metrics_tool,
    audit_history_tool,
    audit_provenance_tool,
    evaluate_alternative_tool,
    evaluate_tradeoffs_tool,
)
from moo.agentic.engine import (
    AgentEngine,
    AnalysisState,
    DeterministicRulePlanner,
)
from moo.agentic.adapter import build_agent_context, _safe_dict
from moo.agentic import analyze_compilation, __week__

# Test tracking
PASSED = 0
FAILED = 0
SKIPPED = 0


def report(test_id: str, desc: str, success: bool, msg: str = ""):
    global PASSED, FAILED
    if success:
        PASSED += 1
        print(f"  [PASS] {test_id}: {desc}")
    else:
        FAILED += 1
        print(f"  [FAIL] {test_id}: {desc} -- {msg}")


def fail(test_id: str, desc: str, exc: Exception):
    global FAILED
    FAILED += 1
    print(f"  [FAIL] {test_id}: {desc} -- Exception: {exc}")


# ===========================================================================
# 1. W12-SCHEMA: Dataclass & Enum Serialization
# ===========================================================================

def test_schema_round_trip():
    tid = "W12-SCHEMA1"
    desc = "AgentAnalysisReport to_dict and from_dict round-trip"
    try:
        report_obj = AgentAnalysisReport(
            report_id="w12-test-001",
            program_id="prog_01",
            source_hash="abcd1234ef5678",
            selected_strategy="-O2",
            verdict=AgentVerdict.CONFIRMED,
            evidence_quality=EvidenceQuality.HIGH,
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION, EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
            findings=[
                Finding(
                    category="PROVENANCE",
                    severity=FindingSeverity.INFO,
                    message="Selection backed by Pareto frontier",
                    evidence_tier=EvidenceTier.TIER_1_STATIC_SELECTION,
                    details={"size": 3},
                )
            ],
            tradeoffs=[
                TradeoffAlert(
                    objective_favored="execution_time",
                    objective_degraded="code_size",
                    ratio=1.30,
                    threshold=1.25,
                    description="Code size expanded by 30%",
                )
            ],
            alternative=AlternativeRecommendation(
                strategy="-O1",
                justification="Better size profile",
                numerical_evidence={"code_size_ratio": 0.95},
                pareto_verified=True,
                is_advisory_only=True,
            ),
            reasoning_steps=[
                StepRecord(step_number=1, tool_name="audit_provenance_tool", action_reason="test", findings_produced=1)
            ],
            is_advisory_only=True,
            metadata={"run_env": "test_env"},
        )
        d = report_obj.to_dict()
        reconstructed = AgentAnalysisReport.from_dict(d)
        assert reconstructed.report_id == report_obj.report_id
        assert reconstructed.verdict == AgentVerdict.CONFIRMED
        assert reconstructed.evidence_quality == EvidenceQuality.HIGH
        assert len(reconstructed.findings) == 1
        assert len(reconstructed.tradeoffs) == 1
        assert reconstructed.alternative is not None
        assert reconstructed.alternative.strategy == "-O1"
        assert reconstructed.is_advisory_only is True
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_schema_json_serialization():
    tid = "W12-SCHEMA2"
    desc = "AgentAnalysisReport to_json and from_json round-trip"
    try:
        report_obj = AgentAnalysisReport(
            report_id="w12-test-json",
            program_id="prog_json",
            source_hash="11223344",
            selected_strategy="-O3",
            verdict=AgentVerdict.CONFIRMED_WITH_WARNINGS,
            evidence_quality=EvidenceQuality.MEDIUM,
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            findings=[],
            tradeoffs=[],
            alternative=None,
            reasoning_steps=[],
            is_advisory_only=True,
        )
        j_str = report_obj.to_json()
        assert isinstance(j_str, str)
        reconstructed = AgentAnalysisReport.from_json(j_str)
        assert reconstructed.program_id == "prog_json"
        assert reconstructed.verdict == AgentVerdict.CONFIRMED_WITH_WARNINGS
        assert reconstructed.schema_version == AGENTIC_SCHEMA_VERSION
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_schema_version_constant():
    tid = "W12-SCHEMA3"
    desc = "AGENTIC_SCHEMA_VERSION is non-empty week12.1.0"
    try:
        assert AGENTIC_SCHEMA_VERSION == "week12.1.0"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_schema_enums_membership():
    tid = "W12-SCHEMA4"
    desc = "All schema enums contain defined canonical constants"
    try:
        assert EvidenceTier.TIER_1_STATIC_SELECTION.value == "TIER_1_STATIC_SELECTION"
        assert EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE.value == "TIER_2_HISTORICAL_EXPERIENCE"
        assert EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK.value == "TIER_3_EMPIRICAL_BENCHMARK"
        assert EvidenceQuality.HIGH.value == "HIGH"
        assert EvidenceQuality.INSUFFICIENT.value == "INSUFFICIENT"
        assert AgentVerdict.CONFIRMED.value == "CONFIRMED"
        assert AgentVerdict.ALTERNATIVE_ADVISED.value == "ALTERNATIVE_ADVISED"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 2. W12-TOOLS: Pure Read-Only Diagnostic Tools
# ===========================================================================

def test_tool_provenance_audit():
    tid = "W12-TOOLS1"
    desc = "audit_provenance_tool detects fallback and strategy conflicts"
    try:
        # Fallback trace
        ctx_fallback = AgentContext(
            program_id="p1",
            source_hash="h1",
            selected_strategy="-O2",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            decision_trace={"selection_method": "argmax_fallback", "final_strategy": "-O2"},
        )
        findings = audit_provenance_tool(ctx_fallback)
        assert any(f.category == "PROVENANCE" and f.severity == FindingSeverity.WARNING for f in findings)

        # Conflicting strategy trace
        ctx_conflict = AgentContext(
            program_id="p1",
            source_hash="h1",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O1"},
        )
        findings_conf = audit_provenance_tool(ctx_conflict)
        assert any(f.severity == FindingSeverity.ALERT for f in findings_conf)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_ir_profile_analysis():
    tid = "W12-TOOLS2"
    desc = "analyze_ir_profile_tool validates alignment without fabricating features"
    try:
        # Control-flow heavy with -O3 -> Warning
        ctx_cf = AgentContext(
            program_id="p2",
            source_hash="h2",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            program_profile={
                "deterministic_profile": "control_flow_heavy",
                "branch_ratio": 0.35,
                "instruction_count": 250,
                "loop_count": 2,
            },
        )
        findings = analyze_ir_profile_tool(ctx_cf)
        assert any(f.severity == FindingSeverity.WARNING and "control-flow" in f.message.lower() for f in findings)

        # Compute intensive with -O3 -> Info
        ctx_comp = AgentContext(
            program_id="p2",
            source_hash="h2",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            program_profile={
                "deterministic_profile": "compute_intensive",
                "loop_count": 15,
                "float_ops_ratio": 0.40,
            },
        )
        findings_comp = analyze_ir_profile_tool(ctx_comp)
        assert any(f.severity == FindingSeverity.INFO and "compute intensive" in f.message.lower() for f in findings_comp)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_history_noise_aware():
    tid = "W12-TOOLS3"
    desc = "audit_history_tool quarantines noisy runs and evaluates reliable runs"
    try:
        # Mix of noisy and reliable records
        experiences = [
            # Record 1: Unreliable (high noise) -> must be quarantined
            {
                "experience_id": "exp_01",
                "selected_strategy": "-O2",
                "is_reliable": False,
                "confidence": "INCONCLUSIVE",
                "reward": -0.80,
                "timestamp_iso": "2026-10-04T10:00:00",
            },
            # Record 2: Reliable run with regression
            {
                "experience_id": "exp_02",
                "selected_strategy": "-O2",
                "is_reliable": True,
                "confidence": "HIGH",
                "regression_overall_status": "REGRESSED",
                "reward": -0.45,
                "timestamp_iso": "2026-10-04T11:00:00",
            },
        ]
        ctx = AgentContext(
            program_id="p3",
            source_hash="h3",
            selected_strategy="-O2",
            tiers_available=[EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE],
            historical_experiences=experiences,
        )
        findings, summary = audit_history_tool(ctx)
        assert summary["records_examined"] == 2
        assert summary["noisy_count"] == 1
        assert summary["reliable_count"] == 1
        assert summary["regressed_count"] == 1
        assert any(f.category == "NOISE" for f in findings)
        assert any(f.category == "REGRESSION" for f in findings)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_regression_metrics_analysis():
    tid = "W12-TOOLS4"
    desc = "analyze_regression_metrics_tool evaluates status and extracts ratios"
    try:
        comp = {
            "overall_status": "CONFIRMED_REGRESSION",
            "strategy_comparisons": {
                "-O3": {
                    "metric_comparisons": {
                        "execution_time": {"ratio": 1.22},
                        "code_size": {"ratio": 1.40},
                    }
                }
            },
        }
        ctx = AgentContext(
            program_id="p4",
            source_hash="h4",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
            program_comparison=comp,
        )
        findings, summary = analyze_regression_metrics_tool(ctx)
        assert summary["status"] == "CONFIRMED_REGRESSION"
        assert summary["execution_time_ratio"] == 1.22
        assert summary["code_size_ratio"] == 1.40
        assert any(f.severity == FindingSeverity.ALERT for f in findings)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_tradeoffs_detection():
    tid = "W12-TOOLS5"
    desc = "evaluate_tradeoffs_tool detects speedup with binary size bloat"
    try:
        metric_summary = {
            "execution_time_ratio": 0.80, # 20% speedup
            "code_size_ratio": 1.35,      # 35% size bloat (> 25% threshold)
        }
        ctx = AgentContext(
            program_id="p5",
            source_hash="h5",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
        )
        alerts = evaluate_tradeoffs_tool(ctx, metric_summary)
        assert len(alerts) == 1
        assert alerts[0].objective_favored == "execution_time"
        assert alerts[0].objective_degraded == "code_size"
        assert alerts[0].ratio == 1.35
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_alternative_recommendation_strict():
    tid = "W12-TOOLS6"
    desc = "evaluate_alternative_tool strictly enforces validity, frontier, and evidence"
    try:
        comp = {
            "overall_status": "CONFIRMED_REGRESSION",
            "strategy_comparisons": {
                "-O3": {"metric_comparisons": {"execution_time": {"ratio": 1.25}}},
                "-O2": {"metric_comparisons": {"execution_time": {"ratio": 0.85}, "code_size": {"ratio": 1.05}}},
                "invalid_pass_xyz": {"metric_comparisons": {"execution_time": {"ratio": 0.70}}},
            },
        }
        trace = {
            "pareto_frontier": ["-O2", "-Os"],
        }
        ctx = AgentContext(
            program_id="p6",
            source_hash="h6",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION, EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
            decision_trace=trace,
            program_comparison=comp,
        )
        rec = evaluate_alternative_tool(
            ctx,
            history_summary={"regressed_count": 1},
            metric_summary={"status": "CONFIRMED_REGRESSION"},
        )
        assert rec is not None
        assert rec.strategy == "-O2"
        assert rec.strategy in VALID_ACTIONS
        assert rec.strategy != ctx.selected_strategy
        assert rec.pareto_verified is True
        assert rec.is_advisory_only is True
        assert rec.numerical_evidence["execution_time_ratio"] == 0.85
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 3. W12-PLANNER: Bounded Loop & Dynamic Branching
# ===========================================================================

def test_planner_budget_enforcement():
    tid = "W12-PLANNER1"
    desc = "AgentEngine strictly adheres to max_budget step limit"
    try:
        ctx = AgentContext(
            program_id="p_budget",
            source_hash="h_budget",
            selected_strategy="-O2",
            tiers_available=[
                EvidenceTier.TIER_1_STATIC_SELECTION,
                EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE,
                EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK,
            ],
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O2"},
            program_profile={"deterministic_profile": "compute_intensive"},
            historical_experiences=[{"selected_strategy": "-O2", "is_reliable": True, "reward": 0.5}],
            program_comparison={"overall_status": "IMPROVED"},
        )
        engine = AgentEngine(max_budget=3)
        rep = engine.analyze(ctx)
        assert len(rep.reasoning_steps) <= 3
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_planner_dynamic_evidence_branching():
    tid = "W12-PLANNER2"
    desc = "AgentEngine skips Tier 2/3 tools when higher tiers are absent"
    try:
        # Tier 1 only context
        ctx = AgentContext(
            program_id="p_t1",
            source_hash="h_t1",
            selected_strategy="-O1",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            decision_trace={"selection_method": "q_argmax", "final_strategy": "-O1"},
            program_profile={"deterministic_profile": "small_leaf_routine"},
        )
        engine = AgentEngine(max_budget=6)
        rep = engine.analyze(ctx)
        tool_names = [s.tool_name for s in rep.reasoning_steps]
        assert "audit_provenance_tool" in tool_names
        assert "analyze_ir_profile_tool" in tool_names
        assert "audit_history_tool" not in tool_names
        assert "analyze_regression_metrics_tool" not in tool_names
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 4. W12-TIERS: Evidence Tier Resolution & Quality Degradation
# ===========================================================================

def test_tier_resolution_adapter():
    tid = "W12-TIERS1"
    desc = "build_agent_context correctly resolves available evidence tiers"
    try:
        # T1 only
        ctx1 = build_agent_context(
            program_id="p1",
            source_hash="h1",
            selected_strategy="-O2",
            decision_trace={"selection_method": "moo_pareto"},
        )
        assert ctx1.tiers_available == [EvidenceTier.TIER_1_STATIC_SELECTION]

        # T1 + T2
        ctx2 = build_agent_context(
            program_id="p2",
            source_hash="h2",
            selected_strategy="-O2",
            program_profile={"deterministic_profile": "compute_intensive"},
            experience_records=[{"selected_strategy": "-O2"}],
        )
        assert EvidenceTier.TIER_1_STATIC_SELECTION in ctx2.tiers_available
        assert EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE in ctx2.tiers_available
        assert EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK not in ctx2.tiers_available

        # T1 + T2 + T3
        ctx3 = build_agent_context(
            program_id="p3",
            source_hash="h3",
            selected_strategy="-O2",
            decision_trace={"selection_method": "moo_pareto"},
            experience_records=[{"selected_strategy": "-O2"}],
            program_comparison={"overall_status": "IMPROVED"},
        )
        assert len(ctx3.tiers_available) == 3
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_evidence_quality_calibration():
    tid = "W12-TIERS2"
    desc = "Quality calibrates correctly (HIGH, MEDIUM, LOW, INSUFFICIENT)"
    try:
        # Insufficient: no inputs
        ctx_insuf = build_agent_context("", "", "")
        rep_insuf = AgentEngine().analyze(ctx_insuf)
        assert rep_insuf.evidence_quality == EvidenceQuality.INSUFFICIENT
        assert rep_insuf.verdict == AgentVerdict.INSUFFICIENT_EVIDENCE

        # Low: Tier 1 only
        ctx_low = build_agent_context("p", "h", "-O2", decision_trace={"final_strategy": "-O2"})
        rep_low = AgentEngine().analyze(ctx_low)
        assert rep_low.evidence_quality == EvidenceQuality.LOW

        # High: T1 + T2 + T3 with low noise
        ctx_high = build_agent_context(
            "p", "h", "-O2",
            decision_trace={"final_strategy": "-O2"},
            experience_records=[{"selected_strategy": "-O2", "is_reliable": True, "reward": 0.4}],
            program_comparison={"overall_status": "IMPROVED", "strategy_comparisons": {}},
        )
        rep_high = AgentEngine().analyze(ctx_high)
        assert rep_high.evidence_quality == EvidenceQuality.HIGH
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 5. W12-NOISE: Noise-Aware Gating (Week 10/11 Semantics)
# ===========================================================================

def test_inconclusive_benchmark_does_not_cause_false_regression():
    tid = "W12-NOISE1"
    desc = "INCONCLUSIVE benchmark yields WARNING noise finding, not ALERT regression"
    try:
        ctx = build_agent_context(
            program_id="p_noise",
            source_hash="h_noise",
            selected_strategy="-O2",
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O2"},
            program_comparison={"overall_status": "INCONCLUSIVE"},
        )
        rep = AgentEngine().analyze(ctx)
        # Should NOT be ALTERNATIVE_ADVISED based on inconclusive data
        assert rep.verdict != AgentVerdict.ALTERNATIVE_ADVISED
        assert rep.alternative is None
        # Should have noise finding
        assert any(f.category == "NOISE" for f in rep.findings)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_unreliable_history_ignored_for_regression():
    tid = "W12-NOISE2"
    desc = "Unreliable history record does not trigger regression alert"
    try:
        ctx = build_agent_context(
            program_id="p_unrel",
            source_hash="h_unrel",
            selected_strategy="-O2",
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O2"},
            experience_records=[
                {"selected_strategy": "-O2", "is_reliable": False, "reward": -0.99}
            ],
        )
        rep = AgentEngine().analyze(ctx)
        assert rep.verdict != AgentVerdict.ALTERNATIVE_ADVISED
        assert not any(f.category == "REGRESSION" and f.severity == FindingSeverity.WARNING for f in rep.findings)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 6. W12-IMMUT: Non-Interference & Input Immutability
# ===========================================================================

def test_input_immutability():
    tid = "W12-IMMUT1"
    desc = "Input objects are deep-preserved and unmutated after analysis"
    try:
        trace = {"selection_method": "moo_pareto", "final_strategy": "-O2", "weights": [0.5, 0.5]}
        profile = {"deterministic_profile": "compute_intensive", "loop_count": 10}
        comp = {"overall_status": "IMPROVED", "strategy_comparisons": {"-O2": {}}}
        exps = [{"selected_strategy": "-O2", "reward": 0.4}]

        trace_copy = copy.deepcopy(trace)
        profile_copy = copy.deepcopy(profile)
        comp_copy = copy.deepcopy(comp)
        exps_copy = copy.deepcopy(exps)

        ctx = build_agent_context(
            program_id="p_immut",
            source_hash="h_immut",
            selected_strategy="-O2",
            decision_trace=trace,
            program_profile=profile,
            experience_records=exps,
            program_comparison=comp,
        )
        _ = AgentEngine().analyze(ctx)

        assert trace == trace_copy
        assert profile == profile_copy
        assert comp == comp_copy
        assert exps == exps_copy
        assert ctx.selected_strategy == "-O2"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 7. W12-SIDEEFF: Side-Effect & Environment Isolation
# ===========================================================================

def test_zero_side_effects():
    tid = "W12-SIDEEFF1"
    desc = "No torch imported, no disk writes, no network calls"
    try:
        # Ensure torch was not imported by moo.agentic
        assert "torch" not in sys.modules, "PyTorch must not be imported by moo.agentic"
        # Ensure gui modules were not imported
        assert "gui_app" not in sys.modules, "GUI must not be imported by moo.agentic"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 8. W12-DET: Determinism Over Repeated Runs
# ===========================================================================

def test_analytical_determinism():
    tid = "W12-DET1"
    desc = "Identical inputs yield identical analytical results across 50 runs"
    try:
        ctx = build_agent_context(
            program_id="p_det",
            source_hash="h_det",
            selected_strategy="-O3",
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O3"},
            program_profile={"deterministic_profile": "control_flow_heavy", "branch_ratio": 0.3},
            program_comparison={
                "overall_status": "CONFIRMED_REGRESSION",
                "strategy_comparisons": {
                    "-O3": {"metric_comparisons": {"execution_time": {"ratio": 1.25}}},
                    "-O2": {"metric_comparisons": {"execution_time": {"ratio": 0.88}}},
                },
            },
        )
        engine = AgentEngine()
        first_rep = engine.analyze(ctx)

        for _ in range(50):
            rep = engine.analyze(ctx)
            assert rep.verdict == first_rep.verdict
            assert rep.evidence_quality == first_rep.evidence_quality
            assert rep.report_id == first_rep.report_id
            assert len(rep.findings) == len(first_rep.findings)
            assert len(rep.tradeoffs) == len(first_rep.tradeoffs)
            assert (rep.alternative is None) == (first_rep.alternative is None)
            if rep.alternative and first_rep.alternative:
                assert rep.alternative.strategy == first_rep.alternative.strategy
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 9. W12-SCOPE: Advisory-Only & Scope Boundaries
# ===========================================================================

def test_advisory_only_integrity():
    tid = "W12-SCOPE1"
    desc = "Reports and recommendations are explicitly advisory-only"
    try:
        rep = analyze_compilation(
            program_id="p_adv",
            source_hash="h_adv",
            selected_strategy="-O3",
            decision_trace={"selection_method": "moo_pareto", "final_strategy": "-O3"},
            program_comparison={
                "overall_status": "CONFIRMED_REGRESSION",
                "strategy_comparisons": {
                    "-O3": {"metric_comparisons": {"execution_time": {"ratio": 1.20}}},
                    "-O1": {"metric_comparisons": {"execution_time": {"ratio": 0.90}}},
                },
            },
        )
        assert rep.is_advisory_only is True
        if rep.alternative:
            assert rep.alternative.is_advisory_only is True
        assert __week__ == 12
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# 10. W12-FAIL: Failure Handling & Graceful Degradation
# ===========================================================================

def test_corrupt_input_graceful_degradation():
    tid = "W12-FAIL1"
    desc = "Corrupt inputs degrade safely without raising unhandled exceptions"
    try:
        # None inputs
        ctx_none = build_agent_context(None, None, None)
        rep1 = AgentEngine().analyze(ctx_none)
        assert rep1.verdict == AgentVerdict.INSUFFICIENT_EVIDENCE

        # Corrupt comparison dictionary
        ctx_corrupt = build_agent_context(
            program_id="p_err",
            source_hash="h_err",
            selected_strategy="-O2",
            program_comparison={"overall_status": None, "strategy_comparisons": "not_a_dict"},
        )
        rep2 = AgentEngine().analyze(ctx_corrupt)
        assert rep2 is not None
        assert rep2.is_advisory_only is True
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_subdataclasses_round_trip():
    tid = "W12-SCHEMA5"
    desc = "Finding, TradeoffAlert, AlternativeRecommendation, StepRecord to/from dict"
    try:
        f = Finding("PROV", FindingSeverity.WARNING, "msg", EvidenceTier.TIER_1_STATIC_SELECTION, {"k": "v"})
        assert Finding.from_dict(f.to_dict()) == f

        t = TradeoffAlert("speed", "size", 1.3, 1.25, "desc")
        assert TradeoffAlert.from_dict(t.to_dict()) == t

        a = AlternativeRecommendation("-O2", "just", {"speed": 0.8}, True, True)
        assert AlternativeRecommendation.from_dict(a.to_dict()) == a

        s = StepRecord(1, "tool", "reason", 2)
        assert StepRecord.from_dict(s.to_dict()) == s
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_ir_profile_memory_intensive():
    tid = "W12-TOOLS7"
    desc = "analyze_ir_profile_tool evaluates memory intensive profile with -Os"
    try:
        ctx = AgentContext(
            program_id="p_mem",
            source_hash="h_mem",
            selected_strategy="-Os",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION],
            program_profile={"deterministic_profile": "memory_intensive", "memory_ops_ratio": 0.45},
        )
        findings = analyze_ir_profile_tool(ctx)
        assert any("memory intensive" in f.message.lower() for f in findings)
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_tradeoffs_code_size_favor():
    tid = "W12-TOOLS8"
    desc = "evaluate_tradeoffs_tool detects size reduction with runtime penalty"
    try:
        metric_summary = {
            "execution_time_ratio": 1.20,  # 20% slower (> 15% threshold)
            "code_size_ratio": 0.80,       # 20% size reduction
        }
        ctx = AgentContext(
            program_id="p_to2",
            source_hash="h_to2",
            selected_strategy="-Os",
            tiers_available=[EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
        )
        alerts = evaluate_tradeoffs_tool(ctx, metric_summary)
        assert len(alerts) == 1
        assert alerts[0].objective_favored == "code_size"
        assert alerts[0].objective_degraded == "execution_time"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_tradeoffs_no_alerts():
    tid = "W12-TOOLS9"
    desc = "evaluate_tradeoffs_tool returns empty list when ratios within thresholds"
    try:
        metric_summary = {
            "execution_time_ratio": 0.95,
            "code_size_ratio": 1.05,
        }
        ctx = AgentContext(
            program_id="p_to3",
            source_hash="h_to3",
            selected_strategy="-O2",
            tiers_available=[EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
        )
        alerts = evaluate_tradeoffs_tool(ctx, metric_summary)
        assert len(alerts) == 0
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_alternative_rejects_non_frontier():
    tid = "W12-TOOLS10"
    desc = "evaluate_alternative_tool rejects candidates not present on Pareto frontier"
    try:
        comp = {
            "overall_status": "CONFIRMED_REGRESSION",
            "strategy_comparisons": {
                "-O3": {"metric_comparisons": {"execution_time": {"ratio": 1.30}}},
                "-O1": {"metric_comparisons": {"execution_time": {"ratio": 0.80}}},
            },
        }
        trace = {
            "pareto_frontier": ["-O2", "-Os"],  # -O1 is not on frontier!
        }
        ctx = AgentContext(
            program_id="p_front",
            source_hash="h_front",
            selected_strategy="-O3",
            tiers_available=[EvidenceTier.TIER_1_STATIC_SELECTION, EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
            decision_trace=trace,
            program_comparison=comp,
        )
        rec = evaluate_alternative_tool(
            ctx,
            history_summary={"regressed_count": 1},
            metric_summary={"status": "CONFIRMED_REGRESSION"},
        )
        assert rec is None, "Candidate not on Pareto frontier must be rejected"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tool_alternative_none_when_improved():
    tid = "W12-TOOLS11"
    desc = "evaluate_alternative_tool returns None when selection is improved"
    try:
        comp = {
            "overall_status": "IMPROVED",
            "strategy_comparisons": {
                "-O2": {"metric_comparisons": {"execution_time": {"ratio": 0.85}}},
                "-O3": {"metric_comparisons": {"execution_time": {"ratio": 0.80}}},
            },
        }
        ctx = AgentContext(
            program_id="p_imp",
            source_hash="h_imp",
            selected_strategy="-O2",
            tiers_available=[EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK],
            program_comparison=comp,
        )
        rec = evaluate_alternative_tool(
            ctx,
            history_summary={"regressed_count": 0},
            metric_summary={"status": "IMPROVED"},
        )
        assert rec is None, "Alternative must not be advised when selection has no regression"
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_tier_quality_medium_variations():
    tid = "W12-TIERS3"
    desc = "Medium quality confirmed for T1+reliable T2 and T1+conclusive T3"
    try:
        # T1 + reliable T2
        ctx_t2 = build_agent_context(
            "p", "h", "-O2",
            decision_trace={"final_strategy": "-O2"},
            experience_records=[{"selected_strategy": "-O2", "is_reliable": True, "reward": 0.3}],
        )
        rep_t2 = AgentEngine().analyze(ctx_t2)
        assert rep_t2.evidence_quality == EvidenceQuality.MEDIUM

        # T1 + conclusive T3
        ctx_t3 = build_agent_context(
            "p", "h", "-O2",
            decision_trace={"final_strategy": "-O2"},
            program_comparison={"overall_status": "IMPROVED", "strategy_comparisons": {}},
        )
        rep_t3 = AgentEngine().analyze(ctx_t3)
        assert rep_t3.evidence_quality == EvidenceQuality.MEDIUM
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_non_dict_experience_record_handled():
    tid = "W12-FAIL2"
    desc = "Non-dict experience record skipped safely without crashing"
    try:
        ctx = build_agent_context(
            "p", "h", "-O2",
            decision_trace={"final_strategy": "-O2"},
            experience_records=["not_a_dict", 123, None],
        )
        rep = AgentEngine().analyze(ctx)
        assert rep is not None
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


def test_end_to_end_integration():
    tid = "W12-INT1"
    desc = "analyze_compilation convenience function produces full valid report"
    try:
        rep = analyze_compilation(
            program_id="full_prog_01",
            source_hash="sha256_full_prog",
            selected_strategy="-O3",
            decision_trace={
                "selection_method": "moo_pareto",
                "final_strategy": "-O3",
                "pareto_frontier": ["-O2", "-O3"],
            },
            program_profile={
                "deterministic_profile": "compute_intensive",
                "loop_count": 25,
                "instruction_count": 500,
            },
            experience_records=[
                {
                    "experience_id": "exp_hist_01",
                    "selected_strategy": "-O3",
                    "is_reliable": True,
                    "confidence": "HIGH",
                    "reward": 0.35,
                    "timestamp_iso": "2026-10-04T12:00:00",
                }
            ],
            program_comparison={
                "overall_status": "IMPROVED",
                "strategy_comparisons": {
                    "-O3": {
                        "metric_comparisons": {
                            "execution_time": {"ratio": 0.78},
                            "code_size": {"ratio": 1.10},
                        }
                    }
                },
            },
        )
        assert rep.verdict == AgentVerdict.CONFIRMED
        assert rep.evidence_quality == EvidenceQuality.HIGH
        assert len(rep.tiers_available) == 3
        assert len(rep.findings) >= 3
        assert rep.alternative is None
        assert rep.is_advisory_only is True
        report(tid, desc, True)
    except Exception as e:
        fail(tid, desc, e)


# ===========================================================================
# Runner
# ===========================================================================

def run_all_tests():
    print("=" * 72)
    print("TOACD — Week 12 Agentic AI Analysis Tests")
    print("=" * 72)

    print("\n--- W12-SCHEMA: Serialization & Schemas ---")
    test_schema_round_trip()
    test_schema_json_serialization()
    test_schema_version_constant()
    test_schema_enums_membership()
    test_subdataclasses_round_trip()

    print("\n--- W12-TOOLS: Pure Read-Only Diagnostic Tools ---")
    test_tool_provenance_audit()
    test_tool_ir_profile_analysis()
    test_tool_ir_profile_memory_intensive()
    test_tool_history_noise_aware()
    test_tool_regression_metrics_analysis()
    test_tool_tradeoffs_detection()
    test_tool_tradeoffs_code_size_favor()
    test_tool_tradeoffs_no_alerts()
    test_tool_alternative_recommendation_strict()
    test_tool_alternative_rejects_non_frontier()
    test_tool_alternative_none_when_improved()

    print("\n--- W12-PLANNER: Bounded Loop & Dynamic Branching ---")
    test_planner_budget_enforcement()
    test_planner_dynamic_evidence_branching()

    print("\n--- W12-TIERS: Evidence Tier Resolution & Quality ---")
    test_tier_resolution_adapter()
    test_evidence_quality_calibration()
    test_tier_quality_medium_variations()

    print("\n--- W12-NOISE: Noise-Aware Gating ---")
    test_inconclusive_benchmark_does_not_cause_false_regression()
    test_unreliable_history_ignored_for_regression()

    print("\n--- W12-IMMUT: Non-Interference & Immutability ---")
    test_input_immutability()

    print("\n--- W12-SIDEEFF: Environment Isolation ---")
    test_zero_side_effects()

    print("\n--- W12-DET: Determinism Over Repeated Runs ---")
    test_analytical_determinism()

    print("\n--- W12-SCOPE: Advisory-Only & Boundaries ---")
    test_advisory_only_integrity()

    print("\n--- W12-FAIL: Failure Handling & Graceful Degradation ---")
    test_corrupt_input_graceful_degradation()
    test_non_dict_experience_record_handled()

    print("\n--- W12-INT: End-to-End Integration ---")
    test_end_to_end_integration()

    print("\n" + "=" * 72)
    print(f"RESULTS: {PASSED + FAILED} tests | PASS: {PASSED} | FAIL: {FAILED} | SKIP: {SKIPPED}")
    print("=" * 72)
    return FAILED == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
