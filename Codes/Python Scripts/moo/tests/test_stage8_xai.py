"""
moo/tests/test_stage8_xai.py — Stage 8 Explainable AI (XAI) unit and integration tests.

Tests the XAI foundation (Week 7 Phase 1):
  XAIResult dataclass, DecisionTrace transformation, canonical 8 IR features,
  Pareto filtering transparency, JSON safety, backward compatibility,
  and academic terminology compliance.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
from typing import Optional

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
)
from moo.xai import (
    CANONICAL_IR_FEATURE_NAMES,
    XAIResult,
    create_xai_result,
    format_ir_features,
    format_xai_summary,
    print_xai_summary,
)
from moo.selector_bridge import moo_aware_select_with_trace


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

_SAMPLE_Q_VALUES = [0.10, 0.60, 0.55, 0.90, 0.30, 0.20, 0.15, 0.12, 0.08]

_SAMPLE_FEATURES = {
    "BasicBlocksCount": 12.0,
    "InstructionsCount": 150.0,
    "BranchCount": 18.0,
    "MemInstCount": 42.0,
    "MathInstCount": 30.0,
    "FloatInstCount": 0.0,
    "VectorInstCount": 0.0,
    "CallInstCount": 6.0,
}


def _build_test_decision_trace(include_features: bool = True) -> DecisionTrace:
    return DecisionTrace(
        ai_top_choice="-O3",
        ai_top_q=0.90,
        q_rank_full=[
            ("-O3", 0.90),
            ("-O1", 0.60),
            ("-O2", 0.55),
            ("mem2reg,instcombine", 0.30),
            ("mem2reg,simplifycfg", 0.20),
            ("mem2reg,instcombine,simplifycfg,dce", 0.15),
            ("mem2reg,instcombine,simplifycfg,gvn,loop-unroll", 0.12),
            ("-O0", 0.10),
            ("mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll", 0.08),
        ],
        pareto_frontier=["-O1", "-O2"],
        pareto_dominated=["-O0", "-O3"],
        pareto_invalid=["mem2reg,instcombine"],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
        moo_active=True,
        ai_choice_was_pareto_optimal=False,
        candidates_considered=["-O1", "-O2"],
        filtered_out=["-O3"],
        final_strategy="-O1",
        selection_reason="MOO-aware: selected highest-Q Pareto strategy '-O1' (AI top '-O3' was not Pareto-efficient)",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[
            ObjectiveSnapshot("-O1", "FRONTIER", 0.72, 0.68, 0.91, 0.68, 0.60),
            ObjectiveSnapshot("-O3", "DOMINATED", 0.70, 0.67, 0.97, 0.67, 0.90),
        ],
        ir_features=_SAMPLE_FEATURES if include_features else None,
    )


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_xai1_create_from_valid_trace():
    tid, name = "XAI1", "XAIResult can be created from a valid DecisionTrace"
    trace = _build_test_decision_trace(include_features=True)

    # 1. create_xai_result() helper
    res1 = create_xai_result(trace)
    assert isinstance(res1, XAIResult), "Must return XAIResult instance"

    # 2. XAIResult.from_decision_trace() method
    res2 = XAIResult.from_decision_trace(trace)
    assert isinstance(res2, XAIResult)

    # 3. trace.to_xai_result() method on DecisionTrace
    res3 = trace.to_xai_result()
    assert isinstance(res3, XAIResult)

    assert res1.final_strategy == trace.final_strategy
    assert res2.final_strategy == trace.final_strategy
    assert res3.final_strategy == trace.final_strategy
    report(tid, name, True)


def test_xai2_all_9_q_values_preserved():
    tid, name = "XAI2", "All 9 Q-values are preserved in descending rank order"
    trace = _build_test_decision_trace()
    xai = create_xai_result(trace)

    assert len(xai.q_rank_full) == 9, f"Expected 9 Q-values, got {len(xai.q_rank_full)}"
    assert xai.ai_top_choice == "-O3"
    assert math.isclose(xai.ai_top_q, 0.90)

    # Verify descending ordering
    q_vals = [qv for _, qv in xai.q_rank_full]
    assert q_vals == sorted(q_vals, reverse=True), "Q-values must be sorted descending"
    assert xai.q_rank_full[0][0] == xai.ai_top_choice
    assert math.isclose(xai.q_rank_full[0][1], xai.ai_top_q)
    report(tid, name, True)


def test_xai3_all_8_feature_values_preserved():
    tid, name = "XAI3", "All 8 feature values from canonical schema are preserved"
    trace = _build_test_decision_trace(include_features=True)
    xai = create_xai_result(trace)

    assert xai.ir_features is not None, "ir_features must not be None"
    assert len(xai.ir_features) == 8, f"Expected 8 features, got {len(xai.ir_features)}"
    for feat_name in CANONICAL_IR_FEATURE_NAMES:
        assert feat_name in xai.ir_features, f"Missing canonical feature: {feat_name}"
        assert math.isclose(xai.ir_features[feat_name], _SAMPLE_FEATURES[feat_name])

    # Test sequence/array input formatting
    seq = [12.0, 150.0, 18.0, 42.0, 30.0, 0.0, 0.0, 6.0]
    trace_no_feat = _build_test_decision_trace(include_features=False)
    xai_from_seq = create_xai_result(trace_no_feat, ir_features=seq)
    assert xai_from_seq.ir_features is not None
    assert len(xai_from_seq.ir_features) == 8
    assert math.isclose(xai_from_seq.ir_features["BasicBlocksCount"], 12.0)
    assert math.isclose(xai_from_seq.ir_features["CallInstCount"], 6.0)
    report(tid, name, True)


def test_xai4_pareto_information_preserved():
    tid, name = "XAI4", "Pareto information is preserved accurately"
    trace = _build_test_decision_trace()
    xai = create_xai_result(trace)

    assert xai.pareto_frontier == ["-O1", "-O2"]
    assert xai.pareto_dominated == ["-O0", "-O3"]
    assert xai.pareto_invalid == ["mem2reg,instcombine"]
    assert xai.candidates_considered == ["-O1", "-O2"]
    assert xai.filtered_out == ["-O3"]
    assert xai.moo_active is True
    assert xai.ai_choice_was_pareto_optimal is False
    report(tid, name, True)


def test_xai5_final_strategy_preserved():
    tid, name = "XAI5", "Final strategy is preserved"
    trace = _build_test_decision_trace()
    xai = create_xai_result(trace)
    assert xai.final_strategy == "-O1"
    report(tid, name, True)


def test_xai6_selection_reason_method_preserved():
    tid, name = "XAI6", "Selection reason and selection method are preserved"
    trace = _build_test_decision_trace()
    xai = create_xai_result(trace)

    assert xai.selection_reason == trace.selection_reason
    assert xai.selection_method == SELECTION_METHOD_MOO_AWARE
    report(tid, name, True)


def test_xai7_missing_optional_info_does_not_crash():
    tid, name = "XAI7", "Missing optional information does not crash"
    # Trace without features
    trace_no_feats = _build_test_decision_trace(include_features=False)
    xai1 = create_xai_result(trace_no_feats)
    assert xai1.ir_features is None

    # from_dict with empty dictionary
    xai_empty = XAIResult.from_dict({})
    assert xai_empty.ai_top_choice == ""
    assert xai_empty.ai_top_q == 0.0
    assert xai_empty.q_rank_full == []
    assert xai_empty.ir_features is None
    assert xai_empty.pareto_frontier == []
    assert xai_empty.final_strategy == ""
    assert xai_empty.moo_active is False
    assert xai_empty.ai_choice_was_pareto_optimal is None

    # Text summary on empty result
    summary = xai_empty.to_text_summary()
    assert isinstance(summary, str) and len(summary) > 0
    report(tid, name, True)


def test_xai8_json_serializable_round_trip():
    tid, name = "XAI8", "Output is JSON serializable and round-trip preserves all fields"
    trace = _build_test_decision_trace(include_features=True)
    xai = create_xai_result(trace)

    d = xai.to_dict()
    assert isinstance(d, dict)
    json_str = json.dumps(d)
    assert isinstance(json_str, str)

    loaded_dict = json.loads(json_str)
    reconstructed = XAIResult.from_dict(loaded_dict)

    assert reconstructed.ai_top_choice == xai.ai_top_choice
    assert math.isclose(reconstructed.ai_top_q, xai.ai_top_q)
    assert len(reconstructed.q_rank_full) == 9
    for (s1, q1), (s2, q2) in zip(xai.q_rank_full, reconstructed.q_rank_full):
        assert s1 == s2
        assert math.isclose(q1, q2)
    assert reconstructed.ir_features == xai.ir_features
    assert reconstructed.pareto_frontier == xai.pareto_frontier
    assert reconstructed.pareto_dominated == xai.pareto_dominated
    assert reconstructed.pareto_invalid == xai.pareto_invalid
    assert reconstructed.candidates_considered == xai.candidates_considered
    assert reconstructed.filtered_out == xai.filtered_out
    assert reconstructed.moo_active == xai.moo_active
    assert reconstructed.ai_choice_was_pareto_optimal == xai.ai_choice_was_pareto_optimal
    assert reconstructed.final_strategy == xai.final_strategy
    assert reconstructed.selection_reason == xai.selection_reason
    assert reconstructed.selection_method == xai.selection_method
    report(tid, name, True)


def test_xai9_decision_trace_behavior_unchanged():
    tid, name = "XAI9", "Existing DecisionTrace behavior remains unchanged"
    trace = _build_test_decision_trace(include_features=True)
    d = trace.to_dict()
    assert "final_strategy" in d
    assert "objective_snapshot" in d
    assert "ir_features" in d

    reconstructed_trace = DecisionTrace.from_dict(d)
    assert reconstructed_trace.final_strategy == trace.final_strategy
    assert reconstructed_trace.ir_features == trace.ir_features

    # Trace instantiated without ir_features works as before
    trace_old_style = DecisionTrace(
        ai_top_choice="-O2",
        ai_top_q=0.85,
        q_rank_full=[("-O2", 0.85)],
        pareto_frontier=["-O2"],
        pareto_dominated=[],
        pareto_invalid=[],
        objectives_used=["execution_time"],
        moo_active=True,
        ai_choice_was_pareto_optimal=True,
        candidates_considered=["-O2"],
        filtered_out=[],
        final_strategy="-O2",
        selection_reason="Selected -O2",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[],
    )
    assert trace_old_style.ir_features is None
    d_old = trace_old_style.to_dict()
    assert d_old["final_strategy"] == "-O2"
    report(tid, name, True)


def test_xai10_backward_compatibility_old_trace_data():
    tid, name = "XAI10", "Backward compatibility with old DecisionTrace dict without ir_features"
    old_trace_dict = {
        "ai_top_choice": "-O3",
        "ai_top_q": 0.90,
        "q_rank_full": [["-O3", 0.90], ["-O1", 0.60]],
        "pareto_frontier": ["-O1"],
        "pareto_dominated": ["-O3"],
        "pareto_invalid": [],
        "objectives_used": ["execution_time", "energy"],
        "moo_active": True,
        "ai_choice_was_pareto_optimal": False,
        "candidates_considered": ["-O1"],
        "filtered_out": ["-O3"],
        "final_strategy": "-O1",
        "selection_reason": "Selected -O1",
        "selection_method": SELECTION_METHOD_MOO_AWARE,
        "objective_snapshot": [],
    }
    # Notice: 'ir_features' is intentionally absent in old_trace_dict

    trace = DecisionTrace.from_dict(old_trace_dict)
    assert trace.ir_features is None

    # create_xai_result directly from old trace
    xai = create_xai_result(trace)
    assert xai.final_strategy == "-O1"
    assert xai.ir_features is None

    # create_xai_result directly from old dict
    xai_from_dict = create_xai_result(old_trace_dict)
    assert xai_from_dict.final_strategy == "-O1"
    assert xai_from_dict.ir_features is None
    report(tid, name, True)


def test_xai11_academic_terminology_compliance():
    tid, name = "XAI11", "XAI summary uses only academic terms, avoids confidence/causality claims"
    trace = _build_test_decision_trace(include_features=True)
    xai = create_xai_result(trace)

    buf = io.StringIO()
    print_xai_summary(xai, file=buf)
    summary_text = buf.getvalue().lower()

    # Allowed technical terms
    assert "q-value" in summary_text
    assert "model" in summary_text
    assert "pareto" in summary_text
    assert "feature" in summary_text

    # Prohibited claims
    prohibited = [
        "confidence score",
        "feature importance",
        "causal influence",
        "trust score",
        "model accuracy",
    ]
    for term in prohibited:
        assert term not in summary_text, f"Prohibited term '{term}' found in XAI summary!"
    report(tid, name, True)


def test_xai12_end_to_end_optimization_selector_integration():
    tid, name = "XAI12", "End-to-end integration: get_best_optimization with return_xai"
    if not os.path.isfile(TC1_PATH):
        skip(tid, name, f"{TC1_PATH} not found")
        return

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "optimization_selector",
        os.path.join(_PS_DIR, "optimization_selector.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["optimization_selector"] = mod
    spec.loader.exec_module(mod)

    # 1. return_trace=True should now populate ir_features on the trace
    strat1, trace1 = mod.get_best_optimization(TC1_PATH, return_trace=True)
    assert isinstance(strat1, str)
    assert trace1 is not None
    assert trace1.ir_features is not None, "trace1.ir_features should be populated from CompilerEnv"
    assert len(trace1.ir_features) == 8

    # 2. return_xai=True returns (strategy, xai_result)
    strat2, xai2 = mod.get_best_optimization(TC1_PATH, return_xai=True)
    assert strat2 == strat1
    assert isinstance(xai2, XAIResult)
    assert xai2.final_strategy == strat1
    assert len(xai2.q_rank_full) == 9
    assert xai2.ir_features is not None
    assert len(xai2.ir_features) == 8

    # 3. get_best_optimization_with_xai helper
    strat3, xai3 = mod.get_best_optimization_with_xai(TC1_PATH)
    assert strat3 == strat1
    assert isinstance(xai3, XAIResult)

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
    print("TOACD MOO Stage 8 - Explainable AI (XAI) Unit & Integration Tests")
    print("=" * 68 + "\n")

    test_xai1_create_from_valid_trace()
    test_xai2_all_9_q_values_preserved()
    test_xai3_all_8_feature_values_preserved()
    test_xai4_pareto_information_preserved()
    test_xai5_final_strategy_preserved()
    test_xai6_selection_reason_method_preserved()
    test_xai7_missing_optional_info_does_not_crash()
    test_xai8_json_serializable_round_trip()
    test_xai9_decision_trace_behavior_unchanged()
    test_xai10_backward_compatibility_old_trace_data()
    test_xai11_academic_terminology_compliance()
    test_xai12_end_to_end_optimization_selector_integration()

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
