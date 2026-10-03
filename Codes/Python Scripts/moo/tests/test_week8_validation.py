"""
moo/tests/test_week8_validation.py — Week 8: Deterministic AI Assessment & Validation Tests.

This test module covers the Week 8 scope:

  W8-PROF  Program Profiler Phase 2B — Runtime Integration Validation
  W8-DET   Deterministic AI Assessment
  W8-FREQ  Selection Frequency Validation
  W8-BASE  Baseline vs Selected Outcome Validation
  W8-CONS  Selection Consistency
  W8-VAL   Selection Validity
  W8-DT    DecisionTrace Integrity (additional checks)
  W8-XAI   XAI Integrity (additional checks)
  W8-FAIL  Failure Isolation (stale IR, MOO failures, pipeline errors)

Design constraints:
  - Pure deterministic tests that do NOT require clang/toolchain.
  - Any test requiring the live model is clearly labelled (W8-MODEL-*).
  - No new architecture introduced — only validation/testing code.
  - Does NOT test Week 9+ features (benchmarking, dataset generation).
  - Does NOT modify any non-test project files.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import shutil
import unittest.mock as mock

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
    SELECTION_METHOD_ARGMAX_NO_FRONTIER,
    SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH,
    SELECTION_METHOD_ARGMAX_EXCEPTION,
)
from moo.xai import (
    CANONICAL_IR_FEATURE_NAMES,
    XAIResult,
    create_xai_result,
    format_ir_features,
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
    profile_program,
    load_thresholds,
)
from moo.selector_bridge import (
    SelectionResult,
    moo_aware_select,
    moo_aware_select_with_trace,
    _load_report_for_trace,
    get_pareto_frontier_for,
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


def fail(tid: str, name: str, exc: Exception) -> None:
    _results.append((tid, name, "FAIL"))
    print(f"  [FAIL] {tid}: {name}  — {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_ACTIONS = [
    "-O0", "-O1", "-O2", "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
]

_FIXED_THRESHOLDS = {
    "trivial_instructions": 35.0,
    "branch_count": 9.0,
    "compute_count": 5.0,
    "mem_count": 45.25,
    "call_count": 2.0,
}

# Sample Q-values with -O3 highest
_Q_HIGH_O3 = [0.10, 0.60, 0.55, 0.90, 0.30, 0.20, 0.15, 0.12, 0.08]
# Sample Q-values with O1 highest
_Q_HIGH_O1 = [0.10, 0.90, 0.55, 0.60, 0.30, 0.20, 0.15, 0.12, 0.08]

_SAMPLE_FEATURES = {
    "BasicBlocksCount": 12.0,
    "InstructionsCount": 120.0,
    "BranchCount": 20.0,
    "MemInstCount": 25.0,
    "MathInstCount": 5.0,
    "FloatInstCount": 0.0,
    "VectorInstCount": 0.0,
    "CallInstCount": 2.0,
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


def _make_sample_trace(
    final="mem2reg,simplifycfg",
    frontier=None,
    profile_dict=None,
) -> DecisionTrace:
    if frontier is None:
        frontier = ["-O1", "mem2reg,simplifycfg"]
    return DecisionTrace(
        ai_top_choice="-O3",
        ai_top_q=0.90,
        q_rank_full=[("-O3", 0.90), ("-O1", 0.60), (final, 0.55)],
        pareto_frontier=list(frontier),
        pareto_dominated=["-O3"],
        pareto_invalid=["mem2reg,instcombine"],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
        moo_active=True,
        ai_choice_was_pareto_optimal=False,
        candidates_considered=list(frontier),
        filtered_out=["-O3"],
        final_strategy=final,
        selection_reason="MOO-aware: selected highest-Q Pareto strategy",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[],
        program_profile=profile_dict,
    )


# ===========================================================================
# W8-PROF: Program Profiler Phase 2B Runtime Integration Validation
# ===========================================================================

def test_prof1_profile_generated_for_loop_oriented():
    """Profiler generates loop_oriented label for branch-heavy feature sets."""
    tid, name = "W8-PROF1", "Profiler generates loop_oriented for branch-heavy features"
    try:
        feats = _make_features(inst=120.0, br=25.0, mem=20.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        assert prof.label == PROFILE_LOOP_ORIENTED, f"Expected loop_oriented, got {prof.label}"
        assert prof.profile_method == "ir_heuristic_threshold"
        assert not prof.is_trivial
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_prof2_profile_is_informational_only():
    """Profile attachment to trace does not change the selection strategy."""
    tid, name = "W8-PROF2", "Profile attachment to trace does not alter selection result"
    try:
        feats = _make_features(inst=120.0, br=25.0, mem=20.0)
        frontier = ["-O1", "-O2"]

        # Selection without profile
        res_no_prof, trace_no_prof = moo_aware_select_with_trace(
            "dummy.c", _Q_HIGH_O3, _ACTIONS, frontier, ir_features=feats
        )

        # Manually attach a profile to the trace (simulating post-selection profiling)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        if trace_no_prof is not None:
            trace_no_prof.program_profile = prof.to_dict()

        # Selection must be unchanged
        res_check, _ = moo_aware_select_with_trace(
            "dummy.c", _Q_HIGH_O3, _ACTIONS, frontier, ir_features=feats
        )
        assert res_no_prof.strategy == res_check.strategy, (
            "Strategy must not change due to profiling"
        )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_prof3_profile_survives_none_features():
    """Profiler handles None features gracefully, returning PROFILE_UNKNOWN."""
    tid, name = "W8-PROF3", "Profiler returns PROFILE_UNKNOWN for None features"
    try:
        prof = profile_program(None)
        assert prof.label == PROFILE_UNKNOWN
        assert prof.profile_method == "fallback_error"
        d = prof.to_dict()
        assert isinstance(d, dict)
        assert d["label"] == PROFILE_UNKNOWN
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_prof4_profile_attached_to_decision_trace_schema():
    """program_profile in DecisionTrace has all required keys."""
    tid, name = "W8-PROF4", "program_profile in DecisionTrace has required schema keys"
    try:
        feats = _make_features(inst=120.0, br=25.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        prof_dict = prof.to_dict()

        trace = _make_sample_trace(profile_dict=prof_dict)
        assert trace.program_profile is not None
        required_keys = ["label", "dominant_feature", "dominant_feature_value",
                         "profile_method", "is_trivial", "all_features"]
        for k in required_keys:
            assert k in trace.program_profile, f"Missing key: {k}"
        assert trace.program_profile["label"] in VALID_PROFILE_LABELS
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_prof5_profile_roundtrip_through_trace_and_xai():
    """program_profile survives JSON round-trip through DecisionTrace and XAIResult."""
    tid, name = "W8-PROF5", "program_profile survives JSON round-trip (trace → XAI)"
    try:
        feats = _make_features(inst=120.0, br=25.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        prof_dict = prof.to_dict()

        trace = _make_sample_trace(profile_dict=prof_dict)

        # DecisionTrace round-trip
        trace_d = trace.to_dict()
        trace_json = json.dumps(trace_d)
        trace_restored = DecisionTrace.from_dict(json.loads(trace_json))
        assert trace_restored.program_profile == prof_dict, "DecisionTrace round-trip mismatch"

        # XAI round-trip
        xai_res = create_xai_result(trace)
        assert xai_res.program_profile == prof_dict, "XAI profile mismatch"
        xai_d = xai_res.to_dict()
        xai_json = json.dumps(xai_d)
        xai_restored = XAIResult.from_dict(json.loads(xai_json))
        assert xai_restored.program_profile == prof_dict, "XAI JSON round-trip mismatch"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-DET: Deterministic AI Assessment (model-free deterministic tests)
# ===========================================================================

def test_det1_selection_is_deterministic_pure_argmax():
    """moo_aware_select with empty frontier always picks the same argmax."""
    tid, name = "W8-DET1", "Same Q-values + empty frontier always produce same selection (argmax)"
    try:
        results = set()
        for _ in range(20):
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, [])
            results.add(res.strategy)
        assert len(results) == 1, f"Non-deterministic argmax: got {results}"
        assert list(results)[0] == "-O3", f"Argmax should select -O3, got {list(results)[0]}"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_det2_selection_is_deterministic_moo_aware():
    """moo_aware_select with frontier always picks the same frontier strategy."""
    tid, name = "W8-DET2", "Same Q-values + frontier always produce same MOO-aware selection"
    try:
        frontier = ["-O1", "-O2"]
        results = set()
        for _ in range(20):
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            results.add(res.strategy)
        assert len(results) == 1, f"Non-deterministic MOO-aware: got {results}"
        # -O1 has Q=0.60, -O2 has Q=0.55 → -O1 should win
        assert list(results)[0] == "-O1"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_det3_profiler_determinism_50_runs():
    """profile_program with fixed thresholds is deterministic over 50 calls."""
    tid, name = "W8-DET3", "profile_program is deterministic over 50 repeated calls"
    try:
        feats = _make_features(inst=120.0, br=25.0, mem=20.0)
        ref = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        for i in range(50):
            current = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
            assert current.label == ref.label, f"Run {i}: label changed"
            assert current.dominant_feature == ref.dominant_feature, f"Run {i}: dominant_feature changed"
            assert math.isclose(current.dominant_feature_value, ref.dominant_feature_value), \
                f"Run {i}: dominant_feature_value changed"
            assert current.is_trivial == ref.is_trivial, f"Run {i}: is_trivial changed"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_det4_different_q_values_produce_different_selections():
    """Different Q-value distributions select different strategies."""
    tid, name = "W8-DET4", "Different Q-value distributions select different strategies"
    try:
        # _Q_HIGH_O3: O3 wins
        res_o3 = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, [])
        # _Q_HIGH_O1: O1 wins
        res_o1 = moo_aware_select("dummy.c", _Q_HIGH_O1, _ACTIONS, [])
        assert res_o3.strategy == "-O3", f"Expected -O3, got {res_o3.strategy}"
        assert res_o1.strategy == "-O1", f"Expected -O1, got {res_o1.strategy}"
        assert res_o3.strategy != res_o1.strategy, "Different Q-values must select different strategies"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_det5_decision_trace_determinism():
    """moo_aware_select_with_trace produces identical trace fields on repeated calls."""
    tid, name = "W8-DET5", "moo_aware_select_with_trace produces identical trace on repeated calls"
    try:
        frontier = ["-O1", "-O2"]
        traces = []
        for _ in range(5):
            _, trace = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            assert trace is not None
            traces.append(trace)

        ref = traces[0]
        for i, t in enumerate(traces[1:], 1):
            assert t.final_strategy == ref.final_strategy, f"Trace {i}: final_strategy differs"
            assert t.ai_top_choice == ref.ai_top_choice, f"Trace {i}: ai_top_choice differs"
            assert t.selection_method == ref.selection_method, f"Trace {i}: selection_method differs"
            assert t.moo_active == ref.moo_active, f"Trace {i}: moo_active differs"
            assert t.candidates_considered == ref.candidates_considered, f"Trace {i}: candidates_considered differs"
            assert t.filtered_out == ref.filtered_out, f"Trace {i}: filtered_out differs"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-FREQ: Selection Frequency Validation
# ===========================================================================

def test_freq1_frontier_strategy_always_selected_when_available():
    """When a single strategy is on the frontier, it is always selected."""
    tid, name = "W8-FREQ1", "Single-element frontier always wins when Q-value available"
    try:
        # Only -O2 is on frontier; should always be selected regardless of Q ranking
        frontier = ["-O2"]
        strategies_selected = set()
        for _ in range(10):
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            strategies_selected.add(res.strategy)
        assert strategies_selected == {"-O2"}, f"Expected only -O2 selected, got {strategies_selected}"
        assert res.moo_active is True
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_freq2_argmax_fallback_frequency():
    """With empty frontier, argmax is used 100% of the time."""
    tid, name = "W8-FREQ2", "Empty frontier produces argmax 100% of runs"
    try:
        strategies = []
        for _ in range(10):
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, [])
            strategies.append(res.strategy)
            assert res.moo_active is False, "moo_active must be False with empty frontier"
        assert all(s == strategies[0] for s in strategies), "All argmax runs must pick the same strategy"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_freq3_selection_method_consistency():
    """Selection method label is consistent with moo_active flag."""
    tid, name = "W8-FREQ3", "selection_method is consistent with moo_active"
    try:
        # MOO active
        _, trace_moo = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, ["-O1", "-O2"])
        assert trace_moo is not None
        assert trace_moo.moo_active is True
        assert trace_moo.selection_method == SELECTION_METHOD_MOO_AWARE

        # MOO inactive (empty frontier)
        _, trace_no_moo = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, [])
        assert trace_no_moo is not None
        assert trace_no_moo.moo_active is False
        assert trace_no_moo.selection_method == SELECTION_METHOD_ARGMAX_NO_FRONTIER

        # Frontier exists but no match in ACTIONS
        _, trace_mismatch = moo_aware_select_with_trace(
            "dummy.c", _Q_HIGH_O3, _ACTIONS, ["unknown_pass_xyz"]
        )
        assert trace_mismatch is not None
        assert trace_mismatch.moo_active is False
        assert trace_mismatch.selection_method == SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-BASE: Baseline vs Selected Outcome Validation
# ===========================================================================

def test_base1_baseline_convention_is_minus_O0():
    """The project's baseline convention is documented as -O0 (unoptimized)."""
    tid, name = "W8-BASE1", "Baseline convention is -O0 (unoptimized)"
    try:
        # Verify baseline strategy name in moo_result
        from moo.moo_result import BaselineMeasurement
        bm = BaselineMeasurement(
            strategy_name="baseline (-O0)",
            exe_path=None,
            build_ok=False,
            build_error="toolchain unavailable",
            reference_exit_code=None,
            reference_stdout="",
            measurement=None,
        )
        assert bm.strategy_name == "baseline (-O0)", (
            "Baseline strategy name must be 'baseline (-O0)'"
        )
        d = bm.to_dict()
        assert d["strategy_name"] == "baseline (-O0)"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_base2_selected_strategy_is_always_in_actions():
    """The selected strategy is always a member of the ACTIONS list."""
    tid, name = "W8-BASE2", "Selected strategy is always a member of ACTIONS"
    try:
        for frontier in [[], ["-O1", "-O2"], ["-O3"], ["unknown_pass"]]:
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            assert res.strategy in _ACTIONS, (
                f"Selected strategy {res.strategy!r} not in ACTIONS for frontier={frontier}"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_base3_selection_not_a_baseline_strategy():
    """The selected strategy is never re-labeled 'baseline (-O0)' or 'baseline'."""
    tid, name = "W8-BASE3", "Selected strategy is not labeled 'baseline'"
    try:
        for frontier in [[], ["-O1", "-O2"]]:
            res = moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            assert "baseline" not in res.strategy.lower(), (
                f"Selected strategy {res.strategy!r} must not contain 'baseline'"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_base4_normalized_ratios_are_relative_to_baseline():
    """
    Validate that normalized objective ratios below 1.0 indicate improvement
    over the -O0 baseline (e.g. faster execution → ratio < 1.0).
    This is a structural/semantic check, not a live measurement.
    """
    tid, name = "W8-BASE4", "Normalized ratios < 1.0 denote improvement over -O0 baseline"
    try:
        from moo.objectives import RawObjectives, normalize, ALL_OBJECTIVES
        base_raw = RawObjectives(
            strategy="baseline (-O0)",
            execution_time_s=1.0,
            energy_j=45.0,
            code_size_bytes=10000,
            carbon_g=0.0055,
        )
        cand_raw = RawObjectives(
            strategy="-O2",
            execution_time_s=0.7,      # 30% faster → ratio = 0.7
            energy_j=31.5,             # proportionally better
            code_size_bytes=8800,
            carbon_g=0.0038,
        )
        vec = normalize(cand_raw, base_raw, objectives=ALL_OBJECTIVES)
        for i, obj_spec in enumerate(vec.objectives):
            val = vec.normalized_values[i]
            if isinstance(val, (int, float)) and math.isfinite(val):
                assert val < 1.0, (
                    f"Objective {obj_spec.name}: ratio {val:.4f} should be < 1.0 for improved candidate"
                )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-CONS: Selection Consistency
# ===========================================================================

def test_cons1_same_input_same_selection_20_runs():
    """Same Q-values + same frontier → same selection across 20 runs."""
    tid, name = "W8-CONS1", "Same inputs produce same selection across 20 runs"
    try:
        frontier = ["-O1", "-O2", "mem2reg,simplifycfg"]
        strategies = [
            moo_aware_select("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier).strategy
            for _ in range(20)
        ]
        assert len(set(strategies)) == 1, f"Inconsistent selections: {set(strategies)}"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_cons2_same_features_same_profile_100_runs():
    """Same IR features → same profile label across 100 runs."""
    tid, name = "W8-CONS2", "Same IR features produce same profile across 100 runs"
    try:
        feats = _make_features(inst=100.0, br=15.0, mem=20.0)
        ref = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        for i in range(100):
            cur = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
            assert cur.label == ref.label, f"Run {i}: label {cur.label!r} != {ref.label!r}"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_cons3_trace_final_strategy_matches_selection_result():
    """trace.final_strategy always equals SelectionResult.strategy."""
    tid, name = "W8-CONS3", "trace.final_strategy always equals SelectionResult.strategy"
    try:
        test_cases = [
            ([], _Q_HIGH_O3),
            (["-O1", "-O2"], _Q_HIGH_O3),
            (["-O3"], _Q_HIGH_O3),
            ([], _Q_HIGH_O1),
        ]
        for frontier, q_vals in test_cases:
            res, trace = moo_aware_select_with_trace("dummy.c", q_vals, _ACTIONS, frontier)
            assert trace is not None, f"Trace is None for frontier={frontier}"
            assert trace.final_strategy == res.strategy, (
                f"Mismatch: trace.final_strategy={trace.final_strategy!r}, "
                f"res.strategy={res.strategy!r}"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-VAL: Selection Validity
# ===========================================================================

def test_val1_selected_strategy_is_in_actions():
    """Selected strategy always belongs to the actions list under all conditions."""
    tid, name = "W8-VAL1", "Selected strategy always in ACTIONS list"
    try:
        scenarios = [
            ([], _Q_HIGH_O3),
            (["-O1"], _Q_HIGH_O3),
            (["-O2", "mem2reg,instcombine"], _Q_HIGH_O3),
            (["unknown_xyz"], _Q_HIGH_O3),
        ]
        for frontier, q_vals in scenarios:
            res = moo_aware_select("dummy.c", q_vals, _ACTIONS, frontier)
            assert res.strategy in _ACTIONS, (
                f"Strategy {res.strategy!r} not in ACTIONS (frontier={frontier})"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_val2_frontier_strategy_in_candidates_considered():
    """candidates_considered only contains frontier members that are in ACTIONS."""
    tid, name = "W8-VAL2", "candidates_considered ⊆ frontier ∩ ACTIONS"
    try:
        frontier = ["-O1", "-O2", "not_a_real_pass"]
        _, trace = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
        assert trace is not None
        frontier_set = set(frontier)
        actions_set = set(_ACTIONS)
        for cand in trace.candidates_considered:
            assert cand in frontier_set, f"{cand!r} not in frontier"
            assert cand in actions_set, f"{cand!r} not in ACTIONS"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_val3_filtered_out_are_not_frontier_members():
    """filtered_out strategies are NOT on the Pareto frontier."""
    tid, name = "W8-VAL3", "filtered_out strategies are not on the Pareto frontier"
    try:
        # -O3 is not on frontier → should appear in filtered_out
        frontier = ["-O1", "-O2"]
        _, trace = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
        assert trace is not None
        frontier_set = set(trace.pareto_frontier)
        for strat in trace.filtered_out:
            assert strat not in frontier_set, (
                f"{strat!r} is in both filtered_out and pareto_frontier"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_val4_final_strategy_in_candidates_or_argmax():
    """final_strategy is either in candidates_considered or is the argmax fallback."""
    tid, name = "W8-VAL4", "final_strategy is either in candidates_considered or argmax fallback"
    try:
        for frontier in [[], ["-O1", "-O2"], ["-O3"]]:
            res, trace = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            assert trace is not None
            if trace.moo_active:
                assert trace.final_strategy in trace.candidates_considered, (
                    f"MOO-active: final_strategy {trace.final_strategy!r} not in candidates_considered"
                )
            else:
                # Argmax fallback — must be the highest-Q action
                assert trace.final_strategy == trace.q_rank_full[0][0], (
                    f"Argmax fallback: final_strategy {trace.final_strategy!r} != q_rank_full[0]"
                )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_val5_selection_method_valid_constants():
    """selection_method value is always one of the known SELECTION_METHOD_* constants."""
    tid, name = "W8-VAL5", "selection_method is always a known constant"
    try:
        valid_methods = {
            SELECTION_METHOD_MOO_AWARE,
            SELECTION_METHOD_ARGMAX_NO_FRONTIER,
            SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH,
            SELECTION_METHOD_ARGMAX_EXCEPTION,
        }
        test_frontiers = [[], ["-O1"], ["unknown_pass_xyz"]]
        for frontier in test_frontiers:
            _, trace = moo_aware_select_with_trace("dummy.c", _Q_HIGH_O3, _ACTIONS, frontier)
            assert trace is not None
            assert trace.selection_method in valid_methods, (
                f"Unknown selection_method {trace.selection_method!r}"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-DT: DecisionTrace Integrity
# ===========================================================================

def test_dt1_trace_json_safe_with_profile():
    """DecisionTrace with program_profile is JSON-safe."""
    tid, name = "W8-DT1", "DecisionTrace with program_profile is json.dumps() safe"
    try:
        feats = _make_features(inst=120.0, br=25.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        trace = _make_sample_trace(profile_dict=prof.to_dict())
        d = trace.to_dict()
        s = json.dumps(d)
        assert isinstance(s, str) and len(s) > 0
        loaded = json.loads(s)
        assert loaded["program_profile"] is not None
        assert loaded["program_profile"]["label"] in VALID_PROFILE_LABELS
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_dt2_trace_roundtrip_preserves_profile():
    """DecisionTrace.from_dict(to_dict(trace)) preserves program_profile exactly."""
    tid, name = "W8-DT2", "DecisionTrace round-trip preserves program_profile"
    try:
        feats = _make_features(inst=120.0, br=25.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        prof_dict = prof.to_dict()
        trace = _make_sample_trace(profile_dict=prof_dict)

        d = trace.to_dict()
        restored = DecisionTrace.from_dict(d)
        assert restored.program_profile == prof_dict, "program_profile not preserved"
        assert restored.program_profile["label"] == prof_dict["label"]
        assert restored.program_profile["dominant_feature"] == prof_dict["dominant_feature"]
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_dt3_trace_without_profile_is_valid():
    """DecisionTrace without program_profile is still a valid, JSON-safe object."""
    tid, name = "W8-DT3", "DecisionTrace without program_profile is still valid"
    try:
        trace = _make_sample_trace(profile_dict=None)
        assert trace.program_profile is None
        d = trace.to_dict()
        assert "program_profile" not in d or d.get("program_profile") is None
        s = json.dumps(d)
        assert isinstance(s, str)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_dt4_legacy_dict_without_profile_key():
    """DecisionTrace.from_dict() handles legacy dicts without 'program_profile' key."""
    tid, name = "W8-DT4", "from_dict() handles missing program_profile key gracefully"
    try:
        legacy = {
            "ai_top_choice": "-O3",
            "ai_top_q": 0.9,
            "q_rank_full": [["-O3", 0.9]],
            "pareto_frontier": ["-O3"],
            "pareto_dominated": [],
            "pareto_invalid": [],
            "objectives_used": ["execution_time"],
            "moo_active": True,
            "ai_choice_was_pareto_optimal": True,
            "candidates_considered": ["-O3"],
            "filtered_out": [],
            "final_strategy": "-O3",
            "selection_reason": "Selected -O3",
            "selection_method": SELECTION_METHOD_MOO_AWARE,
            "objective_snapshot": [],
            # 'program_profile' intentionally absent
        }
        trace = DecisionTrace.from_dict(legacy)
        assert trace.program_profile is None, "Expected program_profile to be None"
        assert trace.final_strategy == "-O3"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_dt5_trace_from_dict_empty_is_safe():
    """DecisionTrace.from_dict({}) produces a valid safe-default trace."""
    tid, name = "W8-DT5", "DecisionTrace.from_dict({}) produces valid safe defaults"
    try:
        trace = DecisionTrace.from_dict({})
        assert trace.final_strategy == ""
        assert trace.ai_top_choice == ""
        assert trace.moo_active is False
        assert trace.program_profile is None
        assert trace.objective_snapshot == []
        assert trace.selection_method == SELECTION_METHOD_ARGMAX_NO_FRONTIER
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_dt6_all_required_fields_present_in_to_dict():
    """DecisionTrace.to_dict() contains all required fields."""
    tid, name = "W8-DT6", "DecisionTrace.to_dict() contains all required fields"
    try:
        trace = _make_sample_trace()
        d = trace.to_dict()
        required_fields = [
            "ai_top_choice", "ai_top_q", "q_rank_full",
            "pareto_frontier", "pareto_dominated", "pareto_invalid",
            "objectives_used", "moo_active",
            "ai_choice_was_pareto_optimal",
            "candidates_considered", "filtered_out",
            "final_strategy", "selection_reason", "selection_method",
            "objective_snapshot",
        ]
        for field in required_fields:
            assert field in d, f"Missing required field: {field}"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-XAI: XAI Integrity
# ===========================================================================

def test_xai1_xai_reflects_decision_trace_not_inverted():
    """XAI result final_strategy matches DecisionTrace.final_strategy."""
    tid, name = "W8-XAI1", "XAIResult.final_strategy matches DecisionTrace.final_strategy"
    try:
        trace = _make_sample_trace()
        xai = create_xai_result(trace)
        assert xai.final_strategy == trace.final_strategy, (
            f"XAI final_strategy {xai.final_strategy!r} != trace final_strategy {trace.final_strategy!r}"
        )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai2_xai_does_not_invent_confidence_scores():
    """XAI result has no confidence_score, probability, or trust fields."""
    tid, name = "W8-XAI2", "XAIResult has no confidence_score, probability, or trust fields"
    try:
        trace = _make_sample_trace()
        xai = create_xai_result(trace)
        prohibited = ["confidence_score", "confidence", "probability", "trust", "certainty"]
        d = xai.to_dict()
        for field in prohibited:
            assert not hasattr(xai, field), f"Prohibited attribute: {field}"
            assert field not in d, f"Prohibited key in dict: {field}"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai3_xai_pareto_info_matches_trace():
    """XAI pareto information is directly sourced from the DecisionTrace."""
    tid, name = "W8-XAI3", "XAI pareto info matches DecisionTrace pareto info"
    try:
        trace = _make_sample_trace()
        xai = create_xai_result(trace)
        assert xai.pareto_frontier == trace.pareto_frontier
        assert xai.pareto_dominated == trace.pareto_dominated
        assert xai.pareto_invalid == trace.pareto_invalid
        assert xai.moo_active == trace.moo_active
        assert xai.ai_choice_was_pareto_optimal == trace.ai_choice_was_pareto_optimal
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai4_xai_from_none_trace_raises():
    """create_xai_result(None) raises ValueError, not a silent failure."""
    tid, name = "W8-XAI4", "create_xai_result(None) raises ValueError"
    try:
        raised = False
        try:
            create_xai_result(None)
        except ValueError:
            raised = True
        assert raised, "Expected ValueError for None trace input"
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai5_xai_summary_no_prohibited_terms():
    """XAI text summary avoids unsupported causal/confidence terminology."""
    tid, name = "W8-XAI5", "XAI summary avoids confidence/causality/trust terms"
    try:
        trace = _make_sample_trace()
        xai = create_xai_result(trace)
        summary = format_xai_summary(xai).lower()
        prohibited_terms = [
            "confidence score",
            "feature importance",
            "causal influence",
            "trust score",
            "model accuracy",
            "reliability score",
        ]
        for term in prohibited_terms:
            assert term not in summary, f"Prohibited term found in XAI summary: {term!r}"
        # Allowed terms
        assert "q-value" in summary
        assert "pareto" in summary
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai6_xai_profile_matches_trace_profile():
    """XAI program_profile matches the trace's program_profile."""
    tid, name = "W8-XAI6", "XAI program_profile matches trace program_profile"
    try:
        feats = _make_features(inst=120.0, br=25.0)
        prof = profile_program(feats, thresholds=_FIXED_THRESHOLDS)
        trace = _make_sample_trace(profile_dict=prof.to_dict())
        xai = create_xai_result(trace)
        assert xai.program_profile == trace.program_profile, (
            "XAI program_profile does not match trace program_profile"
        )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_xai7_xai_with_no_profile_is_valid():
    """XAIResult is valid and JSON-safe even when program_profile is None."""
    tid, name = "W8-XAI7", "XAIResult with no program_profile is still valid and JSON-safe"
    try:
        trace = _make_sample_trace(profile_dict=None)
        xai = create_xai_result(trace)
        assert xai.program_profile is None
        d = xai.to_dict()
        assert d["program_profile"] is None
        s = json.dumps(d)
        assert isinstance(s, str)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-FAIL: Failure Isolation
# ===========================================================================

def test_fail1_stale_ir_risk_in_compiler_env():
    """
    Validates failure isolation and stale temp_unopt.ll prevention in CompilerEnv:
      1. Confirms extract_features falls back to zeros when IR file is absent.
      2. Confirms pre-existing temp_unopt.ll is removed before compilation.
      3. Confirms clang returncode is checked; compilation failure returns False.
      4. Confirms stale IR cannot be reused: when compilation fails, features are all zeros.
    """
    tid, name = "W8-FAIL1", "Stale temp_unopt.ll prevention and compilation failure isolation"
    try:
        import importlib.util
        ml_path = os.path.join(_PS_DIR, "ml_optimizer.py")
        if not os.path.isfile(ml_path):
            skip(tid, name, "ml_optimizer.py not found")
            return

        spec = importlib.util.spec_from_file_location("_ml_opt_ref", ml_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        CompilerEnv = mod.CompilerEnv

        # 1. Test the extract_features fallback when IR file is absent
        with tempfile.TemporaryDirectory() as tmpdir:
            absent_path = os.path.join(tmpdir, "nonexistent_test.ll")
            env_instance = object.__new__(CompilerEnv)
            feats = env_instance.extract_features(absent_path)
            import numpy as np
            assert isinstance(feats, np.ndarray), "extract_features must return ndarray"
            assert feats.shape == (8,), f"Expected shape (8,), got {feats.shape}"
            assert (feats == 0).all(), (
                "extract_features must return zeros when IR file is absent "
                "(prevents silent stale data use)"
            )

        # 2. Test that existing temp_unopt.ll cannot be reused when compilation fails
        with tempfile.TemporaryDirectory() as tmpdir:
            test_ir = os.path.join(tmpdir, "test_stale.ll")
            # Create a fake "stale" IR with non-zero instruction count
            with open(test_ir, "w", encoding="utf-8") as f:
                f.write("define i32 @main() {\n  %1 = add i32 1, 2\n  ret i32 %1\n}\n")
            assert os.path.exists(test_ir)

            env = object.__new__(CompilerEnv)
            env.benchmark_path = "nonexistent_source.c"
            env.ir_path = test_ir

            # Simulate clang compilation failure (returncode = 1)
            fake_proc = mock.MagicMock(returncode=1, stderr="error: file not found")
            with mock.patch("subprocess.run", return_value=fake_proc):
                ok = env.generate_unoptimized_ir()
                assert ok is False, "generate_unoptimized_ir must return False on non-zero returncode"
                assert not os.path.exists(test_ir), "Stale IR file must be deleted upon failure"

        # 3. Test CompilerEnv __init__ with failed compilation produces all-zero features
        fake_proc = mock.MagicMock(returncode=1, stderr="compiler error")
        with mock.patch("subprocess.run", return_value=fake_proc):
            env_fail = CompilerEnv("failing_program.c")
            assert isinstance(env_fail.features, np.ndarray)
            assert (env_fail.features == 0).all(), (
                "CompilerEnv must produce zero features on compilation failure"
            )

        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail2_profiler_failure_does_not_affect_selection():
    """A crash in profile_program does not alter the selected strategy."""
    tid, name = "W8-FAIL2", "Profiler crash does not alter selection"
    try:
        frontier = ["-O1", "-O2"]
        # Normal selection
        res_normal, trace_normal = moo_aware_select_with_trace(
            "dummy.c", _Q_HIGH_O3, _ACTIONS, frontier
        )
        normal_strategy = res_normal.strategy

        # Simulate profiler failure after selection
        with mock.patch("moo.program_profiler.profile_program",
                        side_effect=RuntimeError("Simulated profiler crash")):
            res_fail, trace_fail = moo_aware_select_with_trace(
                "dummy.c", _Q_HIGH_O3, _ACTIONS, frontier
            )
            # Selection must be identical
            assert res_fail.strategy == normal_strategy, (
                f"Strategy changed on profiler failure: {res_fail.strategy!r} != {normal_strategy!r}"
            )
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail3_selector_bridge_always_returns_on_exception():
    """moo_aware_select never propagates an internal exception to the caller."""
    tid, name = "W8-FAIL3", "moo_aware_select never raises — always returns SelectionResult"
    try:
        # Mismatched lengths
        res = moo_aware_select("dummy.c", [0.5], _ACTIONS, ["-O1"])
        assert isinstance(res, SelectionResult), "Must return SelectionResult even on length mismatch"
        assert isinstance(res.strategy, str)

        # Empty actions
        res2 = moo_aware_select("dummy.c", [], [], [])
        assert isinstance(res2, SelectionResult)
        assert isinstance(res2.strategy, str)

        # None in Q-values
        res3 = moo_aware_select("dummy.c", [None, None], ["-O1", "-O2"], [])
        assert isinstance(res3, SelectionResult)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail4_decision_trace_never_contains_none_for_required_fields():
    """DecisionTrace.from_dict({}) sets required fields to safe non-None defaults."""
    tid, name = "W8-FAIL4", "DecisionTrace.from_dict({}) has safe defaults for all required fields"
    try:
        trace = DecisionTrace.from_dict({})
        assert trace.final_strategy is not None
        assert trace.ai_top_choice is not None
        assert isinstance(trace.q_rank_full, list)
        assert isinstance(trace.pareto_frontier, list)
        assert isinstance(trace.pareto_dominated, list)
        assert isinstance(trace.pareto_invalid, list)
        assert isinstance(trace.objectives_used, list)
        assert isinstance(trace.candidates_considered, list)
        assert isinstance(trace.filtered_out, list)
        assert isinstance(trace.objective_snapshot, list)
        assert isinstance(trace.selection_method, str)
        assert len(trace.selection_method) > 0
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail5_moo_report_with_pipeline_error_returns_empty_frontier():
    """A cached MOO report with pipeline_error returns [] for the frontier."""
    tid, name = "W8-FAIL5", "Cached report with pipeline_error yields empty frontier"
    try:
        tmpdir = tempfile.mkdtemp()
        try:
            broken_report = {
                "source_file": "fail5_test.c",
                "source_path": "/mock/fail5_test.c",
                "timestamp": "2026-10-01T00:00:00",
                "toolchain_ok": True,
                "toolchain_notes": [],
                "baseline": None,
                "candidates": [],
                "pareto_frontier": ["-O1", "-O2"],  # Non-empty, but pipeline_error is set
                "pareto_dominated": [],
                "pareto_invalid": [],
                "objectives_used": [],
                "pipeline_error": "Reference build failed: clang not found",
                "summary": {"n_strategies": 0, "n_valid": 0, "n_invalid": 0,
                            "n_frontier": 0, "n_dominated": 0},
            }
            report_path = os.path.join(tmpdir, "moo_fail5_test_c_2026-10-01_00-00-00.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(broken_report, f)

            frontier = get_pareto_frontier_for("fail5_test.c", report_dir=tmpdir)
            assert frontier == [], (
                f"Expected empty frontier for pipeline_error report, got {frontier}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail6_profile_unknown_is_valid_in_trace():
    """PROFILE_UNKNOWN profile can be attached to a trace without any errors."""
    tid, name = "W8-FAIL6", "PROFILE_UNKNOWN profile attaches to trace without error"
    try:
        unknown_prof = profile_program(None)
        assert unknown_prof.label == PROFILE_UNKNOWN

        trace = _make_sample_trace(profile_dict=unknown_prof.to_dict())
        assert trace.program_profile is not None
        assert trace.program_profile["label"] == PROFILE_UNKNOWN

        xai = create_xai_result(trace)
        assert xai.program_profile is not None
        assert xai.program_profile["label"] == PROFILE_UNKNOWN

        # JSON must still be safe
        s = json.dumps(trace.to_dict())
        assert isinstance(s, str)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail7_missing_moo_report_yields_empty_frontier():
    """When no MOO report exists, get_pareto_frontier_for returns []."""
    tid, name = "W8-FAIL7", "No cached MOO report yields empty frontier"
    try:
        tmpdir = tempfile.mkdtemp()
        try:
            # Empty directory — no reports
            frontier = get_pareto_frontier_for("no_such_file.c", report_dir=tmpdir)
            assert frontier == [], f"Expected empty frontier, got {frontier}"
            assert isinstance(frontier, list)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_fail8_selection_continues_without_trace_when_bridge_fails():
    """
    If moo_aware_select_with_trace returns (result, None), the selection
    result is still valid and contains a valid strategy.
    """
    tid, name = "W8-FAIL8", "Selection is valid even when trace construction fails (returns None)"
    try:
        from moo.selector_bridge import _build_decision_trace
        with mock.patch(
            "moo.selector_bridge._build_decision_trace",
            return_value=None,
        ):
            res, trace = moo_aware_select_with_trace(
                "dummy.c", _Q_HIGH_O3, _ACTIONS, ["-O1", "-O2"]
            )
            assert isinstance(res, SelectionResult)
            assert res.strategy in _ACTIONS
            # trace may be None (the mock forces this), which is acceptable
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# W8-SCOPE: Architecture / Scope Guard
# ===========================================================================

def test_scope1_no_automated_benchmark_generation_imported():
    """
    Verify that no Week 9 automated benchmark/dataset generation modules
    have been accidentally pulled into the current codebase.
    """
    tid, name = "W8-SCOPE1", "No Week 9 benchmark/dataset generation modules in moo/"
    try:
        prohibited_modules = [
            "moo.benchmark_generator",
            "moo.dataset_generator",
            "moo.auto_benchmark",
        ]
        for mod_name in prohibited_modules:
            try:
                import importlib
                m = importlib.import_module(mod_name)
                assert False, f"Week 9 module {mod_name!r} should not exist yet"
            except ImportError:
                pass  # correct — module should not exist
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


def test_scope2_no_regression_platform_modules():
    """
    Verify that no Week 10+ optimization regression platform modules
    have been accidentally introduced.
    """
    tid, name = "W8-SCOPE2", "No Week 10+ regression platform modules in moo/"
    try:
        prohibited_modules = [
            "moo.regression_tracker",
            "moo.regression_platform",
            "moo.historical_comparison",
        ]
        for mod_name in prohibited_modules:
            try:
                import importlib
                m = importlib.import_module(mod_name)
                assert False, f"Week 10+ module {mod_name!r} should not exist yet"
            except ImportError:
                pass  # correct
        report(tid, name, True)
    except Exception as e:
        fail(tid, name, e)


# ===========================================================================
# Main Runner
# ===========================================================================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("TOACD — Week 8 Deterministic AI Assessment & Validation Tests")
    print("=" * 70)

    print("\n--- W8-PROF: Program Profiler Phase 2B Runtime Integration ---")
    test_prof1_profile_generated_for_loop_oriented()
    test_prof2_profile_is_informational_only()
    test_prof3_profile_survives_none_features()
    test_prof4_profile_attached_to_decision_trace_schema()
    test_prof5_profile_roundtrip_through_trace_and_xai()

    print("\n--- W8-DET: Deterministic AI Assessment ---")
    test_det1_selection_is_deterministic_pure_argmax()
    test_det2_selection_is_deterministic_moo_aware()
    test_det3_profiler_determinism_50_runs()
    test_det4_different_q_values_produce_different_selections()
    test_det5_decision_trace_determinism()

    print("\n--- W8-FREQ: Selection Frequency Validation ---")
    test_freq1_frontier_strategy_always_selected_when_available()
    test_freq2_argmax_fallback_frequency()
    test_freq3_selection_method_consistency()

    print("\n--- W8-BASE: Baseline vs Selected Outcome Validation ---")
    test_base1_baseline_convention_is_minus_O0()
    test_base2_selected_strategy_is_always_in_actions()
    test_base3_selection_not_a_baseline_strategy()
    test_base4_normalized_ratios_are_relative_to_baseline()

    print("\n--- W8-CONS: Selection Consistency ---")
    test_cons1_same_input_same_selection_20_runs()
    test_cons2_same_features_same_profile_100_runs()
    test_cons3_trace_final_strategy_matches_selection_result()

    print("\n--- W8-VAL: Selection Validity ---")
    test_val1_selected_strategy_is_in_actions()
    test_val2_frontier_strategy_in_candidates_considered()
    test_val3_filtered_out_are_not_frontier_members()
    test_val4_final_strategy_in_candidates_or_argmax()
    test_val5_selection_method_valid_constants()

    print("\n--- W8-DT: DecisionTrace Integrity ---")
    test_dt1_trace_json_safe_with_profile()
    test_dt2_trace_roundtrip_preserves_profile()
    test_dt3_trace_without_profile_is_valid()
    test_dt4_legacy_dict_without_profile_key()
    test_dt5_trace_from_dict_empty_is_safe()
    test_dt6_all_required_fields_present_in_to_dict()

    print("\n--- W8-XAI: XAI Integrity ---")
    test_xai1_xai_reflects_decision_trace_not_inverted()
    test_xai2_xai_does_not_invent_confidence_scores()
    test_xai3_xai_pareto_info_matches_trace()
    test_xai4_xai_from_none_trace_raises()
    test_xai5_xai_summary_no_prohibited_terms()
    test_xai6_xai_profile_matches_trace_profile()
    test_xai7_xai_with_no_profile_is_valid()

    print("\n--- W8-FAIL: Failure Isolation ---")
    test_fail1_stale_ir_risk_in_compiler_env()
    test_fail2_profiler_failure_does_not_affect_selection()
    test_fail3_selector_bridge_always_returns_on_exception()
    test_fail4_decision_trace_never_contains_none_for_required_fields()
    test_fail5_moo_report_with_pipeline_error_returns_empty_frontier()
    test_fail6_profile_unknown_is_valid_in_trace()
    test_fail7_missing_moo_report_yields_empty_frontier()
    test_fail8_selection_continues_without_trace_when_bridge_fails()

    print("\n--- W8-SCOPE: Architecture / Scope Guard ---")
    test_scope1_no_automated_benchmark_generation_imported()
    test_scope2_no_regression_platform_modules()

    print()
    print("=" * 70)
    passed = sum(1 for _, _, s in _results if s == "PASS")
    failed = sum(1 for _, _, s in _results if s == "FAIL")
    skipped = sum(1 for _, _, s in _results if s == "SKIP")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 70 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
