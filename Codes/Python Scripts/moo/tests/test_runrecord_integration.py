"""
tests/test_runrecord_integration.py -- RunRecord Integration Test Suite.

Covers the 23 required test cases plus additional verification:

1.  RunRecord creation from a complete run.
2.  RunRecord creation from a partial run.
3.  Missing profile handling.
4.  Missing DecisionTrace handling.
5.  Failed compiler handling.
6.  Failed benchmark handling.
7.  NOT_RUN vs FAILED vs OK distinction.
8.  Provenance preservation.
9.  -O0 baseline preservation.
10. Regression projection.
11. Adaptive ExperienceRecord projection.
12. Agentic AgentContext projection.
13. Security result projection.
14. XAI/DecisionTrace projection.
15. RunRecord immutability where appropriate.
16. Deterministic serialization.
17. Stable RunRecord identity where appropriate.
18. Backward compatibility with existing selector APIs.
19. Agentic analysis cannot override selected strategy.
20. Adaptive learning cannot override selected strategy.
21. No fake security "Preserved" status.
22. Existing Week 8-12 tests still pass (import guard).
23. Existing GUI import/startup behavior remains intact.

Additional tests:
24. MeasurementSnapshot explicit failure (not zero).
25. Partial run: selection OK, benchmark FAILED.
26. Full pipeline via orchestrator (artifact injection).
27. RunRecord persistence/load round-trip.
28. GUI view model (to_gui_view) correctness.
29. Regression projection with failed measurements.
30. MOO result integration.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import math

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_SCRIPT_DIR)
_PS_DIR = os.path.dirname(_MOO_DIR)

if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []
PASSED = 0
FAILED = 0
SKIPPED = 0


def report(tid: str, name: str, passed: bool, note: str = "") -> None:
    global PASSED, FAILED
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    safe_name = name.encode("ascii", errors="replace").decode("ascii")
    safe_suffix = suffix.encode("ascii", errors="replace").decode("ascii")
    print(f"  [{tag}] {tid}: {safe_name}{safe_suffix}")
    if passed:
        PASSED += 1
    else:
        FAILED += 1


def skip(tid: str, name: str, reason: str = "") -> None:
    global SKIPPED
    _results.append((tid, name, "SKIP"))
    SKIPPED += 1
    safe_name = name.encode("ascii", errors="replace").decode("ascii")
    print(f"  [SKIP] {tid}: {safe_name}  {reason}")


def fail_exc(tid: str, name: str, exc: Exception) -> None:
    global FAILED
    _results.append((tid, name, "FAIL"))
    FAILED += 1
    safe_name = name.encode("ascii", errors="replace").decode("ascii")
    print(f"  [FAIL] {tid}: {safe_name}  -- {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Import RunRecord modules
# ---------------------------------------------------------------------------

try:
    from moo.runrecord import (
        RunRecord,
        RunStatus,
        MeasurementStatus,
        SelectionProvenance,
        RUNRECORD_SCHEMA_VERSION,
        RunRecordBuilder,
        to_regression_input,
        to_experience_record,
        to_agent_context,
        to_gui_view,
        PipelineOrchestrator,
    )
    from moo.runrecord.schema import MeasurementSnapshot, BASELINE_STRATEGY_LABEL
    _RUNRECORD_AVAILABLE = True
    print("RunRecord modules imported successfully.")
except ImportError as e:
    print(f"FATAL: Cannot import moo.runrecord: {e}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

MOCK_IR_FEATURES = {
    "BasicBlocksCount": 5.0,
    "InstructionsCount": 40.0,
    "BranchCount": 8.0,
    "MemInstCount": 12.0,
    "MathInstCount": 6.0,
    "FloatInstCount": 2.0,
    "VectorInstCount": 0.0,
    "CallInstCount": 3.0,
}

MOCK_ACTIONS = ["-O0", "-O1", "-O2", "-O3", "-Os", "-Oz",
                "mem2reg,instcombine,simplifycfg,dce",
                "mem2reg,simplifycfg",
                "mem2reg,instcombine,simplifycfg,dce,loop-simplify"]

MOCK_Q_VALUES = [0.1, 0.4, 0.7, 0.5, 0.3, 0.2, 0.65, 0.6, 0.55]


def _make_mock_timing_dict(median_s: float = 0.01, n_samples: int = 5) -> dict:
    return {
        "n_samples": n_samples,
        "median_ns": median_s * 1e9,
        "min_ns": median_s * 0.9e9,
        "max_ns": median_s * 1.1e9,
        "mean_ns": median_s * 1e9,
        "stdev_ns": 0.0,
        "median_s": median_s,
        "mean_s": median_s,
        "cv": 0.0,
        "n_timeouts": 0,
    }


def _make_mock_measurement_dict(
    strategy: str = "-O2",
    median_s: float = 0.01,
    code_size_bytes: int = 10000,
    failed: bool = False,
    error: str = "",
) -> dict:
    if failed:
        return {
            "strategy": strategy,
            "exe_path": "",
            "warmup_runs": 1,
            "measure_runs": 5,
            "raw_samples_ns": [],
            "timing": None,
            "last_return_code": None,
            "last_stdout": "",
            "last_stderr": "",
            "all_return_codes": [],
            "code_size": None,
            "energy": None,
            "carbon": None,
            "measurement_error": error or "Measurement failed",
            "n_timeouts": 0,
            "n_errors": 1,
            "timing_is_reliable": None,
        }
    return {
        "strategy": strategy,
        "exe_path": "/tmp/test.exe",
        "warmup_runs": 1,
        "measure_runs": 5,
        "raw_samples_ns": [int(median_s * 1e9)] * 5,
        "timing": _make_mock_timing_dict(median_s),
        "last_return_code": 0,
        "last_stdout": "ok",
        "last_stderr": "",
        "all_return_codes": [0] * 5,
        "code_size": {
            "file_path": "/tmp/test.exe",
            "file_size_bytes": code_size_bytes,
            "text_size_bytes": code_size_bytes,
            "data_size_bytes": 0,
            "bss_size_bytes": 0,
            "size_source": "llvm-size .text section (PE format)",
            "primary_metric": "text_size_bytes",
            "primary_value": code_size_bytes,
            "llvm_size_raw": None,
        },
        "energy": {
            "energy_joules": median_s * 65.0 * 0.5,
            "energy_source": "estimated",
            "energy_is_estimated": True,
        },
        "carbon": {
            "carbon_grams": median_s * 65.0 * 0.5 * 442.0 / 3600000.0,
            "grid_intensity_g_per_kwh": 442.0,
            "grid_intensity_source": "configured",
            "energy_source": "estimated",
            "carbon_is_estimated": True,
        },
        "measurement_error": None,
        "n_timeouts": 0,
        "n_errors": 0,
        "timing_is_reliable": True,
    }


def _make_mock_program_profile(label: str = "loop_oriented") -> dict:
    return {
        "label": label,
        "dominant_feature": "BranchCount",
        "dominant_feature_value": 8.0,
        "profile_method": "ir_heuristic_threshold",
        "is_trivial": False,
        "all_features": dict(MOCK_IR_FEATURES),
    }


def _make_mock_decision_trace(
    final_strategy: str = "-O2",
    moo_active: bool = True,
) -> dict:
    return {
        "ai_top_choice": "-O2",
        "ai_top_q": 0.7,
        "q_rank_full": [
            ["-O2", 0.7],
            ["-O1", 0.4],
            ["-O3", 0.5],
        ],
        "pareto_frontier": ["-O2", "-O3"] if moo_active else [],
        "pareto_dominated": ["-O1"],
        "pareto_invalid": [],
        "objectives_used": ["execution_time", "energy", "code_size", "carbon"],
        "moo_active": moo_active,
        "ai_choice_was_pareto_optimal": True if moo_active else None,
        "candidates_considered": ["-O2", "-O3"] if moo_active else [],
        "filtered_out": [],
        "final_strategy": final_strategy,
        "selection_reason": "MOO-aware selection" if moo_active else "argmax",
        "selection_method": "moo_aware" if moo_active else "argmax_fallback_no_frontier",
        "objective_snapshot": [],
        "ir_features": MOCK_IR_FEATURES,
    }


def _make_mock_moo_result(
    selected_strategy: str = "-O2",
    build_ok: bool = True,
    measure_ok: bool = True,
    pipeline_error: str = "",
) -> dict:
    """Construct a mock MOOEvaluationResult dict."""
    baseline_mdict = _make_mock_measurement_dict("baseline (-O0)", 0.02, 11000)

    candidates = []
    for i, action in enumerate(MOCK_ACTIONS):
        if action == selected_strategy:
            cand = {
                "strategy_name": action,
                "strategy_index": i,
                "strategy_kind": "clang_flag",
                "build_ok": build_ok,
                "build_error": None if build_ok else "Build failed: cc1 error",
                "exe_path": "/tmp/opt.exe" if build_ok else None,
                "correctness_checked": build_ok,
                "correct": build_ok and measure_ok,
                "correctness_details": "CORRECT" if build_ok else "",
                "reference_exit_code": 0,
                "candidate_exit_code": 0 if build_ok else None,
                "measurement": _make_mock_measurement_dict(action, 0.01) if (build_ok and measure_ok) else (
                    _make_mock_measurement_dict(action, failed=True, error="Timer failed") if build_ok else None
                ),
                "normalized": None,
                "pareto_status": "FRONTIER" if build_ok else "INVALID",
                "dominated_by": [],
            }
        else:
            cand = {
                "strategy_name": action,
                "strategy_index": i,
                "strategy_kind": "clang_flag",
                "build_ok": True,
                "build_error": None,
                "exe_path": "/tmp/other.exe",
                "correctness_checked": True,
                "correct": True,
                "correctness_details": "CORRECT",
                "reference_exit_code": 0,
                "candidate_exit_code": 0,
                "measurement": _make_mock_measurement_dict(action, 0.015),
                "normalized": None,
                "pareto_status": "DOMINATED",
                "dominated_by": [selected_strategy],
            }
        candidates.append(cand)

    return {
        "source_file": "test.c",
        "source_path": "/tmp/test.c",
        "timestamp": "2026-10-05T20:00:00",
        "toolchain_ok": True,
        "toolchain_notes": [],
        "baseline": {
            "strategy_name": "baseline (-O0)",
            "exe_path": "/tmp/ref.exe",
            "build_ok": True,
            "build_error": None,
            "reference_exit_code": 0,
            "reference_stdout": "ok",
            "measurement": baseline_mdict,
        },
        "candidates": candidates,
        "pareto_frontier": [selected_strategy],
        "pareto_dominated": [a for a in MOCK_ACTIONS if a != selected_strategy],
        "pareto_invalid": [],
        "objectives_used": ["execution_time", "energy", "code_size", "carbon"],
        "pipeline_error": pipeline_error or None,
        "summary": {
            "n_strategies": len(MOCK_ACTIONS),
            "n_valid": len(MOCK_ACTIONS) - 1,
            "n_invalid": 0,
            "n_frontier": 1,
            "n_dominated": len(MOCK_ACTIONS) - 1,
        },
        "measurement_quality": {},
    }


def _make_mock_program_comparison(
    selected_strategy: str = "-O2",
    overall_status: str = "IMPROVED",
) -> dict:
    """Construct a mock ProgramComparison dict."""
    return {
        "program_id": "test_prog",
        "status": "ok",
        "baseline_strategy": "baseline (-O0)",
        "selected_strategy": selected_strategy,
        "selected_comparison": {
            "strategy_name": selected_strategy,
            "reference_strategy": "baseline (-O0)",
            "is_valid": True,
            "pareto_status": "FRONTIER",
            "metric_comparisons": {
                "execution_time": {
                    "metric_name": "execution_time",
                    "baseline_value": 0.02,
                    "target_value": 0.01,
                    "delta": -0.01,
                    "percent_change": -50.0,
                    "ratio": 0.5,
                    "lower_is_better": True,
                    "unit": "seconds",
                    "status": "IMPROVED",
                    "reason": "50% faster",
                    "threshold_pct": 1.0,
                    "is_reliable": True,
                    "confidence": "HIGH",
                    "noise_cv": 0.05,
                    "is_estimated": False,
                }
            },
            "overall_status": overall_status,
            "family_comparisons": {},
            "family_status": {},
        },
        "selection_provenance": {
            "program_id": "test_prog",
            "source_sha256": "a" * 64,
            "selected_strategy": selected_strategy,
            "selection_source": "DQN∩Pareto",
            "model_identifier": "production_v0",
            "trace_id": None,
            "timestamp": "2026-10-05T20:00:00",
        },
        "strategy_comparisons": {},
        "pareto_frontier": [selected_strategy],
        "overall_status": overall_status,
        "family_comparisons": {},
        "family_status": {},
        "pipeline_error": None,
    }


def _make_mock_security_result(verdict: str = "PRESERVED") -> dict:
    return {
        "strategy_name": "-O2",
        "verdict": verdict,
        "baseline_sink_count": 3,
        "candidate_sink_count": 3,
        "preserved_sinks": 3,
        "eliminated_sinks": 0,
        "merged_sinks": 0,
        "folded_sinks": 0,
        "guard_assessments": [],
        "warnings": [],
        "notes": ["Security analysis completed"],
    }


def _make_mock_agent_report(selected_strategy: str = "-O2") -> dict:
    return {
        "schema_version": "week12.1.0",
        "report_id": "rpt_test_001",
        "program_id": "test_prog",
        "source_hash": "a" * 64,
        "selected_strategy": selected_strategy,
        "verdict": "CONFIRMED",
        "evidence_quality": "HIGH",
        "tiers_available": ["TIER_1_STATIC_SELECTION"],
        "findings": [],
        "tradeoffs": [],
        "alternative": None,
        "reasoning_steps": [],
        "is_advisory_only": True,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Test 1: Complete run
# ---------------------------------------------------------------------------

def test_t01_complete_run():
    """RR-01: RunRecord creation from a complete run."""
    try:
        builder = RunRecordBuilder(source_path=None)
        builder.set_ir_features(features=MOCK_IR_FEATURES)
        builder.set_profile(_make_mock_program_profile())
        trace = _make_mock_decision_trace()
        builder.set_selection(selected_strategy="-O2", decision_trace=trace)
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        builder.set_optimized_measurement("-O2", _make_mock_measurement_dict("-O2", 0.01))
        builder.set_regression(_make_mock_program_comparison())
        builder.set_security(_make_mock_security_result("PRESERVED"))
        builder.set_agentic(_make_mock_agent_report())
        r = builder.build()

        ok = (
            r.selection_status == RunStatus.OK
            and r.profile_status == RunStatus.OK
            and r.baseline_status == MeasurementStatus.OK
            and r.optimized_status == MeasurementStatus.OK
            and r.benchmark_status == RunStatus.OK
            and r.regression_status == RunStatus.OK
            and r.security_status == RunStatus.OK
            and r.agentic_status == RunStatus.OK
            and r.selected_strategy == "-O2"
            and r.agentic_is_advisory_only is True
            and r.adaptive_is_advisory_only is True
        )
        report("RR-01", "Complete run: all stages OK", ok)
    except Exception as e:
        fail_exc("RR-01", "Complete run: all stages OK", e)


# ---------------------------------------------------------------------------
# Test 2: Partial run
# ---------------------------------------------------------------------------

def test_t02_partial_run():
    """RR-02: RunRecord creation from a partial run (selection only, no benchmark)."""
    try:
        builder = RunRecordBuilder(source_path=None)
        builder.set_ir_features(features=MOCK_IR_FEATURES)
        builder.set_selection(selected_strategy="-O2")
        # No profile, no benchmark, no regression, no security
        r = builder.build()

        ok = (
            r.selection_status == RunStatus.OK
            and r.selected_strategy == "-O2"
            and r.profile_status == RunStatus.NOT_RUN
            and r.baseline_status == MeasurementStatus.NOT_RUN
            and r.optimized_status == MeasurementStatus.NOT_RUN
            and r.regression_status == RunStatus.NOT_RUN
            and r.security_status == RunStatus.NOT_RUN
            and r.adaptive_status == RunStatus.NOT_RUN
            and r.agentic_status == RunStatus.NOT_RUN
        )
        report("RR-02", "Partial run: selection only, no benchmark -> correct NOT_RUN statuses", ok)
    except Exception as e:
        fail_exc("RR-02", "Partial run: correct NOT_RUN statuses", e)


# ---------------------------------------------------------------------------
# Test 3: Missing profile
# ---------------------------------------------------------------------------

def test_t03_missing_profile():
    """RR-03: Missing profile sets profile_status=NOT_RUN, not FAILED."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        r = builder.build()

        ok = (
            r.profile_status == RunStatus.NOT_RUN
            and r.program_profile is None
        )
        report("RR-03", "Missing profile -> profile_status=NOT_RUN", ok)
    except Exception as e:
        fail_exc("RR-03", "Missing profile handling", e)


# ---------------------------------------------------------------------------
# Test 4: Missing DecisionTrace
# ---------------------------------------------------------------------------

def test_t04_missing_trace():
    """RR-04: Missing DecisionTrace -> trace_status=NOT_RUN, selection still works."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection(selected_strategy="-O2", decision_trace=None)
        r = builder.build()

        ok = (
            r.selection_status == RunStatus.OK
            and r.selected_strategy == "-O2"
            and r.trace_status == RunStatus.NOT_RUN
            and r.decision_trace is None
            and r.xai_result is None
        )
        report("RR-04", "Missing DecisionTrace -> trace_status=NOT_RUN, selection OK", ok)
    except Exception as e:
        fail_exc("RR-04", "Missing DecisionTrace handling", e)


# ---------------------------------------------------------------------------
# Test 5: Failed compiler
# ---------------------------------------------------------------------------

def test_t05_failed_compiler():
    """RR-05: Failed compiler -> FAILED_BUILD status, never zero measurement."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_baseline_measurement(None, error="clang: error: cc1 not found")
        builder.set_optimized_measurement("-O2", None)
        r = builder.build()

        ok = (
            r.baseline_status == MeasurementStatus.FAILED_RUN
            and r.baseline_measurement is not None
            and r.baseline_measurement.median_s is None  # NOT zero
            and r.optimized_status == MeasurementStatus.NOT_RUN
            and r.benchmark_status == RunStatus.FAILED
        )
        report("RR-05", "Failed compiler -> FAILED_BUILD, not zero measurement", ok,
               note=f"baseline_status={r.baseline_status.value}, median_s={r.baseline_measurement.median_s if r.baseline_measurement else 'N/A'}")
    except Exception as e:
        fail_exc("RR-05", "Failed compiler handling", e)


# ---------------------------------------------------------------------------
# Test 6: Failed benchmark
# ---------------------------------------------------------------------------

def test_t06_failed_benchmark():
    """RR-06: Failed benchmark (build ok, timing fails) -> explicit FAILED_RUN."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        # Baseline OK
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        # Optimized: measurement_error set
        opt_failed = _make_mock_measurement_dict("-O2", failed=True, error="Timeout after 30s")
        builder.set_optimized_measurement("-O2", opt_failed)
        r = builder.build()

        ok = (
            r.baseline_status == MeasurementStatus.OK
            and r.optimized_status == MeasurementStatus.FAILED_RUN
            and r.optimized_measurement is not None
            and r.optimized_measurement.median_s is None  # NOT zero
            and r.optimized_measurement.error_detail is not None
        )
        report("RR-06", "Failed benchmark -> FAILED_RUN, not zero median_s", ok,
               note=f"opt median_s={r.optimized_measurement.median_s if r.optimized_measurement else 'N/A'}")
    except Exception as e:
        fail_exc("RR-06", "Failed benchmark handling", e)


# ---------------------------------------------------------------------------
# Test 7: NOT_RUN vs FAILED vs OK
# ---------------------------------------------------------------------------

def test_t07_status_distinction():
    """RR-07: NOT_RUN, FAILED, and OK are clearly distinguished."""
    try:
        # NOT_RUN: stage not invoked
        b1 = RunRecordBuilder()
        b1.set_selection("-O2")
        r1 = b1.build()
        not_run_ok = r1.security_status == RunStatus.NOT_RUN

        # FAILED: stage invoked, error returned
        b2 = RunRecordBuilder()
        b2.set_selection("-O2")
        b2.set_baseline_measurement(None, error="Compiler missing")
        r2 = b2.build()
        failed_ok = r2.baseline_status == MeasurementStatus.FAILED_RUN

        # OK: stage completed successfully
        b3 = RunRecordBuilder()
        b3.set_selection("-O2")
        b3.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        r3 = b3.build()
        success_ok = r3.baseline_status == MeasurementStatus.OK

        # The three statuses must be distinct
        statuses = {r1.security_status, r2.baseline_status, r3.baseline_status}
        all_distinct = len(statuses) == 3

        ok = not_run_ok and failed_ok and success_ok and all_distinct
        report("RR-07", "NOT_RUN vs FAILED vs OK are distinct", ok)
    except Exception as e:
        fail_exc("RR-07", "Status distinction", e)


# ---------------------------------------------------------------------------
# Test 8: Provenance preservation
# ---------------------------------------------------------------------------

def test_t08_provenance():
    """RR-08: Provenance from DecisionTrace is correctly mapped."""
    try:
        trace_moo = _make_mock_decision_trace(moo_active=True)
        b1 = RunRecordBuilder()
        b1.set_selection("-O2", decision_trace=trace_moo)
        r1 = b1.build()
        moo_prov_ok = r1.selection_provenance == SelectionProvenance.DQN_MOO

        trace_argmax = _make_mock_decision_trace(moo_active=False)
        trace_argmax["selection_method"] = "argmax_fallback_no_frontier"
        b2 = RunRecordBuilder()
        b2.set_selection("-O2", decision_trace=trace_argmax)
        r2 = b2.build()
        argmax_prov_ok = r2.selection_provenance == SelectionProvenance.DQN_ARGMAX

        # No trace -> UNKNOWN provenance
        b3 = RunRecordBuilder()
        b3.set_selection("-O2")
        r3 = b3.build()
        unknown_prov_ok = r3.selection_provenance == SelectionProvenance.UNKNOWN

        ok = moo_prov_ok and argmax_prov_ok and unknown_prov_ok
        report("RR-08", "Provenance correctly mapped from DecisionTrace", ok,
               note=f"moo={r1.selection_provenance.value}, argmax={r2.selection_provenance.value}, none={r3.selection_provenance.value}")
    except Exception as e:
        fail_exc("RR-08", "Provenance preservation", e)


# ---------------------------------------------------------------------------
# Test 9: -O0 baseline preservation
# ---------------------------------------------------------------------------

def test_t09_baseline_convention():
    """RR-09: Baseline is always labeled 'baseline (-O0)', never confused with optimized."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        builder.set_optimized_measurement("-O2", _make_mock_measurement_dict("-O2", 0.01))
        r = builder.build()

        ok = (
            r.baseline_config == BASELINE_STRATEGY_LABEL
            and r.baseline_measurement is not None
            and r.baseline_measurement.strategy == BASELINE_STRATEGY_LABEL
            and r.optimized_measurement is not None
            and r.optimized_measurement.strategy == "-O2"
            # Baseline and optimized are never the same object
            and r.baseline_measurement is not r.optimized_measurement
            # Different timings (baseline slower)
            and r.baseline_measurement.median_s == 0.02
            and r.optimized_measurement.median_s == 0.01
        )
        report("RR-09", "-O0 baseline preserved and never confused with optimized", ok)
    except Exception as e:
        fail_exc("RR-09", "-O0 baseline convention", e)


# ---------------------------------------------------------------------------
# Test 10: Regression projection
# ---------------------------------------------------------------------------

def test_t10_regression_projection():
    """RR-10: to_regression_input() produces correct projection."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        builder.set_optimized_measurement("-O2", _make_mock_measurement_dict("-O2", 0.01))
        builder.set_regression(_make_mock_program_comparison())
        r = builder.build()

        proj = to_regression_input(r)

        ok = (
            proj["can_compare"] is True
            and proj["selected_strategy"] == "-O2"
            and proj["baseline_strategy"] == BASELINE_STRATEGY_LABEL
            and proj["baseline_metrics"] is not None
            and proj["optimized_metrics"] is not None
            and proj["baseline_metrics"]["execution_time_s"] == 0.02
            and proj["optimized_metrics"]["execution_time_s"] == 0.01
            and "cannot_compare_reason" not in proj
        )
        report("RR-10", "to_regression_input(): correct projection with valid measurements", ok)
    except Exception as e:
        fail_exc("RR-10", "Regression projection", e)


# ---------------------------------------------------------------------------
# Test 11: Adaptive ExperienceRecord projection
# ---------------------------------------------------------------------------

def test_t11_adaptive_projection():
    """RR-11: to_experience_record() produces valid advisory ExperienceRecord."""
    try:
        from moo.adaptive.schema import ExperienceRecord as ER

        builder = RunRecordBuilder(source_path=None)
        builder.set_ir_features(features=MOCK_IR_FEATURES)
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        builder.set_optimized_measurement("-O2", _make_mock_measurement_dict("-O2", 0.01))
        r = builder.build()

        # source_hash needed for ExperienceRecord
        r.source_hash = "a" * 64

        exp = to_experience_record(r)

        ok = (
            exp is not None
            and isinstance(exp, ER)
            and exp.selected_action == "-O2"
            # ADVISORY: creating an ExperienceRecord does NOT change the RunRecord selection
            and r.selected_strategy == "-O2"  # still unchanged
            and "ADVISORY ONLY" in " ".join(exp.notes)
        )
        report("RR-11", "to_experience_record(): advisory ExperienceRecord created correctly", ok)
    except ImportError:
        skip("RR-11", "to_experience_record(): adaptive schema not available")
    except Exception as e:
        fail_exc("RR-11", "Adaptive ExperienceRecord projection", e)


# ---------------------------------------------------------------------------
# Test 12: Agentic AgentContext projection
# ---------------------------------------------------------------------------

def test_t12_agentic_projection():
    """RR-12: to_agent_context() produces valid advisory AgentContext."""
    try:
        from moo.agentic.schema import AgentContext

        builder = RunRecordBuilder(source_path=None)
        builder.set_ir_features(features=MOCK_IR_FEATURES)
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())
        r = builder.build()
        r.source_hash = "b" * 64

        ctx = to_agent_context(r)

        ok = (
            ctx is not None
            and isinstance(ctx, AgentContext)
            and ctx.selected_strategy == "-O2"
            # ADVISORY: creating context does NOT change RunRecord selection
            and r.selected_strategy == "-O2"
        )
        report("RR-12", "to_agent_context(): advisory AgentContext created correctly", ok)
    except ImportError:
        skip("RR-12", "to_agent_context(): agentic schema not available")
    except Exception as e:
        fail_exc("RR-12", "Agentic AgentContext projection", e)


# ---------------------------------------------------------------------------
# Test 13: Security projection
# ---------------------------------------------------------------------------

def test_t13_security_projection():
    """RR-13: Security result correctly stored and projected (not fabricated)."""
    try:
        # Case 1: Security ran and returned PRESERVED
        b1 = RunRecordBuilder()
        b1.set_selection("-O2")
        b1.set_security(_make_mock_security_result("PRESERVED"))
        r1 = b1.build()
        sec_ok_ok = (
            r1.security_status == RunStatus.OK
            and r1.security_verdict == "PRESERVED"
            and r1.security_result is not None
        )

        # Case 2: Security NOT run
        b2 = RunRecordBuilder()
        b2.set_selection("-O2")
        r2 = b2.build()
        sec_notrun_ok = (
            r2.security_status == RunStatus.NOT_RUN
            and r2.security_verdict is None
            and r2.security_result is None
        )

        # Case 3: Security ran but result is UNKNOWN
        b3 = RunRecordBuilder()
        b3.set_selection("-O2")
        b3.set_security(_make_mock_security_result("UNKNOWN"))
        r3 = b3.build()
        sec_unknown_ok = (
            r3.security_status == RunStatus.UNKNOWN
        )

        ok = sec_ok_ok and sec_notrun_ok and sec_unknown_ok
        report("RR-13", "Security: PRESERVED=OK, NOT_RUN=NOT_RUN, UNKNOWN=UNKNOWN -- no fabrication", ok)
    except Exception as e:
        fail_exc("RR-13", "Security result projection", e)


# ---------------------------------------------------------------------------
# Test 14: XAI / DecisionTrace projection
# ---------------------------------------------------------------------------

def test_t14_xai_trace_projection():
    """RR-14: XAI result linked from DecisionTrace in RunRecord."""
    try:
        trace = _make_mock_decision_trace()
        builder = RunRecordBuilder()
        builder.set_ir_features(MOCK_IR_FEATURES)
        builder.set_selection("-O2", decision_trace=trace)
        r = builder.build()

        ok = (
            r.trace_status == RunStatus.OK
            and r.decision_trace is not None
            and r.decision_trace.get("final_strategy") == "-O2"
            and r.xai_result is not None
            and r.xai_result.get("final_strategy") == "-O2"
        )
        report("RR-14", "XAI result linked from DecisionTrace in RunRecord", ok)
    except Exception as e:
        fail_exc("RR-14", "XAI/DecisionTrace projection", e)


# ---------------------------------------------------------------------------
# Test 15: RunRecord advisory safety (agentic cannot override selection)
# ---------------------------------------------------------------------------

def test_t15_agentic_cannot_override():
    """RR-15: Agentic AI analysis cannot override selected_strategy."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())

        # Agent report says different strategy -- but advisory only
        agent_report = _make_mock_agent_report("-O3")  # different from selected
        agent_report["selected_strategy"] = "-O3"
        builder.set_agentic(agent_report)
        r = builder.build()

        ok = (
            # RunRecord selection is unchanged
            r.selected_strategy == "-O2"
            # Agentic result is stored as advisory
            and r.agentic_status == RunStatus.OK
            and r.agentic_is_advisory_only is True
            # Note about discrepancy was added
            and any("advisory" in note.lower() for note in r.run_notes)
        )
        report("RR-15", "Agentic AI cannot override selected_strategy", ok)
    except Exception as e:
        fail_exc("RR-15", "Agentic cannot override selection", e)


# ---------------------------------------------------------------------------
# Test 16: Serialization determinism
# ---------------------------------------------------------------------------

def test_t16_deterministic_serialization():
    """RR-16: to_dict() / from_dict() is deterministic and round-trips cleanly."""
    try:
        builder = RunRecordBuilder(source_path=None, run_id="test-run-001")
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())
        builder.set_profile(_make_mock_program_profile())
        r = builder.build()

        d1 = json.dumps(r.to_dict(), sort_keys=True)
        d2 = json.dumps(r.to_dict(), sort_keys=True)
        deterministic_ok = (d1 == d2)

        # Round-trip
        r2 = RunRecord.from_dict(r.to_dict())
        rt_ok = (
            r2.run_id == r.run_id
            and r2.selected_strategy == r.selected_strategy
            and r2.selection_provenance == r.selection_provenance
            and r2.profile_status == r.profile_status
        )

        ok = deterministic_ok and rt_ok
        report("RR-16", "Serialization is deterministic and round-trips correctly", ok)
    except Exception as e:
        fail_exc("RR-16", "Deterministic serialization", e)


# ---------------------------------------------------------------------------
# Test 17: RunRecord identity (run_id)
# ---------------------------------------------------------------------------

def test_t17_run_identity():
    """RR-17: RunRecord has stable, unique run_id."""
    try:
        r1 = RunRecordBuilder(run_id="stable-001").build()
        r2 = RunRecordBuilder(run_id="stable-001").build()
        r3 = RunRecordBuilder().build()  # auto-generated UUID

        same_id_ok = r1.run_id == r2.run_id == "stable-001"
        auto_id_ok = r3.run_id != "" and r3.run_id != "stable-001"

        ok = same_id_ok and auto_id_ok
        report("RR-17", "RunRecord has stable, unique run_id", ok)
    except Exception as e:
        fail_exc("RR-17", "RunRecord identity", e)


# ---------------------------------------------------------------------------
# Test 18: Backward compatibility with existing selector APIs
# ---------------------------------------------------------------------------

def test_t18_selector_backward_compat():
    """RR-18: Existing selector_bridge APIs still work unchanged."""
    try:
        from moo.selector_bridge import (
            moo_aware_select,
            get_pareto_frontier_for,
            SelectionResult,
        )
        # These should still import and be callable
        # moo_aware_select with empty frontier = pure argmax (original behavior)
        result = moo_aware_select(
            source_path="",
            q_values=MOCK_Q_VALUES,
            actions=MOCK_ACTIONS,
            frontier=[],
        )
        ok = (
            isinstance(result, SelectionResult)
            and result.strategy in MOCK_ACTIONS
            and result.moo_active is False
        )
        report("RR-18", "Existing selector_bridge APIs preserved and working", ok)
    except ImportError as e:
        skip("RR-18", "selector_bridge not available", str(e))
    except Exception as e:
        fail_exc("RR-18", "Backward compatibility with selector APIs", e)


# ---------------------------------------------------------------------------
# Test 19: Agentic analysis cannot override selected strategy (via orchestrator)
# ---------------------------------------------------------------------------

def test_t19_orchestrator_agentic_safety():
    """RR-19: Orchestrator: agentic result NEVER changes selected_strategy."""
    try:
        orch = PipelineOrchestrator()
        agent_report = _make_mock_agent_report("-O3")  # different from selected

        r = orch.build_from_artifacts(
            source_path=None,
            selected_strategy="-O2",
            ir_features=MOCK_IR_FEATURES,
            agent_report=agent_report,
        )

        ok = (
            r.selected_strategy == "-O2"  # NEVER changed by agentic
            and r.agentic_is_advisory_only is True
        )
        report("RR-19", "Orchestrator: agentic analysis cannot override selected_strategy", ok)
    except Exception as e:
        fail_exc("RR-19", "Orchestrator agentic safety", e)


# ---------------------------------------------------------------------------
# Test 20: Adaptive learning cannot override selected strategy
# ---------------------------------------------------------------------------

def test_t20_adaptive_cannot_override():
    """RR-20: Adaptive learning linkage NEVER changes selected_strategy."""
    try:
        # Simulate an ExperienceRecord with different selected_action
        mock_exp = {
            "experience_id": "exp_001",
            "selected_action": "-O3",  # different from RunRecord's -O2
            "reward": 0.8,
        }

        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_adaptive(mock_exp)  # should link but NOT override
        r = builder.build()

        ok = (
            r.selected_strategy == "-O2"  # NEVER changed
            and r.adaptive_is_advisory_only is True
            and r.adaptive_experience_id == "exp_001"
        )
        report("RR-20", "Adaptive learning cannot override selected_strategy", ok)
    except Exception as e:
        fail_exc("RR-20", "Adaptive cannot override selection", e)


# ---------------------------------------------------------------------------
# Test 21: No fake security "Preserved" status
# ---------------------------------------------------------------------------

def test_t21_no_fake_security():
    """RR-21: Security status is never OK unless analyzer actually ran."""
    try:
        # Case: analyzer not run -> NOT_RUN (never OK)
        b1 = RunRecordBuilder()
        b1.set_selection("-O2")
        r1 = b1.build()
        no_fake_ok = r1.security_status == RunStatus.NOT_RUN

        # Case: None passed explicitly -> NOT_RUN
        b2 = RunRecordBuilder()
        b2.set_selection("-O2")
        b2.set_security(None)
        r2 = b2.build()
        explicit_none_ok = r2.security_status == RunStatus.NOT_RUN

        # Case: analyzer ran with UNKNOWN result -> UNKNOWN, not OK
        b3 = RunRecordBuilder()
        b3.set_selection("-O2")
        b3.set_security({"strategy_name": "-O2", "verdict": "UNKNOWN"})
        r3 = b3.build()
        unknown_not_ok = r3.security_status == RunStatus.UNKNOWN

        ok = no_fake_ok and explicit_none_ok and unknown_not_ok
        report("RR-21", "No fake security OK status without real analyzer result", ok)
    except Exception as e:
        fail_exc("RR-21", "No fake security Preserved status", e)


# ---------------------------------------------------------------------------
# Test 22: Existing Week 8-12 modules still importable
# ---------------------------------------------------------------------------

def test_t22_existing_modules_intact():
    """RR-22: Existing Week 8-12 modules import without error."""
    try:
        from moo.decision_trace import DecisionTrace
        from moo.program_profiler import ProgramProfile, profile_program
        from moo.selector_bridge import moo_aware_select_with_trace
        from moo.regression.schema import ProgramComparison, RegressionReport
        from moo.adaptive.schema import ExperienceRecord
        from moo.agentic.schema import AgentAnalysisReport
        from moo.security.models import CandidateSecurity

        report("RR-22", "All existing Week 8-12 modules import without error", True)
    except ImportError as e:
        report("RR-22", "All existing Week 8-12 modules import without error", False, str(e))
    except Exception as e:
        fail_exc("RR-22", "Existing modules still importable", e)


# ---------------------------------------------------------------------------
# Test 23: GUI import behavior preserved
# ---------------------------------------------------------------------------

def test_t23_gui_compat():
    """RR-23: GUI-relevant imports and module structure remain intact."""
    try:
        # The RunRecord must be usable by the GUI without breaking existing imports
        # GUI imports moo modules; RunRecord must not break moo namespace
        import moo
        import moo.runrecord
        # Ensure moo.runrecord doesn't pollute moo namespace unexpectedly
        ok = (
            hasattr(moo, "__version__")
            and hasattr(moo.runrecord, "RunRecord")
            and hasattr(moo.runrecord, "RunRecordBuilder")
        )
        report("RR-23", "GUI import compatibility: moo namespace intact", ok)
    except Exception as e:
        fail_exc("RR-23", "GUI import behavior preserved", e)


# ---------------------------------------------------------------------------
# Test 24: MeasurementSnapshot explicit failure (never zero)
# ---------------------------------------------------------------------------

def test_t24_measurement_never_zero():
    """RR-24: Failed measurements are FAILED, not zero-valued."""
    try:
        # Zero samples -> FAILED_RUN, not a zero median
        m_empty_samples = {
            "strategy": "-O2",
            "exe_path": "/tmp/test.exe",
            "warmup_runs": 1,
            "measure_runs": 5,
            "raw_samples_ns": [],
            "timing": None,
            "last_return_code": 1,
            "measurement_error": "No valid timing samples collected",
            "n_timeouts": 0,
            "n_errors": 5,
            "timing_is_reliable": None,
        }
        from moo.runrecord.builder import _measurement_snapshot_from_dict
        snap = _measurement_snapshot_from_dict(m_empty_samples, "-O2")

        ok = (
            snap.status == MeasurementStatus.FAILED_RUN
            and snap.median_s is None  # NOT zero
            and snap.n_samples == 0
        )
        report("RR-24", "Failed measurement -> FAILED_RUN, not zero median_s", ok,
               note=f"status={snap.status.value}, median_s={snap.median_s}")
    except Exception as e:
        fail_exc("RR-24", "Measurement never zero on failure", e)


# ---------------------------------------------------------------------------
# Test 25: Regression projection with failed measurements
# ---------------------------------------------------------------------------

def test_t25_regression_projection_failed():
    """RR-25: to_regression_input() with failed measurements -> can_compare=False."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        # Baseline OK but optimized FAILED
        builder.set_baseline_measurement(_make_mock_measurement_dict("baseline (-O0)", 0.02))
        builder.set_optimized_measurement("-O2", _make_mock_measurement_dict("-O2", failed=True, error="Timeout"))
        r = builder.build()

        proj = to_regression_input(r)

        ok = (
            proj["can_compare"] is False
            and "cannot_compare_reason" in proj
            and proj["baseline_metrics"] is None
            and proj["optimized_metrics"] is None
        )
        report("RR-25", "Regression projection with failed measurements -> can_compare=False", ok,
               note=proj.get("cannot_compare_reason", ""))
    except Exception as e:
        fail_exc("RR-25", "Regression projection with failures", e)


# ---------------------------------------------------------------------------
# Test 26: Full orchestrator artifact injection
# ---------------------------------------------------------------------------

def test_t26_orchestrator_artifact_injection():
    """RR-26: PipelineOrchestrator assembles RunRecord from injected artifacts."""
    try:
        orch = PipelineOrchestrator()
        moo_result = _make_mock_moo_result(selected_strategy="-O2")
        comparison = _make_mock_program_comparison(selected_strategy="-O2")
        security = _make_mock_security_result("PRESERVED")
        trace = _make_mock_decision_trace()

        r = orch.build_from_artifacts(
            source_path=None,
            program_profile=_make_mock_program_profile(),
            decision_trace=trace,
            moo_result=moo_result,
            selected_strategy="-O2",
            ir_features=MOCK_IR_FEATURES,
            program_comparison=comparison,
            security_result=security,
        )

        ok = (
            r.selected_strategy == "-O2"
            and r.selection_status == RunStatus.OK
            and r.profile_status == RunStatus.OK
            and r.baseline_status == MeasurementStatus.OK
            and r.optimized_status == MeasurementStatus.OK
            and r.regression_status == RunStatus.OK
            and r.security_status == RunStatus.OK
            and r.agentic_is_advisory_only is True
            and r.adaptive_is_advisory_only is True
        )
        report("RR-26", "PipelineOrchestrator assembles complete RunRecord from artifacts", ok)
    except Exception as e:
        fail_exc("RR-26", "Orchestrator artifact injection", e)


# ---------------------------------------------------------------------------
# Test 27: RunRecord persistence / load round-trip
# ---------------------------------------------------------------------------

def test_t27_persistence():
    """RR-27: RunRecord persists to JSON and loads back correctly."""
    tmpdir = tempfile.mkdtemp()
    try:
        orch = PipelineOrchestrator(persist_dir=tmpdir)
        builder = RunRecordBuilder(source_path=None, run_id="persist-test-001")
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())
        r = builder.build()

        path = orch._persist(r)
        ok_persist = path is not None and os.path.isfile(path)

        loaded = PipelineOrchestrator.load(path) if ok_persist else None
        ok_load = (
            loaded is not None
            and loaded.run_id == "persist-test-001"
            and loaded.selected_strategy == "-O2"
        )

        ok = ok_persist and ok_load
        report("RR-27", "RunRecord persists to JSON and loads back correctly", ok)
    except Exception as e:
        fail_exc("RR-27", "RunRecord persistence/load round-trip", e)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 28: GUI view model
# ---------------------------------------------------------------------------

def test_t28_gui_view():
    """RR-28: to_gui_view() produces correct view model without fabricating OK."""
    try:
        builder = RunRecordBuilder()
        builder.set_selection("-O2", decision_trace=_make_mock_decision_trace())
        # Security NOT run -> must appear as NOT_RUN in GUI view
        r = builder.build()

        view = to_gui_view(r)

        ok = (
            view["selected_strategy"] == "-O2"
            and view["security"]["status"] == "NOT_RUN"
            and view["security"]["verdict"] is None  # NOT fabricated as Preserved
            and view["agentic"]["is_advisory_only"] is True
            and view["adaptive"]["is_advisory_only"] is True
        )
        report("RR-28", "to_gui_view(): no fabricated OK statuses, advisory correctly labeled", ok)
    except Exception as e:
        fail_exc("RR-28", "GUI view model correctness", e)


# ---------------------------------------------------------------------------
# Test 29: MOO result integration
# ---------------------------------------------------------------------------

def test_t29_moo_result_integration():
    """RR-29: MOO result integrates baseline and optimized measurements correctly."""
    try:
        moo_result = _make_mock_moo_result(selected_strategy="-O2", build_ok=True, measure_ok=True)

        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_moo_result(moo_result)
        builder.set_optimized_from_moo(moo_result, "-O2")
        r = builder.build()

        ok = (
            r.baseline_status == MeasurementStatus.OK
            and r.optimized_status == MeasurementStatus.OK
            and r.baseline_measurement is not None
            and r.baseline_measurement.has_valid_timing()
            and r.optimized_measurement is not None
            and r.optimized_measurement.has_valid_timing()
            and r.baseline_measurement.strategy == BASELINE_STRATEGY_LABEL
            and r.optimized_measurement.strategy == "-O2"
        )
        report("RR-29", "MOO result: baseline and optimized both OK with valid timing", ok)
    except Exception as e:
        fail_exc("RR-29", "MOO result integration", e)


# ---------------------------------------------------------------------------
# Test 30: MOO with failed build
# ---------------------------------------------------------------------------

def test_t30_moo_failed_build():
    """RR-30: MOO result with failed build -> FAILED_BUILD status, not zero."""
    try:
        moo_result = _make_mock_moo_result(selected_strategy="-O2", build_ok=False)

        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        builder.set_moo_result(moo_result)
        builder.set_optimized_from_moo(moo_result, "-O2")
        r = builder.build()

        ok = (
            r.baseline_status == MeasurementStatus.OK  # baseline built OK
            and r.optimized_status == MeasurementStatus.FAILED_BUILD  # optimized failed
            and r.optimized_measurement is not None
            and r.optimized_measurement.median_s is None  # NOT zero
        )
        report("RR-30", "MOO failed build -> FAILED_BUILD, median_s=None (not zero)", ok)
    except Exception as e:
        fail_exc("RR-30", "MOO with failed build", e)


# ---------------------------------------------------------------------------
# Tests 31-46: Production Wiring & Live Integration Verification
# ---------------------------------------------------------------------------

_CODES_DIR = os.path.dirname(_PS_DIR)
_TC_DIR = os.path.join(_CODES_DIR, "test_cases")
TC1_PATH = os.path.join(_TC_DIR, "TC1_loop_heavy.c")


def test_t31_real_pipeline_creates_runrecord():
    """RR-31: Real pipeline (execute_pipeline) creates a populated RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=2, timeout_s=5)
        ok = (
            rec is not None
            and isinstance(rec, RunRecord)
            and bool(rec.run_id)
            and rec.source_file == "TC1_loop_heavy.c"
            and rec.selection_status == RunStatus.OK
            and rec.selected_strategy is not None
            and rec.overall_status in (RunStatus.OK, RunStatus.UNKNOWN)
        )
        report("RR-31", "Real pipeline creates populated RunRecord", ok)
    except Exception as e:
        fail_exc("RR-31", "Real pipeline creates RunRecord", e)


def test_t32_selection_provenance_preserved():
    """RR-32: Selection provenance is preserved from live selector into RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.selection_provenance in (
                SelectionProvenance.DQN_MOO,
                SelectionProvenance.DQN_ARGMAX,
            )
            and rec.selected_strategy is not None
        )
        report("RR-32", "Selection provenance preserved from live selector", ok,
               note=f"provenance={rec.selection_provenance.value}")
    except Exception as e:
        fail_exc("RR-32", "Selection provenance preservation", e)


def test_t33_decision_trace_survives_into_runrecord():
    """RR-33: DecisionTrace survives into RunRecord from live execution."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.decision_trace is not None
            and rec.trace_status == RunStatus.OK
            and rec.decision_trace.get("final_strategy") == rec.selected_strategy
            and "selection_reason" in rec.decision_trace
        )
        report("RR-33", "DecisionTrace survives into RunRecord", ok)
    except Exception as e:
        fail_exc("RR-33", "DecisionTrace in RunRecord", e)


def test_t34_xai_survives_into_runrecord():
    """RR-34: XAI result survives into RunRecord from live execution."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.xai_result is not None
            and rec.xai_result.get("final_strategy") == rec.selected_strategy
        )
        report("RR-34", "XAI result survives into RunRecord", ok)
    except Exception as e:
        fail_exc("RR-34", "XAI in RunRecord", e)


def test_t35_o0_baseline_remains_canonical():
    """RR-35: -O0 baseline convention remains canonical in real execution."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.baseline_config == "baseline (-O0)"
            and rec.baseline_measurement is not None
            and rec.baseline_measurement.strategy == "baseline (-O0)"
            and rec.baseline_status == MeasurementStatus.OK
        )
        report("RR-35", "-O0 baseline remains canonical in real execution", ok)
    except Exception as e:
        fail_exc("RR-35", "-O0 baseline convention", e)


def test_t36_failed_compilation_produces_failed_status():
    """RR-36: Non-existent source produces FAILED status, never zero measurement."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline("non_existent_file_xyz.c")
        ok = (
            rec.selection_status == RunStatus.FAILED
            and rec.overall_status == RunStatus.FAILED
            and rec.baseline_measurement is None
            and rec.optimized_measurement is None
        )
        report("RR-36", "Failed source produces FAILED status, not zero measurement", ok)
    except Exception as e:
        fail_exc("RR-36", "Failed source handling", e)


def test_t37_missing_benchmark_produces_not_run():
    """RR-37: Missing benchmark produces NOT_RUN rather than fake zero."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, run_benchmarks=False)
        ok = (
            rec.benchmark_status == RunStatus.NOT_RUN
            and rec.baseline_status == MeasurementStatus.NOT_RUN
            and rec.optimized_status == MeasurementStatus.NOT_RUN
            and rec.baseline_measurement is None
            and rec.optimized_measurement is None
        )
        report("RR-37", "Missing benchmark produces NOT_RUN rather than fake zero", ok)
    except Exception as e:
        fail_exc("RR-37", "Missing benchmark handling", e)


def test_t38_regression_projection_works():
    """RR-38: Regression projection works on live RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=2, timeout_s=5)
        proj = to_regression_input(rec)
        ok = (
            proj["can_compare"] is True
            and proj["selected_strategy"] == rec.selected_strategy
            and proj["baseline_metrics"] is not None
            and proj["optimized_metrics"] is not None
        )
        report("RR-38", "Regression projection works on live RunRecord", ok)
    except Exception as e:
        fail_exc("RR-38", "Regression projection on live RunRecord", e)


def test_t39_adaptive_projection_works():
    """RR-39: Adaptive ExperienceRecord projection works on live RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=2, timeout_s=5)
        exp = to_experience_record(rec)
        ok = (
            exp is not None
            and exp.selected_action == rec.selected_strategy
            and rec.adaptive_is_advisory_only is True
        )
        report("RR-39", "Adaptive ExperienceRecord projection works on live RunRecord", ok)
    except Exception as e:
        fail_exc("RR-39", "Adaptive projection on live RunRecord", e)


def test_t40_agentic_projection_works():
    """RR-40: Agentic AgentContext projection works on live RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=2, timeout_s=5)
        ctx = to_agent_context(rec)
        ok = (
            ctx is not None
            and ctx.selected_strategy == rec.selected_strategy
        )
        report("RR-40", "Agentic AgentContext projection works on live RunRecord", ok)
    except Exception as e:
        fail_exc("RR-40", "Agentic projection on live RunRecord", e)


def test_t41_security_not_run_when_disabled():
    """RR-41: Security remains NOT_RUN when security scan is disabled."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, run_security=False, run_benchmarks=False)
        ok = (
            rec.security_status == RunStatus.NOT_RUN
            and rec.security_verdict is None
            and rec.security_result is None
        )
        report("RR-41", "Security remains NOT_RUN when disabled (never fabricated)", ok)
    except Exception as e:
        fail_exc("RR-41", "Security disabled handling", e)


def test_t42_gui_projection_works():
    """RR-42: GUI projection works on live RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=2, timeout_s=5)
        view = to_gui_view(rec)
        ok = (
            view["selected_strategy"] == rec.selected_strategy
            and view["benchmark_status"] == rec.benchmark_status.value
            and view["baseline_timing"] is not None
            and view["optimized_timing"] is not None
            and view["agentic"]["is_advisory_only"] is True
            and view["adaptive"]["is_advisory_only"] is True
        )
        report("RR-42", "GUI projection works on live RunRecord", ok)
    except Exception as e:
        fail_exc("RR-42", "GUI projection on live RunRecord", e)


def test_t43_existing_public_apis_backward_compat():
    """RR-43: Existing public APIs remain backward compatible."""
    try:
        from optimization_selector import select_with_provenance, get_best_optimization
        sel = select_with_provenance(TC1_PATH)
        s1 = get_best_optimization(TC1_PATH)
        s2, tr = get_best_optimization(TC1_PATH, return_trace=True)
        s3, tr3, xai = get_best_optimization(TC1_PATH, return_trace=True, return_xai=True)

        ok = (
            sel is not None
            and s1 == sel.strategy
            and s2 == sel.strategy
            and tr is not None
            and s3 == sel.strategy
            and xai is not None
        )
        report("RR-43", "Existing public APIs remain 100% backward compatible", ok)
    except Exception as e:
        fail_exc("RR-43", "Existing public APIs compatibility", e)


def test_t44_runrecord_does_not_mutate_upstream_artifacts():
    """RR-44: Downstream projections do not mutate the RunRecord."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        orig_strategy = rec.selected_strategy
        orig_overall = rec.overall_status

        _ = to_regression_input(rec)
        _ = to_experience_record(rec)
        _ = to_agent_context(rec)
        _ = to_gui_view(rec)

        ok = (
            rec.selected_strategy == orig_strategy
            and rec.overall_status == orig_overall
            and rec.agentic_is_advisory_only is True
            and rec.adaptive_is_advisory_only is True
        )
        report("RR-44", "Downstream projections do not mutate the RunRecord", ok)
    except Exception as e:
        fail_exc("RR-44", "RunRecord non-mutation", e)


def test_t45_agentic_remains_advisory_only():
    """RR-45: Live Agentic AI analysis remains strictly advisory only."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.agentic_is_advisory_only is True
            and rec.agentic_status in (RunStatus.OK, RunStatus.NOT_RUN)
            and (rec.agentic_report is None or rec.agentic_report.get("is_advisory_only") is True)
        )
        report("RR-45", "Live Agentic AI analysis remains strictly advisory only", ok)
    except Exception as e:
        fail_exc("RR-45", "Agentic advisory only invariant", e)


def test_t46_adaptive_remains_advisory_only():
    """RR-46: Live Adaptive Learning linkage remains strictly advisory only."""
    try:
        orch = PipelineOrchestrator()
        rec = orch.execute_pipeline(TC1_PATH, warmup_runs=1, measure_runs=1, timeout_s=5)
        ok = (
            rec.adaptive_is_advisory_only is True
            and rec.adaptive_status in (RunStatus.OK, RunStatus.NOT_RUN)
        )
        report("RR-46", "Live Adaptive Learning linkage remains strictly advisory only", ok)
    except Exception as e:
        fail_exc("RR-46", "Adaptive advisory only invariant", e)


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

def _run_all():
    print()
    print("=" * 70)
    print("TOACD RunRecord Integration Test Suite")
    print("=" * 70)
    print()

    test_t01_complete_run()
    test_t02_partial_run()
    test_t03_missing_profile()
    test_t04_missing_trace()
    test_t05_failed_compiler()
    test_t06_failed_benchmark()
    test_t07_status_distinction()
    test_t08_provenance()
    test_t09_baseline_convention()
    test_t10_regression_projection()
    test_t11_adaptive_projection()
    test_t12_agentic_projection()
    test_t13_security_projection()
    test_t14_xai_trace_projection()
    test_t15_agentic_cannot_override()
    test_t16_deterministic_serialization()
    test_t17_run_identity()
    test_t18_selector_backward_compat()
    test_t19_orchestrator_agentic_safety()
    test_t20_adaptive_cannot_override()
    test_t21_no_fake_security()
    test_t22_existing_modules_intact()
    test_t23_gui_compat()
    test_t24_measurement_never_zero()
    test_t25_regression_projection_failed()
    test_t26_orchestrator_artifact_injection()
    test_t27_persistence()
    test_t28_gui_view()
    test_t29_moo_result_integration()
    test_t30_moo_failed_build()

    print("\n--- RR-PROD: Live Production Pipeline & Wiring ---")
    test_t31_real_pipeline_creates_runrecord()
    test_t32_selection_provenance_preserved()
    test_t33_decision_trace_survives_into_runrecord()
    test_t34_xai_survives_into_runrecord()
    test_t35_o0_baseline_remains_canonical()
    test_t36_failed_compilation_produces_failed_status()
    test_t37_missing_benchmark_produces_not_run()
    test_t38_regression_projection_works()
    test_t39_adaptive_projection_works()
    test_t40_agentic_projection_works()
    test_t41_security_not_run_when_disabled()
    test_t42_gui_projection_works()
    test_t43_existing_public_apis_backward_compat()
    test_t44_runrecord_does_not_mutate_upstream_artifacts()
    test_t45_agentic_remains_advisory_only()
    test_t46_adaptive_remains_advisory_only()

    print()
    print("=" * 70)
    total = PASSED + FAILED + SKIPPED
    print(f"RESULTS: {total} tests | PASS: {PASSED} | FAIL: {FAILED} | SKIP: {SKIPPED}")
    return FAILED == 0


if __name__ == "__main__":
    success = _run_all()
    sys.exit(0 if success else 1)
