"""
moo/tests/test_stage8_classification.py — Tests for the Deterministic Program Profiler.

Despite the historical name 'classification', this test suite verifies the
deterministic IR-based Program Profiler (Week 7 Phase 2A).

Tests at minimum:
 1. Threshold JSON loads correctly.
 2. Required thresholds exist.
 3. Same input features always produce same profile (Determinism).
 4. Trivial program handling works.
 5. Loop-oriented rule works.
 6. Compute-oriented rule works.
 7. Memory-oriented rule works.
 8. Call-oriented rule works.
 9. Mixed profile works.
10. Missing/invalid feature input fails safely.
11. No confidence score is produced.
12. Profile result is JSON serializable.
13. Canonical 8-feature names are preserved.
14. No 6-feature schema is accidentally used.
"""

from __future__ import annotations

import json
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_SCRIPT_DIR)
_PS_DIR = os.path.dirname(_MOO_DIR)
_CODES_DIR = os.path.dirname(_PS_DIR)
_TC_DIR = os.path.join(_CODES_DIR, "test_cases")
TC1_PATH = os.path.join(_TC_DIR, "TC1_loop_heavy.c")

if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)

from moo.decision_trace import (
    DecisionTrace,
    ObjectiveSnapshot,
    SELECTION_METHOD_MOO_AWARE,
)
from moo.xai import (
    CANONICAL_IR_FEATURE_NAMES,
    XAIResult,
    format_xai_summary,
)
from moo.program_profiler import (
    PROFILE_LOOP_ORIENTED,
    PROFILE_COMPUTE_ORIENTED,
    PROFILE_MEMORY_ORIENTED,
    PROFILE_CALL_ORIENTED,
    PROFILE_MIXED,
    PROFILE_TRIVIAL,
    PROFILE_UNKNOWN,
    VALID_PROFILE_LABELS,
    ProgramProfile,
    get_default_thresholds_path,
    load_thresholds,
    profile_program,
)


# ---------------------------------------------------------------------------
# Test Infrastructure
# ---------------------------------------------------------------------------
_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{tag}] {tid}: {name}{suffix}")


def skip(tid: str, name: str, reason: str = "") -> None:
    _results.append((tid, name, "SKIP"))
    print(f"  [SKIP] {tid}: {name}  {reason}")


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------
_FIXED_THRESHOLDS = {
    "trivial_instructions": 35.0,
    "branch_count": 9.0,
    "compute_count": 5.0,
    "mem_count": 45.25,
    "call_count": 2.0,
}


def _make_features(
    inst: float = 60.0,
    bb: float = 4.0,
    br: float = 3.0,
    mem: float = 20.0,
    math_val: float = 2.0,
    float_val: float = 0.0,
    vec: float = 0.0,
    call: float = 1.0,
) -> dict[str, float]:
    return {
        "BasicBlocksCount": float(bb),
        "InstructionsCount": float(inst),
        "BranchCount": float(br),
        "MemInstCount": float(mem),
        "MathInstCount": float(math_val),
        "FloatInstCount": float(float_val),
        "VectorInstCount": float(vec),
        "CallInstCount": float(call),
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_p1_threshold_json_loads():
    tid, name = "P1", "Threshold JSON loads correctly"
    json_path = get_default_thresholds_path()
    assert os.path.isfile(json_path), f"thresholds.json not found at {json_path}"

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict), "thresholds.json must be a valid JSON dictionary"
    assert "thresholds" in data, "thresholds.json must contain 'thresholds' key"
    report(tid, name, True)


def test_p2_required_thresholds_exist():
    tid, name = "P2", "Required thresholds exist"
    thresh = load_thresholds()
    required = [
        "trivial_instructions",
        "branch_count",
        "compute_count",
        "mem_count",
        "call_count",
    ]
    for req in required:
        assert req in thresh, f"Missing required threshold key: {req}"
        assert isinstance(thresh[req], (int, float)), f"{req} must be a number"
        assert thresh[req] > 0, f"{req} must be positive"
    report(tid, name, True)


def test_p3_determinism_same_input_same_profile():
    tid, name = "P3", "Same input features always produce same profile (Determinism)"
    f = _make_features(inst=100.0, br=15.0, mem=20.0, math_val=2.0)
    ref = profile_program(f, thresholds=_FIXED_THRESHOLDS)

    for _ in range(50):
        current = profile_program(f, thresholds=_FIXED_THRESHOLDS)
        assert current.label == ref.label
        assert current.dominant_feature == ref.dominant_feature
        assert math.isclose(current.dominant_feature_value, ref.dominant_feature_value)
        assert current.is_trivial == ref.is_trivial
        assert current.profile_method == ref.profile_method
    report(tid, name, True)


def test_p4_trivial_program_handling():
    tid, name = "P4", "Trivial program handling works"
    # InstructionsCount < 35.0
    f_trivial = _make_features(inst=24.0, br=0.0, mem=5.0)
    prof = profile_program(f_trivial, thresholds=_FIXED_THRESHOLDS)
    assert prof.is_trivial is True
    assert prof.label == PROFILE_TRIVIAL
    assert prof.dominant_feature == "InstructionsCount"
    assert math.isclose(prof.dominant_feature_value, 24.0)

    # Barely non-trivial: InstructionsCount >= 35.0
    f_non_trivial = _make_features(inst=35.0, br=1.0, mem=10.0)
    prof2 = profile_program(f_non_trivial, thresholds=_FIXED_THRESHOLDS)
    assert prof2.is_trivial is False
    assert prof2.label != PROFILE_TRIVIAL
    report(tid, name, True)


def test_p5_loop_oriented_rule():
    tid, name = "P5", "Loop-oriented rule works"
    # High branches (20 > 9.0), other dimensions sub-threshold
    f = _make_features(inst=120.0, br=20.0, mem=20.0, math_val=2.0, call=0.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)
    assert prof.label == PROFILE_LOOP_ORIENTED
    assert prof.dominant_feature == "BranchCount"
    assert math.isclose(prof.dominant_feature_value, 20.0)
    assert prof.is_trivial is False
    report(tid, name, True)


def test_p6_compute_oriented_rule():
    tid, name = "P6", "Compute-oriented rule works"
    # High math and float (Math=10, Float=8 -> Compute=18 > 5.0), others low
    f = _make_features(inst=100.0, br=2.0, mem=20.0, math_val=10.0, float_val=8.0, call=0.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)
    assert prof.label == PROFILE_COMPUTE_ORIENTED
    assert prof.dominant_feature in ("MathInstCount", "FloatInstCount")
    assert math.isclose(prof.dominant_feature_value, 18.0)
    report(tid, name, True)


def test_p7_memory_oriented_rule():
    tid, name = "P7", "Memory-oriented rule works"
    # High memory (Mem=90 > 45.25), others sub-threshold
    f = _make_features(inst=180.0, br=3.0, mem=90.0, math_val=2.0, call=0.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)
    assert prof.label == PROFILE_MEMORY_ORIENTED
    assert prof.dominant_feature == "MemInstCount"
    assert math.isclose(prof.dominant_feature_value, 90.0)
    report(tid, name, True)


def test_p8_call_oriented_rule():
    tid, name = "P8", "Call-oriented rule works"
    # High call count (Call=10 > 2.0), others low
    f = _make_features(inst=80.0, br=2.0, mem=15.0, math_val=1.0, call=10.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)
    assert prof.label == PROFILE_CALL_ORIENTED
    assert prof.dominant_feature == "CallInstCount"
    assert math.isclose(prof.dominant_feature_value, 10.0)
    report(tid, name, True)


def test_p9_mixed_profile():
    tid, name = "P9", "Mixed profile works"
    # Scenario A: Balanced sub-threshold across all dimensions
    f_sub = _make_features(inst=50.0, br=4.0, mem=15.0, math_val=2.0, call=1.0)
    prof_sub = profile_program(f_sub, thresholds=_FIXED_THRESHOLDS)
    assert prof_sub.label == PROFILE_MIXED

    # Scenario B: Co-dominant dimensions (both loop and compute are equally high above threshold)
    # Loop ratio = 18 / 9 = 2.0
    # Compute ratio = 10 / 5 = 2.0
    f_codom = _make_features(inst=120.0, br=18.0, mem=20.0, math_val=10.0, call=0.0)
    prof_codom = profile_program(f_codom, thresholds=_FIXED_THRESHOLDS)
    assert prof_codom.label == PROFILE_MIXED
    report(tid, name, True)


def test_p10_missing_invalid_input_fails_safely():
    tid, name = "P10", "Missing/invalid feature input fails safely"
    # None input
    prof1 = profile_program(None)
    assert prof1.label == PROFILE_UNKNOWN
    assert prof1.is_trivial is False

    # Empty dict
    prof2 = profile_program({})
    assert prof2.label == PROFILE_UNKNOWN

    # Invalid feature values (strings, malformed types)
    bad_dict = {"InstructionsCount": "bad", "BranchCount": None}
    prof3 = profile_program(bad_dict)
    assert prof3.label in VALID_PROFILE_LABELS

    # Empty sequence
    prof4 = profile_program([])
    assert prof4.label == PROFILE_UNKNOWN
    report(tid, name, True)


def test_p11_no_confidence_score_produced():
    tid, name = "P11", "No confidence score is produced"
    f = _make_features(inst=100.0, br=15.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)
    d = prof.to_dict()

    prohibited_fields = ["confidence", "confidence_score", "probability", "trust", "score", "certainty"]
    for field in prohibited_fields:
        assert not hasattr(prof, field), f"Prohibited attribute '{field}' found on ProgramProfile!"
        assert field not in d, f"Prohibited key '{field}' found in ProgramProfile.to_dict()!"
    report(tid, name, True)


def test_p12_profile_result_json_serializable():
    tid, name = "P12", "Profile result is JSON serializable"
    f = _make_features(inst=100.0, br=15.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)

    d = prof.to_dict()
    assert isinstance(d, dict)
    json_str = json.dumps(d)
    assert isinstance(json_str, str)

    loaded = json.loads(json_str)
    reconstructed = ProgramProfile.from_dict(loaded)

    assert reconstructed.label == prof.label
    assert reconstructed.dominant_feature == prof.dominant_feature
    assert math.isclose(reconstructed.dominant_feature_value, prof.dominant_feature_value)
    assert reconstructed.is_trivial == prof.is_trivial
    assert reconstructed.profile_method == prof.profile_method
    assert len(reconstructed.all_features) == 8
    report(tid, name, True)


def test_p13_canonical_8_feature_names_preserved():
    tid, name = "P13", "Canonical 8-feature names are preserved"
    f = _make_features(inst=50.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)

    assert len(prof.all_features) == 8, f"Expected 8 features, got {len(prof.all_features)}"
    for name_feat in CANONICAL_IR_FEATURE_NAMES:
        assert name_feat in prof.all_features, f"Missing canonical feature: {name_feat}"
        assert isinstance(prof.all_features[name_feat], float)
    report(tid, name, True)


def test_p14_no_6_feature_schema_used():
    tid, name = "P14", "No 6-feature schema is accidentally used"
    legacy_6_features = [
        "num_functions",
        "num_branches",
        "num_loops",
        "num_calls",
        "num_memory_ops",
        "num_arithmetic_ops",
    ]
    f = _make_features(inst=50.0)
    prof = profile_program(f, thresholds=_FIXED_THRESHOLDS)

    for legacy in legacy_6_features:
        assert legacy not in prof.all_features, f"Accidental use of legacy 6-feature name: {legacy}"

    # Also verify thresholds.json feature schema
    json_path = get_default_thresholds_path()
    if os.path.isfile(json_path):
        with open(json_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh).get("metadata", {})
        schema = meta.get("feature_schema", [])
        assert len(schema) == 8, f"thresholds.json schema must have 8 features, got {len(schema)}"
        for legacy in legacy_6_features:
            assert legacy not in schema, f"Legacy 6-feature name in thresholds.json: {legacy}"
    report(tid, name, True)


# ---------------------------------------------------------------------------
# Phase 2B Runtime Integration Tests (PB1 - PB8)
# ---------------------------------------------------------------------------

def test_pb1_runtime_flow_generates_profile():
    tid, name = "PB1", "Profile is generated during normal runtime flow"
    from optimization_selector import get_best_optimization
    assert os.path.isfile(TC1_PATH), f"TC1_loop_heavy.c not found at {TC1_PATH}"

    strat, trace = get_best_optimization(TC1_PATH, return_trace=True)
    assert strat is not None, "get_best_optimization returned None strategy"
    assert trace is not None, "get_best_optimization returned None trace"
    assert trace.program_profile is not None, "trace.program_profile was not generated"
    assert isinstance(trace.program_profile, dict), "trace.program_profile must be a dict"
    assert "label" in trace.program_profile, "trace.program_profile missing 'label'"
    assert "dominant_feature" in trace.program_profile, "trace.program_profile missing 'dominant_feature'"
    report(tid, name, True)


def test_pb2_profile_attached_to_decision_trace():
    tid, name = "PB2", "Profile is attached to decision trace with full schema"
    from optimization_selector import get_best_optimization
    strat, trace = get_best_optimization(TC1_PATH, return_trace=True)
    assert trace is not None
    prof = trace.program_profile
    assert prof is not None
    required_keys = [
        "label",
        "dominant_feature",
        "dominant_feature_value",
        "profile_method",
        "is_trivial",
        "all_features",
    ]
    for k in required_keys:
        assert k in prof, f"Missing key '{k}' in trace.program_profile"
    assert prof["label"] in VALID_PROFILE_LABELS, f"Invalid profile label: {prof['label']}"
    assert isinstance(prof["all_features"], dict)
    assert len(prof["all_features"]) == 8
    report(tid, name, True)


def test_pb3_profile_attached_to_xai_result():
    tid, name = "PB3", "Profile is attached to XAI result via to_xai_result"
    from optimization_selector import get_best_optimization
    strat, trace, xai_res = get_best_optimization(TC1_PATH, return_trace=True, return_xai=True)
    assert trace is not None and xai_res is not None
    assert xai_res.program_profile is not None, "xai_res.program_profile is None"
    assert xai_res.program_profile == trace.program_profile, "XAI profile does not match trace profile"
    assert xai_res.program_profile["label"] == trace.program_profile["label"]
    report(tid, name, True)


def test_pb4_profile_survives_serialization():
    tid, name = "PB4", "Profile survives DecisionTrace and XAIResult JSON round-trips"
    from optimization_selector import get_best_optimization
    strat, trace, xai_res = get_best_optimization(TC1_PATH, return_trace=True, return_xai=True)
    assert trace is not None and xai_res is not None

    # DecisionTrace round-trip
    d = trace.to_dict()
    json_str = json.dumps(d)
    trace_reconstructed = DecisionTrace.from_dict(json.loads(json_str))
    assert trace_reconstructed.program_profile == trace.program_profile

    # XAIResult round-trip
    xd = xai_res.to_dict()
    json_xai_str = json.dumps(xd)
    xai_reconstructed = XAIResult.from_dict(json.loads(json_xai_str))
    assert xai_reconstructed.program_profile == xai_res.program_profile
    report(tid, name, True)


def test_pb5_valid_program_produces_expected_profile_structure():
    tid, name = "PB5", "Valid program produces expected profile structure"
    feats = _make_features(inst=120.0, br=25.0, mem=20.0, math_val=2.0)
    prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
    p_dict = prof.to_dict()
    assert p_dict["label"] == PROFILE_LOOP_ORIENTED
    assert p_dict["dominant_feature"] == "BranchCount"
    assert p_dict["is_trivial"] is False
    assert math.isclose(p_dict["dominant_feature_value"], 25.0)
    assert p_dict["profile_method"] == "ir_heuristic_threshold"
    report(tid, name, True)


def test_pb6_unknown_profile_safely_represented():
    tid, name = "PB6", "Unknown/invalid profile remains safely represented"
    prof_unknown = profile_program(None)
    assert prof_unknown.label == PROFILE_UNKNOWN
    assert prof_unknown.is_trivial is False

    # Attach unknown profile dict to trace
    dt = DecisionTrace(
        ai_top_choice="-O2",
        ai_top_q=1.0,
        q_rank_full=[("-O2", 1.0)],
        pareto_frontier=["-O2"],
        pareto_dominated=[],
        pareto_invalid=[],
        objectives_used=["execution_time"],
        moo_active=False,
        ai_choice_was_pareto_optimal=True,
        candidates_considered=["-O2"],
        filtered_out=[],
        final_strategy="-O2",
        selection_reason="test",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[],
        program_profile=prof_unknown.to_dict(),
    )
    xai_res = dt.to_xai_result()
    assert xai_res.program_profile is not None
    assert xai_res.program_profile["label"] == PROFILE_UNKNOWN
    summary_text = format_xai_summary(xai_res)
    assert "Profile Label        : unknown" in summary_text
    report(tid, name, True)


def test_pb7_decision_unchanged_by_profiling():
    tid, name = "PB7", "Optimization decision remains unchanged by Program Profiling"
    from optimization_selector import get_best_optimization
    # Without trace/profiling
    strat_plain = get_best_optimization(TC1_PATH, return_trace=False)
    # With trace and profiling
    strat_traced, trace = get_best_optimization(TC1_PATH, return_trace=True)

    assert strat_plain == strat_traced, f"Strategy mismatch: '{strat_plain}' != '{strat_traced}'"
    assert trace.final_strategy == strat_plain, f"Trace strategy mismatch: '{trace.final_strategy}' != '{strat_plain}'"
    report(tid, name, True)


def test_pb8_backward_compatibility_when_no_profile():
    tid, name = "PB8", "Existing runtime/XAI behavior compatible when no profile is available"
    # Legacy trace dictionary without program_profile
    legacy_dict = {
        "ai_top_choice": "-O3",
        "ai_top_q": 2.5,
        "q_rank_full": [["-O3", 2.5]],
        "pareto_frontier": ["-O3"],
        "pareto_dominated": [],
        "pareto_invalid": [],
        "objectives_used": ["execution_time"],
        "moo_active": True,
        "ai_choice_was_pareto_optimal": True,
        "candidates_considered": ["-O3"],
        "filtered_out": [],
        "final_strategy": "-O3",
        "selection_reason": "Baseline selection",
        "selection_method": SELECTION_METHOD_MOO_AWARE,
        "objective_snapshot": [],
    }
    trace = DecisionTrace.from_dict(legacy_dict)
    assert trace.program_profile is None, "Expected program_profile to be None in legacy trace"

    xai_res = trace.to_xai_result()
    assert xai_res.program_profile is None, "Expected xai_res.program_profile to be None for legacy trace"

    summary = format_xai_summary(xai_res)
    assert "Program Profile (Informational Analysis):" not in summary
    assert "Baseline selection" in summary
    report(tid, name, True)


def test_pb9_xai_failure_isolation():
    tid, name = "PB9", "XAI conversion failure does not change finalized optimization decision"
    from optimization_selector import get_best_optimization
    import unittest.mock as mock

    # Baseline selection
    normal_strat, normal_trace = get_best_optimization(TC1_PATH, return_trace=True)

    # Mock DecisionTrace.to_xai_result to simulate an informational XAI failure
    with mock.patch("moo.decision_trace.DecisionTrace.to_xai_result", side_effect=RuntimeError("Simulated XAI failure")):
        strat, trace, xai_res = get_best_optimization(TC1_PATH, return_trace=True, return_xai=True)
        assert strat == normal_strat, f"Strategy changed on XAI failure: '{strat}' != '{normal_strat}'"
        assert trace is not None, "Trace should still be returned"
        assert trace.final_strategy == normal_strat
        assert xai_res is None, "xai_res must be None when conversion fails"

        # Also test with return_xai=True alone
        strat_only_xai, xai_res2 = get_best_optimization(TC1_PATH, return_xai=True)
        assert strat_only_xai == normal_strat, f"Strategy changed on return_xai alone: '{strat_only_xai}' != '{normal_strat}'"
        assert xai_res2 is None
    report(tid, name, True)


def test_pb10_profiler_failure_isolation():
    tid, name = "PB10", "Profiler failure does not change finalized optimization decision"
    from optimization_selector import get_best_optimization
    import unittest.mock as mock

    normal_strat, normal_trace = get_best_optimization(TC1_PATH, return_trace=True)

    # Mock profile_program to simulate a profiler crash
    with mock.patch("moo.program_profiler.profile_program", side_effect=RuntimeError("Simulated profiler failure")):
        strat, trace, xai_res = get_best_optimization(TC1_PATH, return_trace=True, return_xai=True)
        assert strat == normal_strat, f"Strategy changed on profiler failure: '{strat}' != '{normal_strat}'"
        assert trace is not None
        assert trace.final_strategy == normal_strat
        assert trace.program_profile is None, "program_profile must be None when profiling fails"
        assert xai_res is not None, "xai_res should still be generated when profiler fails"
        assert xai_res.program_profile is None
    report(tid, name, True)


def test_pb11_bridge_ir_features_isolation():
    tid, name = "PB11", "Bridge ir_features argument does not change SelectionResult"
    from moo.selector_bridge import moo_aware_select_with_trace, _load_report_for_trace
    from ml_optimizer import ACTIONS

    report_data = _load_report_for_trace(TC1_PATH)
    frontier = list(report_data.get("pareto_frontier", [])) if report_data else []
    q_vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    sample_features = {
        "BasicBlocksCount": 5.0,
        "InstructionsCount": 50.0,
        "BranchCount": 4.0,
        "MemInstCount": 15.0,
        "MathInstCount": 6.0,
        "FloatInstCount": 0.0,
        "VectorInstCount": 0.0,
        "CallInstCount": 1.0,
    }

    res_no_feats, trace_no_feats = moo_aware_select_with_trace(
        TC1_PATH,
        q_vals,
        ACTIONS,
        frontier,
        report_data=report_data,
        ir_features=None,
    )

    res_with_feats, trace_with_feats = moo_aware_select_with_trace(
        TC1_PATH,
        q_vals,
        ACTIONS,
        frontier,
        report_data=report_data,
        ir_features=sample_features,
    )

    # Selection decisions must be identical
    assert res_no_feats.strategy == res_with_feats.strategy
    assert res_no_feats.reason == res_with_feats.reason
    assert res_no_feats.frontier == res_with_feats.frontier
    assert res_no_feats.filtered_out == res_with_feats.filtered_out
    assert res_no_feats.moo_active == res_with_feats.moo_active

    # Trace core decisions must be identical
    assert trace_no_feats.final_strategy == trace_with_feats.final_strategy
    assert trace_no_feats.ai_top_choice == trace_with_feats.ai_top_choice
    assert trace_no_feats.selection_method == trace_with_feats.selection_method

    # Features correctly recorded in trace
    assert trace_no_feats.ir_features is None
    assert trace_with_feats.ir_features is not None
    assert trace_with_feats.ir_features["InstructionsCount"] == 50.0
    report(tid, name, True)


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------
def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 68)
    print("TOACD MOO Stage 8 - Deterministic Program Profiler Tests")
    print("=" * 68 + "\n")

    # Phase 2A Tests (P1 - P14)
    test_p1_threshold_json_loads()
    test_p2_required_thresholds_exist()
    test_p3_determinism_same_input_same_profile()
    test_p4_trivial_program_handling()
    test_p5_loop_oriented_rule()
    test_p6_compute_oriented_rule()
    test_p7_memory_oriented_rule()
    test_p8_call_oriented_rule()
    test_p9_mixed_profile()
    test_p10_missing_invalid_input_fails_safely()
    test_p11_no_confidence_score_produced()
    test_p12_profile_result_json_serializable()
    test_p13_canonical_8_feature_names_preserved()
    test_p14_no_6_feature_schema_used()

    # Phase 2B Tests (PB1 - PB11)
    test_pb1_runtime_flow_generates_profile()
    test_pb2_profile_attached_to_decision_trace()
    test_pb3_profile_attached_to_xai_result()
    test_pb4_profile_survives_serialization()
    test_pb5_valid_program_produces_expected_profile_structure()
    test_pb6_unknown_profile_safely_represented()
    test_pb7_decision_unchanged_by_profiling()
    test_pb8_backward_compatibility_when_no_profile()
    test_pb9_xai_failure_isolation()
    test_pb10_profiler_failure_isolation()
    test_pb11_bridge_ir_features_isolation()

    print()
    print("=" * 68)
    passed = sum(1 for _, _, s in _results if s == "PASS")
    failed = sum(1 for _, _, s in _results if s == "FAIL")
    skipped = sum(1 for _, _, s in _results if s == "SKIP")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 68 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
