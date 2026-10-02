"""
moo/tests/test_stage7_decision_trace.py — Stage 7 Decision Transparency tests.

Tests the DecisionTrace, ObjectiveSnapshot, moo_aware_select_with_trace,
backward compatibility, and get_best_optimization opt-in trace support.

Test plan (matches week6_final_spec.md Part 7):
------------------------------------------------
DT1  DecisionTrace.to_dict() is json.dumps() safe
DT2  DecisionTrace round-trip: from_dict(to_dict(trace)) preserves all fields
DT3  DecisionTrace.from_dict({}) produces valid trace with safe defaults
DT4  DecisionTrace.from_dict on report without decision_trace handles absence safely
OS1  ObjectiveSnapshot to_dict / from_dict round-trip preserves all fields
OS2  ObjectiveSnapshot preserves None values across serialization
WT1  moo_aware_select_with_trace returns same strategy as moo_aware_select
WT2  moo_aware_select_with_trace never raises on malformed / empty input
WT3  ai_top_choice == q_rank_full[0][0]
WT4  ai_choice_was_pareto_optimal=True when AI top choice is on the frontier
WT5  ai_choice_was_pareto_optimal=False when AI top choice is not on the frontier
WT6  ai_choice_was_pareto_optimal=None when frontier is empty
WT7  selection_method="moo_aware" when moo_active=True
WT8  selection_method="argmax_fallback_no_frontier" when frontier is empty
WT9  selection_method="argmax_fallback_frontier_mismatch" when frontier ∩ ACTIONS = ∅
WT10 filtered_out contains only strategies with Q > final selection Q
WT11 candidates_considered is a subset of pareto_frontier
WT12 With report_data=None, objective_snapshot is empty list
WT13 With report_data containing normalized dicts, objective_snapshot has correct ratios
WT14 ai_top_choice is included in objective_snapshot even when not in candidates_considered
BC1  _load_moo_report accepts old dict without decision_trace key
BC2  get_pareto_frontier_for still returns list[str] (backward compatibility)
BC3  moo_aware_select still returns SelectionResult (backward compatibility)
GB1  get_best_optimization with return_trace=False returns plain str
GB2  get_best_optimization with return_trace=True returns (str, DecisionTrace | None)
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import sys
import tempfile

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
from moo.selector_bridge import (
    SelectionResult,
    _load_moo_report,
    _load_report_for_trace,
    get_pareto_frontier_for,
    moo_aware_select,
    moo_aware_select_with_trace,
)
from moo.cli_report import print_decision_trace_summary


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

# -O3 has highest Q (0.90), -O1 has 0.60, -O2 has 0.55
_Q_HIGH_O3 = [0.10, 0.60, 0.55, 0.90, 0.30, 0.20, 0.15, 0.12, 0.08]


def _build_sample_report_data(
    source_file: str = "test.c",
    frontier: list[str] | None = None,
    dominated: list[str] | None = None,
    invalid: list[str] | None = None,
) -> dict:
    frontier = frontier if frontier is not None else ["-O1", "-O2"]
    dominated = dominated if dominated is not None else ["-O0", "-O3"]
    invalid = invalid if invalid is not None else [
        "mem2reg,instcombine",
        "mem2reg,simplifycfg",
        "mem2reg,instcombine,simplifycfg,dce",
        "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
        "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
    ]

    candidates = []
    # Assign representative normalized ratios
    ratios = {
        "-O1": {"time": 0.72, "energy": 0.68, "size": 0.91, "carbon": 0.68},
        "-O2": {"time": 0.71, "energy": 0.67, "size": 0.88, "carbon": 0.67},
        "-O3": {"time": 0.70, "energy": 0.67, "size": 0.97, "carbon": 0.67},
        "-O0": {"time": 1.00, "energy": 1.00, "size": 1.00, "carbon": 1.00},
    }

    for idx, act in enumerate(_ACTIONS):
        status = "FRONTIER" if act in frontier else ("DOMINATED" if act in dominated else "INVALID")
        cand_ratios = ratios.get(act, {"time": 0.85, "energy": 0.80, "size": 0.95, "carbon": 0.80})
        normalized_obj = {
            "objectives": [
                {"objective": {"name": "execution_time"}, "normalized_value": cand_ratios["time"]},
                {"objective": {"name": "energy"}, "normalized_value": cand_ratios["energy"]},
                {"objective": {"name": "code_size"}, "normalized_value": cand_ratios["size"]},
                {"objective": {"name": "carbon"}, "normalized_value": cand_ratios["carbon"]},
            ]
        } if status != "INVALID" else None

        candidates.append({
            "strategy_name": act,
            "strategy_index": idx,
            "strategy_kind": "clang_flag" if act.startswith("-O") else "opt_passes",
            "build_ok": status != "INVALID",
            "build_error": None if status != "INVALID" else "Build failed",
            "exe_path": None,
            "correctness_checked": True,
            "correct": status != "INVALID",
            "correctness_details": "" if status != "INVALID" else "Check failed",
            "reference_exit_code": 0,
            "candidate_exit_code": 0,
            "measurement": {"timing": {"median_s": 0.5}},
            "normalized": normalized_obj,
            "pareto_status": status,
            "dominated_by": ["-O1"] if status == "DOMINATED" else [],
        })

    return {
        "source_file": source_file,
        "source_path": f"/mock/{source_file}",
        "timestamp": "2026-10-02T10:00:00",
        "toolchain_ok": True,
        "toolchain_notes": [],
        "baseline": None,
        "candidates": candidates,
        "pareto_frontier": list(frontier),
        "pareto_dominated": list(dominated),
        "pareto_invalid": list(invalid),
        "objectives_used": ["execution_time", "energy", "code_size", "carbon"],
        "pipeline_error": None,
        "summary": {
            "n_strategies": len(_ACTIONS),
            "n_valid": len(frontier) + len(dominated),
            "n_invalid": len(invalid),
            "n_frontier": len(frontier),
            "n_dominated": len(dominated),
        },
    }


# ---------------------------------------------------------------------------
# DT Group: DecisionTrace Unit Tests
# ---------------------------------------------------------------------------

def test_dt1_to_dict_json_serializable():
    tid, name = "DT1", "DecisionTrace.to_dict() is json.dumps() safe"
    trace = DecisionTrace(
        ai_top_choice="-O3",
        ai_top_q=0.90,
        q_rank_full=[("-O3", 0.90), ("-O1", 0.60)],
        pareto_frontier=["-O1", "-O2"],
        pareto_dominated=["-O0", "-O3"],
        pareto_invalid=["mem2reg,instcombine"],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
        moo_active=True,
        ai_choice_was_pareto_optimal=False,
        candidates_considered=["-O1"],
        filtered_out=["-O3"],
        final_strategy="-O1",
        selection_reason="MOO-aware: selected highest-Q Pareto strategy '-O1'",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[
            ObjectiveSnapshot(
                strategy_name="-O1",
                pareto_status="FRONTIER",
                execution_time_ratio=0.72,
                energy_ratio=0.68,
                code_size_ratio=0.91,
                carbon_ratio=0.68,
                q_value=0.60,
            )
        ],
    )
    d = trace.to_dict()
    assert isinstance(d, dict), "to_dict() must return a dict"
    s = json.dumps(d)
    assert isinstance(s, str) and len(s) > 0, "json.dumps must produce a non-empty string"
    loaded = json.loads(s)
    assert loaded["final_strategy"] == "-O1", "JSON round-trip must preserve final_strategy"
    assert loaded["ai_top_choice"] == "-O3", "JSON round-trip must preserve ai_top_choice"
    assert loaded["ai_choice_was_pareto_optimal"] is False
    assert len(loaded["objective_snapshot"]) == 1
    report(tid, name, True)


def test_dt2_round_trip():
    tid, name = "DT2", "from_dict(to_dict(trace)) preserves all fields"
    trace = DecisionTrace(
        ai_top_choice="-O3",
        ai_top_q=0.95,
        q_rank_full=[("-O3", 0.95), ("-O2", 0.80), ("-O1", 0.60)],
        pareto_frontier=["-O2", "-O1"],
        pareto_dominated=["-O3"],
        pareto_invalid=["-O0"],
        objectives_used=["execution_time", "energy"],
        moo_active=True,
        ai_choice_was_pareto_optimal=False,
        candidates_considered=["-O2", "-O1"],
        filtered_out=["-O3"],
        final_strategy="-O2",
        selection_reason="Reason string",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[
            ObjectiveSnapshot(
                strategy_name="-O2",
                pareto_status="FRONTIER",
                execution_time_ratio=0.80,
                energy_ratio=0.75,
                code_size_ratio=None,
                carbon_ratio=None,
                q_value=0.80,
            )
        ],
    )
    d = trace.to_dict()
    reconstructed = DecisionTrace.from_dict(d)

    assert reconstructed.ai_top_choice == trace.ai_top_choice
    assert math.isclose(reconstructed.ai_top_q, trace.ai_top_q)
    assert reconstructed.q_rank_full == trace.q_rank_full
    assert reconstructed.pareto_frontier == trace.pareto_frontier
    assert reconstructed.pareto_dominated == trace.pareto_dominated
    assert reconstructed.pareto_invalid == trace.pareto_invalid
    assert reconstructed.objectives_used == trace.objectives_used
    assert reconstructed.moo_active == trace.moo_active
    assert reconstructed.ai_choice_was_pareto_optimal == trace.ai_choice_was_pareto_optimal
    assert reconstructed.candidates_considered == trace.candidates_considered
    assert reconstructed.filtered_out == trace.filtered_out
    assert reconstructed.final_strategy == trace.final_strategy
    assert reconstructed.selection_reason == trace.selection_reason
    assert reconstructed.selection_method == trace.selection_method
    assert len(reconstructed.objective_snapshot) == 1
    assert reconstructed.objective_snapshot[0].strategy_name == "-O2"
    assert reconstructed.objective_snapshot[0].code_size_ratio is None
    report(tid, name, True)


def test_dt3_from_dict_empty():
    tid, name = "DT3", "DecisionTrace.from_dict({}) produces valid trace with safe defaults"
    trace = DecisionTrace.from_dict({})
    assert isinstance(trace, DecisionTrace)
    assert trace.ai_top_choice == ""
    assert trace.ai_top_q == 0.0
    assert trace.q_rank_full == []
    assert trace.pareto_frontier == []
    assert trace.pareto_dominated == []
    assert trace.pareto_invalid == []
    assert trace.objectives_used == []
    assert trace.moo_active is False
    assert trace.ai_choice_was_pareto_optimal is None
    assert trace.candidates_considered == []
    assert trace.filtered_out == []
    assert trace.final_strategy == ""
    assert trace.selection_reason == ""
    assert trace.selection_method == SELECTION_METHOD_ARGMAX_NO_FRONTIER
    assert trace.objective_snapshot == []
    report(tid, name, True)


def test_dt4_from_dict_missing_in_report():
    tid, name = "DT4", "DecisionTrace handling of absent key in report"
    # Old report dictionary without 'decision_trace' key
    old_report = _build_sample_report_data()
    assert "decision_trace" not in old_report
    trace_dict = old_report.get("decision_trace")
    assert trace_dict is None
    trace = DecisionTrace.from_dict(trace_dict) if trace_dict else None
    assert trace is None, "Missing decision_trace in report must safely evaluate to None"
    report(tid, name, True)


# ---------------------------------------------------------------------------
# OS Group: ObjectiveSnapshot Unit Tests
# ---------------------------------------------------------------------------

def test_os1_objective_snapshot_round_trip():
    tid, name = "OS1", "ObjectiveSnapshot to_dict / from_dict round-trip"
    snap = ObjectiveSnapshot(
        strategy_name="-O1",
        pareto_status="FRONTIER",
        execution_time_ratio=0.725,
        energy_ratio=0.681,
        code_size_ratio=0.912,
        carbon_ratio=0.680,
        q_value=0.60,
    )
    d = snap.to_dict()
    reconstructed = ObjectiveSnapshot.from_dict(d)
    assert reconstructed.strategy_name == "-O1"
    assert reconstructed.pareto_status == "FRONTIER"
    assert math.isclose(reconstructed.execution_time_ratio, 0.725)
    assert math.isclose(reconstructed.energy_ratio, 0.681)
    assert math.isclose(reconstructed.code_size_ratio, 0.912)
    assert math.isclose(reconstructed.carbon_ratio, 0.680)
    assert math.isclose(reconstructed.q_value, 0.60)
    report(tid, name, True)


def test_os2_objective_snapshot_none_values():
    tid, name = "OS2", "ObjectiveSnapshot preserves None values across serialization"
    snap = ObjectiveSnapshot(
        strategy_name="-O3",
        pareto_status="DOMINATED",
        execution_time_ratio=None,
        energy_ratio=None,
        code_size_ratio=None,
        carbon_ratio=None,
        q_value=None,
    )
    d = snap.to_dict()
    assert d["execution_time_ratio"] is None
    assert d["q_value"] is None
    reconstructed = ObjectiveSnapshot.from_dict(d)
    assert reconstructed.execution_time_ratio is None
    assert reconstructed.energy_ratio is None
    assert reconstructed.code_size_ratio is None
    assert reconstructed.carbon_ratio is None
    assert reconstructed.q_value is None
    report(tid, name, True)


# ---------------------------------------------------------------------------
# WT Group: moo_aware_select_with_trace Tests
# ---------------------------------------------------------------------------

def test_wt1_same_strategy_as_base():
    tid, name = "WT1", "moo_aware_select_with_trace returns same strategy as moo_aware_select"
    frontier = ["-O1", "-O2"]
    base_res = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert res.strategy == base_res.strategy, "Strategy must match exactly"
    assert res.reason == base_res.reason
    assert res.moo_active == base_res.moo_active
    assert res.filtered_out == base_res.filtered_out
    assert trace is not None
    assert trace.final_strategy == base_res.strategy
    report(tid, name, True)


def test_wt2_never_raises():
    tid, name = "WT2", "moo_aware_select_with_trace never raises on bad input"
    try:
        # Mismatched lengths
        res, trace = moo_aware_select_with_trace("test.c", [0.5], _ACTIONS, ["-O1"])
        assert isinstance(res.strategy, str)
        assert trace is not None

        # Empty actions
        res2, trace2 = moo_aware_select_with_trace("test.c", [], [], [])
        assert isinstance(res2.strategy, str)

        # Non-numeric Q values causing internal errors
        res3, trace3 = moo_aware_select_with_trace("test.c", ["bad"], ["act"], [])
        assert isinstance(res3.strategy, str)
        report(tid, name, True)
    except Exception as e:
        report(tid, name, False, f"Raised exception: {e}")


def test_wt3_ai_top_choice():
    tid, name = "WT3", "ai_top_choice == q_rank_full[0][0]"
    frontier = ["-O1"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert trace.ai_top_choice == "-O3"
    assert trace.ai_top_choice == trace.q_rank_full[0][0]
    assert math.isclose(trace.ai_top_q, 0.90)
    report(tid, name, True)


def test_wt4_ai_choice_was_pareto_optimal_true():
    tid, name = "WT4", "ai_choice_was_pareto_optimal=True when AI top is on frontier"
    # -O3 is highest Q and is in frontier
    frontier = ["-O1", "-O3"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert trace.ai_top_choice == "-O3"
    assert trace.ai_choice_was_pareto_optimal is True
    assert trace.final_strategy == "-O3"
    assert trace.filtered_out == []
    report(tid, name, True)


def test_wt5_ai_choice_was_pareto_optimal_false():
    tid, name = "WT5", "ai_choice_was_pareto_optimal=False when AI top not on frontier"
    # -O3 is highest Q (0.9) but frontier is only [-O1, -O2]
    frontier = ["-O1", "-O2"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert trace.ai_top_choice == "-O3"
    assert trace.ai_choice_was_pareto_optimal is False
    assert trace.final_strategy == "-O1"
    assert "-O3" in trace.filtered_out
    report(tid, name, True)


def test_wt6_ai_choice_was_pareto_optimal_none_when_empty_frontier():
    tid, name = "WT6", "ai_choice_was_pareto_optimal=None when frontier is empty"
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, [])
    assert trace is not None
    assert trace.ai_choice_was_pareto_optimal is None
    assert trace.moo_active is False
    assert trace.final_strategy == "-O3"  # pure argmax
    report(tid, name, True)


def test_wt7_selection_method_moo_aware():
    tid, name = "WT7", "selection_method='moo_aware' when moo_active=True"
    frontier = ["-O1", "-O2"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert trace.moo_active is True
    assert trace.selection_method == SELECTION_METHOD_MOO_AWARE
    report(tid, name, True)


def test_wt8_selection_method_no_frontier():
    tid, name = "WT8", "selection_method='argmax_fallback_no_frontier' when frontier is empty"
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, [])
    assert trace is not None
    assert trace.moo_active is False
    assert trace.selection_method == SELECTION_METHOD_ARGMAX_NO_FRONTIER
    report(tid, name, True)


def test_wt9_selection_method_frontier_mismatch():
    tid, name = "WT9", "selection_method='argmax_fallback_frontier_mismatch' when frontier ∩ ACTIONS = ∅"
    frontier = ["unknown_pass_alpha", "unknown_pass_beta"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert trace.moo_active is False
    assert trace.selection_method == SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH
    assert trace.candidates_considered == []
    report(tid, name, True)


def test_wt10_filtered_out_strictly_higher_q():
    tid, name = "WT10", "filtered_out only contains strategies with Q > final selection Q"
    # Frontier: [-O1, -O2]. Selected: -O1 (Q=0.60).
    # Strategies with Q > 0.60: only -O3 (Q=0.90).
    # Other actions have Q <= 0.60 (e.g. -O2=0.55, -O0=0.30)
    frontier = ["-O1", "-O2"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    q_map = dict(zip(_ACTIONS, _Q_HIGH_O3))
    selected_q = q_map[trace.final_strategy]
    for act in trace.filtered_out:
        assert q_map[act] > selected_q, f"Strategy {act} in filtered_out must have Q > selected_q"
    assert trace.filtered_out == ["-O3"]
    report(tid, name, True)


def test_wt11_candidates_considered_subset_of_frontier():
    tid, name = "WT11", "candidates_considered is a subset of pareto_frontier"
    frontier = ["-O1", "-O2", "unknown_pass"]
    res, trace = moo_aware_select_with_trace("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert trace is not None
    assert set(trace.candidates_considered).issubset(set(frontier))
    # Must only contain ACTIONS members
    assert set(trace.candidates_considered).issubset(set(_ACTIONS))
    assert trace.candidates_considered == ["-O1", "-O2"]
    report(tid, name, True)


def test_wt12_objective_snapshot_empty_without_report():
    tid, name = "WT12", "With report_data=None, objective_snapshot is empty list"
    frontier = ["-O1", "-O2"]
    res, trace = moo_aware_select_with_trace(
        "test.c", _Q_HIGH_O3, _ACTIONS, frontier, report_data=None
    )
    assert trace is not None
    assert trace.objective_snapshot == []
    report(tid, name, True)


def test_wt13_objective_snapshot_populated():
    tid, name = "WT13", "With report_data containing normalized dicts, objective_snapshot has correct ratios"
    frontier = ["-O1", "-O2"]
    report_data = _build_sample_report_data(frontier=frontier)
    res, trace = moo_aware_select_with_trace(
        "test.c", _Q_HIGH_O3, _ACTIONS, frontier, report_data=report_data
    )
    assert trace is not None
    assert len(trace.objective_snapshot) > 0
    names = {s.strategy_name for s in trace.objective_snapshot}
    assert "-O1" in names
    assert "-O2" in names
    # Verify ratio values match
    s_o1 = next(s for s in trace.objective_snapshot if s.strategy_name == "-O1")
    assert math.isclose(s_o1.execution_time_ratio, 0.72)
    assert math.isclose(s_o1.energy_ratio, 0.68)
    assert math.isclose(s_o1.code_size_ratio, 0.91)
    assert math.isclose(s_o1.carbon_ratio, 0.68)
    assert math.isclose(s_o1.q_value, 0.60)
    report(tid, name, True)


def test_wt14_ai_top_included_in_snapshot():
    tid, name = "WT14", "ai_top_choice included in objective_snapshot even when not in candidates_considered"
    # -O3 is ai_top_choice, but NOT in frontier
    frontier = ["-O1", "-O2"]
    report_data = _build_sample_report_data(frontier=frontier)
    res, trace = moo_aware_select_with_trace(
        "test.c", _Q_HIGH_O3, _ACTIONS, frontier, report_data=report_data
    )
    assert trace is not None
    assert "-O3" not in trace.candidates_considered
    snapshot_names = [s.strategy_name for s in trace.objective_snapshot]
    assert "-O3" in snapshot_names, "ai_top_choice -O3 must be present in objective_snapshot"
    s_o3 = next(s for s in trace.objective_snapshot if s.strategy_name == "-O3")
    assert s_o3.pareto_status == "DOMINATED"
    assert math.isclose(s_o3.q_value, 0.90)
    report(tid, name, True)


# ---------------------------------------------------------------------------
# BC Group: Backward Compatibility Tests
# ---------------------------------------------------------------------------

def test_bc1_load_moo_report_old_format():
    tid, name = "BC1", "_load_moo_report accepts old dict without decision_trace key"
    tmpdir = tempfile.mkdtemp()
    try:
        old_data = _build_sample_report_data("old_test.c")
        # Ensure decision_trace is absent
        assert "decision_trace" not in old_data
        json_path = os.path.join(tmpdir, "moo_old_test_c_2026-10-01_00-00-00.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        loaded = _load_moo_report(json_path)
        assert loaded is not None, "Old report without decision_trace must load successfully"
        assert loaded["source_file"] == "old_test.c"
        assert loaded.get("decision_trace") is None, "Missing key should evaluate to None via .get()"
        report(tid, name, True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_bc2_get_pareto_frontier_returns_list():
    tid, name = "BC2", "get_pareto_frontier_for still returns list[str] (backward compat)"
    tmpdir = tempfile.mkdtemp()
    try:
        data = _build_sample_report_data("bc2_test.c", frontier=["-O1", "-O3"])
        json_path = os.path.join(tmpdir, "moo_bc2_test_c_2026-10-01_00-00-00.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        frontier = get_pareto_frontier_for("bc2_test.c", report_dir=tmpdir)
        assert isinstance(frontier, list), "Return value must be a list"
        assert all(isinstance(x, str) for x in frontier)
        assert sorted(frontier) == sorted(["-O1", "-O3"])
        report(tid, name, True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_bc3_moo_aware_select_returns_selection_result():
    tid, name = "BC3", "moo_aware_select still returns SelectionResult (backward compat)"
    frontier = ["-O1", "-O2"]
    res = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    assert isinstance(res, SelectionResult), "Must be SelectionResult instance"
    assert hasattr(res, "strategy")
    assert hasattr(res, "reason")
    assert hasattr(res, "frontier")
    assert hasattr(res, "q_rank")
    assert hasattr(res, "moo_active")
    assert hasattr(res, "filtered_out")
    report(tid, name, True)


# ---------------------------------------------------------------------------
# GB Group: get_best_optimization Tests
# ---------------------------------------------------------------------------

def test_gb1_get_best_optimization_returns_str():
    tid, name = "GB1", "get_best_optimization with return_trace=False returns plain str"
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

    res = mod.get_best_optimization(TC1_PATH)
    assert isinstance(res, str), f"Expected str, got {type(res)}"
    assert res in _ACTIONS, f"Expected action in _ACTIONS, got {res}"
    report(tid, name, True)


def test_gb2_get_best_optimization_returns_tuple():
    tid, name = "GB2", "get_best_optimization with return_trace=True returns (str, DecisionTrace|None)"
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

    result = mod.get_best_optimization(TC1_PATH, return_trace=True)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected 2-tuple, got len={len(result)}"
    strategy, trace = result
    assert isinstance(strategy, str), f"Expected str strategy, got {type(strategy)}"
    assert strategy in _ACTIONS, f"Expected strategy in _ACTIONS, got {strategy}"
    assert trace is None or isinstance(trace, DecisionTrace), f"Expected DecisionTrace or None, got {type(trace)}"
    if trace is not None:
        assert trace.final_strategy == strategy, "trace.final_strategy must match returned strategy"
    report(tid, name, True)


# ---------------------------------------------------------------------------
# CLI Reporter Unit Test (verifies print_decision_trace_summary formatting)
# ---------------------------------------------------------------------------

def test_cli_reporter():
    trace = DecisionTrace(
        ai_top_choice="-O3",
        ai_top_q=0.90,
        q_rank_full=[("-O3", 0.90), ("-O1", 0.60), ("-O2", 0.55)],
        pareto_frontier=["-O1", "-O2"],
        pareto_dominated=["-O3"],
        pareto_invalid=[],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
        moo_active=True,
        ai_choice_was_pareto_optimal=False,
        candidates_considered=["-O1", "-O2"],
        filtered_out=["-O3"],
        final_strategy="-O1",
        selection_reason="MOO-aware: selected highest-Q Pareto strategy '-O1'",
        selection_method=SELECTION_METHOD_MOO_AWARE,
        objective_snapshot=[
            ObjectiveSnapshot("-O1", "FRONTIER", 0.72, 0.68, 0.91, 0.68, 0.60),
            ObjectiveSnapshot("-O3", "DOMINATED", 0.70, 0.67, 0.97, 0.67, 0.90),
        ],
    )
    buf = io.StringIO()
    print_decision_trace_summary(trace, file=buf)
    out = buf.getvalue()
    assert "DECISION TRACE" in out
    assert "-O3" in out
    assert "-O1" in out
    assert "moo_aware" in out


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print("TOACD MOO Stage 7 - Decision Trace Unit & Integration Tests")
    print("=" * 65)

    print("\n--- DT Group: DecisionTrace Unit Tests ---")
    test_dt1_to_dict_json_serializable()
    test_dt2_round_trip()
    test_dt3_from_dict_empty()
    test_dt4_from_dict_missing_in_report()

    print("\n--- OS Group: ObjectiveSnapshot Unit Tests ---")
    test_os1_objective_snapshot_round_trip()
    test_os2_objective_snapshot_none_values()

    print("\n--- WT Group: moo_aware_select_with_trace Tests ---")
    test_wt1_same_strategy_as_base()
    test_wt2_never_raises()
    test_wt3_ai_top_choice()
    test_wt4_ai_choice_was_pareto_optimal_true()
    test_wt5_ai_choice_was_pareto_optimal_false()
    test_wt6_ai_choice_was_pareto_optimal_none_when_empty_frontier()
    test_wt7_selection_method_moo_aware()
    test_wt8_selection_method_no_frontier()
    test_wt9_selection_method_frontier_mismatch()
    test_wt10_filtered_out_strictly_higher_q()
    test_wt11_candidates_considered_subset_of_frontier()
    test_wt12_objective_snapshot_empty_without_report()
    test_wt13_objective_snapshot_populated()
    test_wt14_ai_top_included_in_snapshot()

    print("\n--- BC Group: Backward Compatibility Tests ---")
    test_bc1_load_moo_report_old_format()
    test_bc2_get_pareto_frontier_returns_list()
    test_bc3_moo_aware_select_returns_selection_result()

    print("\n--- GB Group: get_best_optimization Tests ---")
    test_gb1_get_best_optimization_returns_str()
    test_gb2_get_best_optimization_returns_tuple()

    test_cli_reporter()

    print()
    print("=" * 65)
    passed = sum(1 for _, _, s in _results if s == "PASS")
    failed = sum(1 for _, _, s in _results if s == "FAIL")
    skipped = sum(1 for _, _, s in _results if s == "SKIP")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 65 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
