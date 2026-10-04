"""
moo/tests/test_week10_regression.py — Week 10: Optimization Regression & Comparison Tests.

Test IDs follow the pattern W10-<CATEGORY><N>.

Categories:
  W10-SCHEMA  Data models, serialization, deserialization, schema versioning
  W10-COMP    Baseline vs selected comparison, strategy-vs-strategy comparison, direction correctness
  W10-REG     Regression, improvement, and unchanged detection with threshold semantics
  W10-HIST    Cross-run historical comparison, delta calculations, missing run handling
  W10-FAIL    Failure isolation, missing benchmarks/metrics, malformed/incomplete records
  W10-DET     Determinism across repeated calls, stable dictionary ordering
  W10-SCOPE   Scope guard verifying Week 11+ modules absent, UI untouched, selection logic unchanged
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_SCRIPT_DIR)
_PS_DIR = os.path.dirname(_MOO_DIR)

if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)

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
# Mock Helpers for Week 10 Testing
# ---------------------------------------------------------------------------

def _make_mock_record(
    pid: str = "test_prog",
    base_time: float = 0.100,
    base_size: int = 10000,
    base_energy: float = 4.5,
    base_carbon: float = 0.0005,
    candidates: list = None,
    frontier: list = None,
    status: str = "ok",
    pipeline_error: str = None,
) -> dict:
    """Build a mock ProgramRecord dict matching Week 9 schema."""
    if status != "ok":
        return {
            "schema_version": "week9.1.0",
            "run_id": "mock_run",
            "program_id": pid,
            "status": status,
            "pipeline_error": pipeline_error or "Simulated pipeline error",
            "baseline": None,
            "candidates": None,
            "pareto_frontier": [],
        }

    if candidates is None:
        candidates = [
            {
                "strategy_name": "-O2",
                "build_ok": True,
                "correct": True,
                "measurement": {
                    "timing": {"median_s": base_time * 0.8},
                    "code_size": {"primary_value": int(base_size * 0.9)},
                    "energy": {"energy_joules": base_energy * 0.8},
                    "carbon": {"carbon_grams": base_carbon * 0.8},
                },
                "pareto_status": "FRONTIER",
            },
            {
                "strategy_name": "-O3",
                "build_ok": True,
                "correct": True,
                "measurement": {
                    "timing": {"median_s": base_time * 1.1},  # regressed on time
                    "code_size": {"primary_value": int(base_size * 1.05)},
                    "energy": {"energy_joules": base_energy * 1.1},
                    "carbon": {"carbon_grams": base_carbon * 1.1},
                },
                "pareto_status": "DOMINATED",
            },
        ]

    return {
        "schema_version": "week9.1.0",
        "run_id": "mock_run",
        "program_id": pid,
        "status": "ok",
        "pipeline_error": None,
        "baseline": {
            "strategy_name": "baseline (-O0)",
            "measurement": {
                "timing": {"median_s": base_time},
                "code_size": {"primary_value": base_size},
                "energy": {"energy_joules": base_energy},
                "carbon": {"carbon_grams": base_carbon},
            },
        },
        "candidates": candidates,
        "pareto_frontier": frontier if frontier is not None else ["-O2"],
    }


# ===========================================================================
# W10-SCHEMA: Schema Model Validation
# ===========================================================================

def test_schema1_metric_comparison_roundtrip():
    """MetricComparison to_dict and from_dict round-trip preserves all fields."""
    tid, name = "W10-SCHEMA1", "MetricComparison to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import ComparisonStatus, MetricComparison
        mc = MetricComparison(
            metric_name="execution_time",
            baseline_value=0.100,
            target_value=0.080,
            delta=-0.020,
            percent_change=-20.0,
            ratio=0.8,
            lower_is_better=True,
            unit="seconds",
            status=ComparisonStatus.IMPROVED,
            reason="-20.00% improved",
            threshold_pct=1.0,
        )
        d = mc.to_dict()
        mc2 = MetricComparison.from_dict(d)
        assert mc2.metric_name == mc.metric_name
        assert math.isclose(mc2.baseline_value, 0.100)
        assert math.isclose(mc2.target_value, 0.080)
        assert math.isclose(mc2.delta, -0.020)
        assert math.isclose(mc2.percent_change, -20.0)
        assert mc2.status == ComparisonStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema2_strategy_comparison_roundtrip():
    """StrategyComparison to_dict and from_dict round-trip preserves all fields."""
    tid, name = "W10-SCHEMA2", "StrategyComparison to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import ComparisonStatus, MetricComparison, OverallStatus, StrategyComparison
        mc = MetricComparison(
            metric_name="execution_time",
            baseline_value=0.100,
            target_value=0.085,
            delta=-0.015,
            percent_change=-15.0,
            ratio=0.85,
            lower_is_better=True,
            unit="seconds",
            status=ComparisonStatus.IMPROVED,
            reason="-15.00% improved",
        )
        sc = StrategyComparison(
            strategy_name="-O2",
            reference_strategy="baseline (-O0)",
            is_valid=True,
            pareto_status="FRONTIER",
            metric_comparisons={"execution_time": mc},
            overall_status=OverallStatus.IMPROVED,
        )
        d = sc.to_dict()
        sc2 = StrategyComparison.from_dict(d)
        assert sc2.strategy_name == "-O2"
        assert sc2.overall_status == OverallStatus.IMPROVED
        assert "execution_time" in sc2.metric_comparisons
        assert sc2.metric_comparisons["execution_time"].status == ComparisonStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema3_program_comparison_roundtrip():
    """ProgramComparison to_dict and from_dict round-trip."""
    tid, name = "W10-SCHEMA3", "ProgramComparison to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import OverallStatus, ProgramComparison
        pc = ProgramComparison(
            program_id="01_hello",
            status="ok",
            baseline_strategy="baseline (-O0)",
            selected_strategy="-O2",
            selected_comparison=None,
            strategy_comparisons={},
            pareto_frontier=["-O2"],
            overall_status=OverallStatus.UNCHANGED,
            pipeline_error=None,
        )
        d = pc.to_dict()
        pc2 = ProgramComparison.from_dict(d)
        assert pc2.program_id == "01_hello"
        assert pc2.selected_strategy == "-O2"
        assert pc2.pareto_frontier == ["-O2"]
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema4_historical_comparison_roundtrip():
    """HistoricalComparison to_dict and from_dict round-trip."""
    tid, name = "W10-SCHEMA4", "HistoricalComparison to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import HistoricalComparison, HistoricalProgramComparison, OverallStatus
        hpc = HistoricalProgramComparison(
            program_id="prog_a",
            status="ok",
            previous_run_id="run_1",
            current_run_id="run_2",
            overall_status=OverallStatus.REGRESSED,
            notes=["Slight regression in runtime"],
        )
        hc = HistoricalComparison(
            previous_run_id="run_1",
            current_run_id="run_2",
            programs={"prog_a": hpc},
            summary={"n_common": 1, "n_regressed": 1},
        )
        d = hc.to_dict()
        hc2 = HistoricalComparison.from_dict(d)
        assert hc2.previous_run_id == "run_1"
        assert hc2.current_run_id == "run_2"
        assert "prog_a" in hc2.programs
        assert hc2.programs["prog_a"].overall_status == OverallStatus.REGRESSED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema5_regression_report_roundtrip():
    """RegressionReport to_dict and from_dict round-trip preserves report structure."""
    tid, name = "W10-SCHEMA5", "RegressionReport to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import REGRESSION_SCHEMA_VERSION, OverallStatus, ProgramComparison, RegressionReport
        pc = ProgramComparison(
            program_id="prog_1",
            status="ok",
            selected_strategy="-O2",
            overall_status=OverallStatus.IMPROVED,
        )
        rr = RegressionReport(
            schema_version=REGRESSION_SCHEMA_VERSION,
            report_id="reg_test_001",
            created_at="2026-10-04T12:00:00",
            suite_name="test_suite",
            thresholds={"default_threshold_pct": 1.0},
            program_comparisons={"prog_1": pc},
            summary={"n_total": 1, "n_improved": 1},
        )
        d = rr.to_dict()
        assert d["schema_version"] == REGRESSION_SCHEMA_VERSION
        rr2 = RegressionReport.from_dict(d)
        assert rr2.report_id == "reg_test_001"
        assert rr2.summary["n_improved"] == 1
        assert "prog_1" in rr2.program_comparisons
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema6_schema_version_constant():
    """REGRESSION_SCHEMA_VERSION is 'week10.1.0'."""
    tid, name = "W10-SCHEMA6", "REGRESSION_SCHEMA_VERSION is non-empty week10.1.0 string"
    try:
        from moo.regression.schema import REGRESSION_SCHEMA_VERSION
        assert REGRESSION_SCHEMA_VERSION == "week10.1.0"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema7_text_summary_rendering():
    """RegressionReport.to_text_summary() renders formatted table without raising."""
    tid, name = "W10-SCHEMA7", "RegressionReport to_text_summary renders cleanly"
    try:
        from moo.regression.schema import REGRESSION_SCHEMA_VERSION, OverallStatus, ProgramComparison, RegressionReport
        pc = ProgramComparison(
            program_id="demo_prog",
            status="ok",
            selected_strategy="-O2",
            overall_status=OverallStatus.IMPROVED,
        )
        rr = RegressionReport(
            schema_version=REGRESSION_SCHEMA_VERSION,
            report_id="rep_1",
            created_at="2026-10-04",
            suite_name="demo",
            thresholds={},
            program_comparisons={"demo_prog": pc},
            summary={"n_total": 1, "n_improved": 1},
        )
        txt = rr.to_text_summary()
        assert "TOACD OPTIMIZATION REGRESSION REPORT" in txt
        assert "demo_prog" in txt
        assert "-O2" in txt
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-COMP: Comparisons & Direction Correctness
# ===========================================================================

def test_comp1_baseline_vs_selected_execution_time():
    """Faster candidate execution time is classified as IMPROVED."""
    tid, name = "W10-COMP1", "Execution time reduction classified as IMPROVED"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import ComparisonStatus
        rec = _make_mock_record(base_time=0.100)  # -O2 has 0.080s (20% faster)
        pcomp = compare_program(rec, selected_strategy="-O2")
        assert pcomp.selected_strategy == "-O2"
        assert pcomp.selected_comparison is not None
        mc = pcomp.selected_comparison.metric_comparisons["execution_time"]
        assert mc.status == ComparisonStatus.IMPROVED
        assert math.isclose(mc.percent_change, -20.0, rel_tol=1e-3)
        assert mc.delta < 0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp2_baseline_vs_selected_regression():
    """Slower candidate execution time is classified as REGRESSED."""
    tid, name = "W10-COMP2", "Execution time increase classified as REGRESSED"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import ComparisonStatus
        rec = _make_mock_record(base_time=0.100)  # -O3 has 0.110s (10% slower)
        pcomp = compare_program(rec, selected_strategy="-O3")
        mc = pcomp.selected_comparison.metric_comparisons["execution_time"]
        assert mc.status == ComparisonStatus.REGRESSED
        assert math.isclose(mc.percent_change, 10.0, rel_tol=1e-3)
        assert mc.delta > 0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp3_code_size_direction_correctness():
    """Code size lower is better: smaller size is IMPROVED, larger is REGRESSED."""
    tid, name = "W10-COMP3", "Code size direction semantics verified"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        # Smaller size (8000 vs 10000 bytes) -> -20% -> IMPROVED
        mc_small = detect_metric_change("code_size", 10000, 8000, lower_is_better=True)
        assert mc_small.status == ComparisonStatus.IMPROVED
        assert mc_small.percent_change == -20.0

        # Larger size (12000 vs 10000 bytes) -> +20% -> REGRESSED
        mc_large = detect_metric_change("code_size", 10000, 12000, lower_is_better=True)
        assert mc_large.status == ComparisonStatus.REGRESSED
        assert mc_large.percent_change == 20.0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp4_security_sinks_direction_correctness():
    """Security sinks: sinks_eliminated lower is better, sinks_preserved higher is better."""
    tid, name = "W10-COMP4", "Security metrics directionality semantics verified"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        # sinks_eliminated: 0 is better than 2
        # Baseline = 0, Target = 2 -> increased -> REGRESSED
        mc_elim = detect_metric_change("sinks_eliminated", 0, 2, lower_is_better=True, threshold_pct=0.0)
        assert mc_elim.status == ComparisonStatus.REGRESSED

        # sinks_preserved: higher is better
        # Baseline = 10, Target = 15 -> increased -> IMPROVED
        mc_pres_up = detect_metric_change("sinks_preserved", 10, 15, lower_is_better=False, threshold_pct=1.0)
        assert mc_pres_up.status == ComparisonStatus.IMPROVED

        # Baseline = 10, Target = 5 -> decreased -> REGRESSED
        mc_pres_down = detect_metric_change("sinks_preserved", 10, 5, lower_is_better=False, threshold_pct=1.0)
        assert mc_pres_down.status == ComparisonStatus.REGRESSED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp5_all_strategies_compared():
    """compare_program populates strategy_comparisons for all candidate strategies."""
    tid, name = "W10-COMP5", "All available strategies compared against baseline"
    try:
        from moo.regression.comparator import compare_program
        rec = _make_mock_record()
        pcomp = compare_program(rec)
        assert "-O2" in pcomp.strategy_comparisons
        assert "-O3" in pcomp.strategy_comparisons
        assert pcomp.strategy_comparisons["-O2"].reference_strategy == "baseline (-O0)"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp6_strategy_vs_strategy_arbitrary_reference():
    """compare_strategies allows arbitrary reference strategy."""
    tid, name = "W10-COMP6", "compare_strategies supports arbitrary reference strategy"
    try:
        from moo.regression.comparator import compare_strategies
        from moo.regression.schema import ComparisonStatus
        cand_o2 = {"measurement": {"timing": {"median_s": 0.080}}}
        cand_o3 = {"measurement": {"timing": {"median_s": 0.070}}}
        # Compare -O3 against -O2 (0.070 vs 0.080 -> 12.5% faster)
        sc = compare_strategies(
            reference_data=cand_o2,
            target_data=cand_o3,
            target_strategy_name="-O3",
            reference_strategy_name="-O2",
        )
        assert sc.strategy_name == "-O3"
        assert sc.reference_strategy == "-O2"
        mc = sc.metric_comparisons["execution_time"]
        assert mc.status == ComparisonStatus.IMPROVED
        assert math.isclose(mc.percent_change, -12.5)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_comp7_percent_calculation_precision():
    """Percentage calculation matches exact delta formula: ((t - b) / b) * 100."""
    tid, name = "W10-COMP7", "Percentage calculation matches exact delta formula"
    try:
        from moo.regression.detector import detect_metric_change
        # 42.1 ms to 45.7 ms -> +8.551068...%
        mc = detect_metric_change("execution_time", 0.0421, 0.0457)
        expected = ((0.0457 - 0.0421) / 0.0421) * 100.0
        assert math.isclose(mc.percent_change, expected, rel_tol=1e-6)
        assert math.isclose(mc.percent_change, 8.551, abs_tol=0.01)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-REG: Regression, Improvement, & Threshold Detection
# ===========================================================================

def test_reg1_exact_no_change_detection():
    """Zero delta produces UNCHANGED status and 0.0% change."""
    tid, name = "W10-REG1", "Exact zero delta produces UNCHANGED status"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change("energy", 45.0, 45.0, threshold_pct=1.0)
        assert mc.status == ComparisonStatus.UNCHANGED
        assert mc.delta == 0.0
        assert mc.percent_change == 0.0
        assert mc.ratio == 1.0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg2_within_threshold_classified_unchanged():
    """Delta within threshold band (e.g. +0.5% with threshold 1.0%) is UNCHANGED."""
    tid, name = "W10-REG2", "Delta within threshold band classified as UNCHANGED"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        # 100 to 100.5 -> +0.5% change <= 1.0%
        mc = detect_metric_change("execution_time", 100.0, 100.5, threshold_pct=1.0)
        assert mc.status == ComparisonStatus.UNCHANGED
        assert math.isclose(mc.percent_change, 0.5)

        # 100 to 99.5 -> -0.5% change <= 1.0%
        mc2 = detect_metric_change("execution_time", 100.0, 99.5, threshold_pct=1.0)
        assert mc2.status == ComparisonStatus.UNCHANGED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg3_threshold_boundary_behavior():
    """Values crossing threshold by epsilon are classified correctly."""
    tid, name = "W10-REG3", "Threshold boundary transition verified"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        # Threshold = 1.0%
        # +1.000% -> exactly on boundary -> UNCHANGED
        mc_boundary = detect_metric_change("execution_time", 100.0, 101.0, threshold_pct=1.0)
        assert mc_boundary.status == ComparisonStatus.UNCHANGED

        # +1.001% -> crosses boundary -> REGRESSED
        mc_cross = detect_metric_change("execution_time", 100.0, 101.001, threshold_pct=1.0)
        assert mc_cross.status == ComparisonStatus.REGRESSED

        # -1.001% -> crosses boundary -> IMPROVED
        mc_imp = detect_metric_change("execution_time", 100.0, 98.999, threshold_pct=1.0)
        assert mc_imp.status == ComparisonStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg4_zero_threshold_strictness():
    """Threshold 0.0 classifies any non-zero difference as IMPROVED or REGRESSED."""
    tid, name = "W10-REG4", "Zero threshold classifies any non-zero difference"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc_up = detect_metric_change("code_size", 1000, 1001, threshold_pct=0.0)
        assert mc_up.status == ComparisonStatus.REGRESSED

        mc_down = detect_metric_change("code_size", 1000, 999, threshold_pct=0.0)
        assert mc_down.status == ComparisonStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg5_per_metric_threshold_overrides():
    """RegressionThresholds applies per-metric override thresholds."""
    tid, name = "W10-REG5", "per_metric_thresholds override defaults"
    try:
        from moo.regression.detector import RegressionThresholds
        rt = RegressionThresholds(
            default_threshold_pct=1.0,
            per_metric_thresholds={"code_size": 0.0, "execution_time": 5.0},
        )
        assert rt.get_threshold("code_size") == 0.0
        assert rt.get_threshold("execution_time") == 5.0
        assert rt.get_threshold("energy") == 1.0  # default
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg6_multi_metric_overall_improved():
    """All metrics improved or unchanged yields OverallStatus.IMPROVED."""
    tid, name = "W10-REG6", "Consistently improved metrics yield OverallStatus.IMPROVED"
    try:
        from moo.regression.detector import derive_overall_status, detect_metric_change
        from moo.regression.schema import OverallStatus
        m1 = detect_metric_change("execution_time", 100, 80)  # IMPROVED
        m2 = detect_metric_change("energy", 50, 40)          # IMPROVED
        m3 = detect_metric_change("code_size", 1000, 1000)   # UNCHANGED
        overall = derive_overall_status([m1, m2, m3])
        assert overall == OverallStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg7_multi_metric_overall_regressed():
    """Metrics regressed without any improved yields OverallStatus.REGRESSED."""
    tid, name = "W10-REG7", "Consistently regressed metrics yield OverallStatus.REGRESSED"
    try:
        from moo.regression.detector import derive_overall_status, detect_metric_change
        from moo.regression.schema import OverallStatus
        m1 = detect_metric_change("execution_time", 100, 120)  # REGRESSED
        m2 = detect_metric_change("energy", 50, 60)           # REGRESSED
        m3 = detect_metric_change("code_size", 1000, 1000)    # UNCHANGED
        overall = derive_overall_status([m1, m2, m3])
        assert overall == OverallStatus.REGRESSED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reg8_multi_metric_overall_mixed():
    """Trade-off (some improved, some regressed) yields OverallStatus.MIXED."""
    tid, name = "W10-REG8", "Trade-off across metrics yields OverallStatus.MIXED"
    try:
        from moo.regression.detector import derive_overall_status, detect_metric_change
        from moo.regression.schema import OverallStatus
        m1 = detect_metric_change("execution_time", 100, 70)  # IMPROVED (faster)
        m2 = detect_metric_change("code_size", 1000, 1300)   # REGRESSED (bloated)
        overall = derive_overall_status([m1, m2])
        assert overall == OverallStatus.MIXED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-HIST: Cross-Run Historical Comparisons
# ===========================================================================

def test_hist1_historical_run_delta():
    """Historical run comparison computes accurate delta between two runs."""
    tid, name = "W10-HIST1", "Cross-run comparison computes accurate historical delta"
    try:
        from moo.regression.historical import compare_historical_runs
        from moo.regression.schema import ComparisonStatus
        prev_recs = [_make_mock_record("prog1", base_time=0.100)]
        curr_recs = [_make_mock_record("prog1", base_time=0.120)]  # 20% slower in current run

        hcomp = compare_historical_runs(
            previous_records=prev_recs,
            current_records=curr_recs,
            previous_run_id="run_A",
            current_run_id="run_B",
        )
        assert hcomp.summary["n_common"] == 1
        assert "prog1" in hcomp.programs
        p_res = hcomp.programs["prog1"]
        mc = p_res.metric_comparisons["execution_time"]
        assert mc.status == ComparisonStatus.REGRESSED
        assert math.isclose(mc.percent_change, 20.0, rel_tol=1e-3)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hist2_historical_missing_previous_program():
    """Program present in current but missing in previous run is tracked as missing_previous."""
    tid, name = "W10-HIST2", "Program missing in previous run handled gracefully"
    try:
        from moo.regression.historical import compare_historical_runs
        from moo.regression.schema import OverallStatus
        prev_recs = []
        curr_recs = [_make_mock_record("new_prog")]
        hcomp = compare_historical_runs(prev_recs, curr_recs, "r1", "r2")
        assert hcomp.summary["n_missing_previous"] == 1
        p_res = hcomp.programs["new_prog"]
        assert p_res.status == "missing_previous"
        assert p_res.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hist3_historical_missing_current_program():
    """Program present in previous but missing in current run is tracked as missing_current."""
    tid, name = "W10-HIST3", "Program missing in current run handled gracefully"
    try:
        from moo.regression.historical import compare_historical_runs
        from moo.regression.schema import OverallStatus
        prev_recs = [_make_mock_record("removed_prog")]
        curr_recs = []
        hcomp = compare_historical_runs(prev_recs, curr_recs, "r1", "r2")
        assert hcomp.summary["n_missing_current"] == 1
        p_res = hcomp.programs["removed_prog"]
        assert p_res.status == "missing_current"
        assert p_res.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hist4_historical_failure_in_previous():
    """Failed benchmark in previous run is marked failed_previous without crash."""
    tid, name = "W10-HIST4", "Failed benchmark in previous run marked safely"
    try:
        from moo.regression.historical import compare_historical_runs
        prev_recs = [_make_mock_record("failing_prog", status="pipeline_error")]
        curr_recs = [_make_mock_record("failing_prog", status="ok")]
        hcomp = compare_historical_runs(prev_recs, curr_recs, "r1", "r2")
        assert hcomp.summary["n_failed_previous"] == 1
        assert hcomp.programs["failing_prog"].status == "failed_previous"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hist5_historical_failure_in_current():
    """Failed benchmark in current run is marked failed_current without crash."""
    tid, name = "W10-HIST5", "Failed benchmark in current run marked safely"
    try:
        from moo.regression.historical import compare_historical_runs
        prev_recs = [_make_mock_record("broken_prog", status="ok")]
        curr_recs = [_make_mock_record("broken_prog", status="pipeline_error")]
        hcomp = compare_historical_runs(prev_recs, curr_recs, "r1", "r2")
        assert hcomp.summary["n_failed_current"] == 1
        assert hcomp.programs["broken_prog"].status == "failed_current"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hist6_historical_per_strategy_comparison():
    """Historical comparison tracks common candidate strategies across runs."""
    tid, name = "W10-HIST6", "Per-strategy historical comparisons populated"
    try:
        from moo.regression.historical import compare_historical_runs
        from moo.regression.schema import ComparisonStatus
        prev_recs = [_make_mock_record("p1")]
        curr_recs = [_make_mock_record("p1")]
        hcomp = compare_historical_runs(prev_recs, curr_recs)
        strat_h = hcomp.programs["p1"].strategy_historical
        assert "-O2" in strat_h
        assert "-O3" in strat_h
        assert strat_h["-O2"]["execution_time"].status == ComparisonStatus.UNCHANGED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-FAIL: Failure Isolation & Missing Metric Handling
# ===========================================================================

def test_fail1_missing_metric_handled_safely():
    """None or missing metric value does not crash and produces INCOMPARABLE."""
    tid, name = "W10-FAIL1", "Missing metric value produces INCOMPARABLE without crashing"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change("execution_time", None, 0.050)
        assert mc.status == ComparisonStatus.INCOMPARABLE
        assert mc.delta is None
        assert mc.percent_change is None
        assert "Baseline value is missing" in mc.reason
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_fail2_nan_and_inf_handled_safely():
    """NaN or Inf inputs produce INCOMPARABLE without crashing."""
    tid, name = "W10-FAIL2", "NaN and Inf values produce INCOMPARABLE safely"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc_nan = detect_metric_change("energy", float("nan"), 10.0)
        assert mc_nan.status == ComparisonStatus.INCOMPARABLE

        mc_inf = detect_metric_change("energy", 10.0, float("inf"))
        assert mc_inf.status == ComparisonStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_fail3_pipeline_error_program_handled():
    """ProgramRecord with pipeline_error produces INCOMPARABLE status and records reason."""
    tid, name = "W10-FAIL3", "Pipeline error program handled gracefully"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import OverallStatus
        rec = _make_mock_record(status="pipeline_error", pipeline_error="Clang crash")
        pcomp = compare_program(rec)
        assert pcomp.status == "pipeline_error"
        assert pcomp.overall_status == OverallStatus.INCOMPARABLE
        assert "Clang crash" in pcomp.pipeline_error
        assert pcomp.selected_comparison is None
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_fail4_malformed_record_dict_handled():
    """Empty or malformed dictionary handled without raising exceptions."""
    tid, name = "W10-FAIL4", "Malformed record dict handled without exception"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import OverallStatus
        pcomp = compare_program({})
        assert pcomp.program_id == "unknown"
        assert pcomp.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_fail5_candidate_without_measurement_handled():
    """Candidate result without measurement dict handled gracefully."""
    tid, name = "W10-FAIL5", "Candidate without measurement dict handled safely"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import ComparisonStatus
        cands = [{"strategy_name": "-O1", "build_ok": False, "measurement": None}]
        rec = _make_mock_record(candidates=cands, frontier=[])
        pcomp = compare_program(rec, selected_strategy="-O1")
        assert "-O1" in pcomp.strategy_comparisons
        sc = pcomp.strategy_comparisons["-O1"]
        assert sc.is_valid is False
        assert sc.metric_comparisons["execution_time"].status == ComparisonStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_fail6_non_existent_selected_strategy():
    """Selecting a non-existent strategy name yields None selected_comparison."""
    tid, name = "W10-FAIL6", "Non-existent selected strategy name handled safely"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import OverallStatus
        rec = _make_mock_record()
        pcomp = compare_program(rec, selected_strategy="non_existent_opt")
        assert pcomp.selected_strategy == "non_existent_opt"
        assert pcomp.selected_comparison is None
        assert pcomp.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-DET: Determinism & Stability
# ===========================================================================

def test_det1_comparison_determinism_50_runs():
    """Repeated comparison calls yield identical numerical and status results."""
    tid, name = "W10-DET1", "Repeated comparison calls yield identical results over 50 runs"
    try:
        from moo.regression.comparator import compare_program
        rec = _make_mock_record()
        ref = compare_program(rec, selected_strategy="-O2")
        for _ in range(50):
            cur = compare_program(rec, selected_strategy="-O2")
            assert cur.overall_status == ref.overall_status
            assert cur.selected_strategy == ref.selected_strategy
            for m, mc in ref.selected_comparison.metric_comparisons.items():
                cur_mc = cur.selected_comparison.metric_comparisons[m]
                assert cur_mc.status == mc.status
                assert cur_mc.percent_change == mc.percent_change
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det2_report_generation_determinism():
    """build_regression_report generates identical output dicts on repeated calls."""
    tid, name = "W10-DET2", "build_regression_report generates identical dict output"
    try:
        from moo.regression.report import build_regression_report
        records = [_make_mock_record(f"p_{i}") for i in range(5)]
        rep1 = build_regression_report(records, suite_name="fixed_suite")
        rep2 = build_regression_report(records, suite_name="fixed_suite")

        d1 = rep1.to_dict()
        d2 = rep2.to_dict()
        # Exclude random report_id and timestamps for determinism check
        for k in ("report_id", "created_at"):
            d1.pop(k, None)
            d2.pop(k, None)
        assert d1 == d2
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det3_stable_ordering_of_strategies():
    """strategy_comparisons maintains stable ordering."""
    tid, name = "W10-DET3", "strategy_comparisons maintains stable ordering"
    try:
        from moo.regression.comparator import compare_program
        rec = _make_mock_record()
        pcomp = compare_program(rec)
        keys1 = list(pcomp.strategy_comparisons.keys())
        pcomp2 = compare_program(rec)
        keys2 = list(pcomp2.strategy_comparisons.keys())
        assert keys1 == keys2
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det4_report_file_save_and_load_stability():
    """save_regression_report and load_regression_report round-trip cleanly."""
    tid, name = "W10-DET4", "save_regression_report and load_regression_report round-trip"
    try:
        from moo.regression.report import build_regression_report, load_regression_report, save_regression_report
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog_a")]
            rep = build_regression_report(records)
            out_file = os.path.join(tmpdir, "report.json")
            save_regression_report(rep, out_file)
            assert os.path.isfile(out_file)

            loaded = load_regression_report(out_file)
            assert loaded.report_id == rep.report_id
            assert loaded.schema_version == rep.schema_version
            assert loaded.summary == rep.summary
            assert "prog_a" in loaded.program_comparisons
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-SCOPE: Architecture & Scope Guard
# ===========================================================================

def test_scope1_no_week11_comparison_modules():
    """Verify that no Week 11+ comparison or benchmarking modules were added."""
    tid, name = "W10-SCOPE1", "No Week 11+ modules in moo/"
    try:
        prohibited = [
            "moo.activity_stream",
            "moo.agentic_stream",
            "moo.unified_report",
            "moo.ui_redesign",
        ]
        import importlib
        for mod in prohibited:
            try:
                importlib.import_module(mod)
                assert False, f"Week 11+ module {mod!r} should not exist yet"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope2_week8_scope_guards_unbroken():
    """Verify that Week 8 scope guards are not triggered."""
    tid, name = "W10-SCOPE2", "Week 8 scope guards remain unbroken"
    try:
        prohibited = [
            "moo.regression_tracker",
            "moo.regression_platform",
            "moo.historical_comparison",
        ]
        import importlib
        for mod in prohibited:
            try:
                importlib.import_module(mod)
                assert False, f"Prohibited module {mod!r} should not exist"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope3_gui_file_untouched():
    """gui_app.py is not imported or modified by regression package."""
    tid, name = "W10-SCOPE3", "gui_app.py is untouched and unimported by regression package"
    try:
        regression_modules = [
            "moo.regression.schema",
            "moo.regression.detector",
            "moo.regression.comparator",
            "moo.regression.historical",
            "moo.regression.report",
        ]
        import importlib
        for mod_name in regression_modules:
            mod = importlib.import_module(mod_name)
            src_file = getattr(mod, "__file__", "")
            if src_file and os.path.isfile(src_file):
                with open(src_file, "r", encoding="utf-8") as fh:
                    content = fh.read()
                assert "gui_app" not in content, f"{mod_name} imports gui_app"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope4_optimization_selection_logic_unchanged():
    """Core selection logic in optimization_selector and ml_optimizer is untouched."""
    tid, name = "W10-SCOPE4", "Optimization selection logic is unchanged"
    try:
        from moo.selector_bridge import moo_aware_select
        from ml_optimizer import ACTIONS
        q_dummy = [0.1, 0.2, 0.8, 0.4, 0.1, 0.1, 0.1, 0.1, 0.1]
        res = moo_aware_select("dummy.c", q_dummy, ACTIONS, ["-O2"])
        assert res.strategy == "-O2"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope5_week9_bench_outputs_reused():
    """Regression package consumes Week 9 ProgramRecord without re-running benchmark."""
    tid, name = "W10-SCOPE5", "Week 9 benchmark output schema directly consumed"
    try:
        from moo.bench.schema import ProgramRecord
        from moo.regression.comparator import compare_program
        rec = ProgramRecord(
            schema_version="week9.1.0",
            run_id="run_bench",
            program_id="test_bench",
            corpus_entry={},
            status="ok",
            evaluated_at="2026-10-04",
            baseline={
                "strategy_name": "baseline (-O0)",
                "measurement": {"timing": {"median_s": 0.050}},
            },
            candidates=[
                {
                    "strategy_name": "-O2",
                    "build_ok": True,
                    "correct": True,
                    "measurement": {"timing": {"median_s": 0.040}},
                    "pareto_status": "FRONTIER",
                }
            ],
            pareto_frontier=["-O2"],
        )
        pcomp = compare_program(rec, selected_strategy="-O2")
        assert pcomp.program_id == "test_bench"
        assert pcomp.selected_strategy == "-O2"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-PROV: Selection Provenance Enforcement
# ===========================================================================

def test_prov1_valid_selection_record_accepted():
    """Explicit SelectionRecord is accepted and provenance is attached to ProgramComparison."""
    tid, name = "W10-PROV1", "Explicit SelectionRecord attached to ProgramComparison"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import SelectionRecord
        rec = _make_mock_record("p1")
        rec["source_sha256"] = "a" * 64
        sr = SelectionRecord(
            program_id="p1",
            source_sha256="a" * 64,
            selected_strategy="-O2",
            selection_source="ml_optimizer",
            model_identifier="q_learning_v1",
            trace_id="trace_001",
        )
        pcomp = compare_program(rec, selection_record=sr)
        assert pcomp.selected_strategy == "-O2"
        assert pcomp.selection_provenance is not None
        assert pcomp.selection_provenance.model_identifier == "q_learning_v1"
        assert pcomp.selection_provenance.trace_id == "trace_001"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_prov2_missing_selection_refuses_fabrication():
    """When no selection is provided, comparator refuses to fabricate an AI selection."""
    tid, name = "W10-PROV2", "Omitting selection refuses to fabricate AI choice"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import OverallStatus
        rec = _make_mock_record("p1")
        pcomp = compare_program(rec)
        assert pcomp.selected_strategy is None
        assert pcomp.selected_comparison is None
        assert pcomp.selection_provenance is None
        assert pcomp.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_prov3_mismatched_source_sha256_rejected():
    """SelectionRecord with mismatched source_sha256 raises ValueError."""
    tid, name = "W10-PROV3", "SelectionRecord with mismatched source_sha256 rejected"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import SelectionRecord
        rec = _make_mock_record("p1")
        rec["source_sha256"] = "a" * 64
        sr = SelectionRecord(
            program_id="p1",
            source_sha256="b" * 64,
            selected_strategy="-O2",
            selection_source="ml_optimizer",
        )
        rejected = False
        try:
            compare_program(rec, selection_record=sr)
        except ValueError:
            rejected = True
        assert rejected, "Expected ValueError on mismatched source_sha256"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_prov4_mismatched_program_id_rejected():
    """SelectionRecord with mismatched program_id raises ValueError."""
    tid, name = "W10-PROV4", "SelectionRecord with mismatched program_id rejected"
    try:
        from moo.regression.comparator import compare_program
        from moo.regression.schema import SelectionRecord
        rec = _make_mock_record("prog_A")
        sr = SelectionRecord(
            program_id="prog_B",
            source_sha256="a" * 64,
            selected_strategy="-O2",
            selection_source="ml_optimizer",
        )
        rejected = False
        try:
            compare_program(rec, selection_record=sr)
        except ValueError:
            rejected = True
        assert rejected, "Expected ValueError on mismatched program_id"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_prov5_selection_record_roundtrip():
    """SelectionRecord to_dict/from_dict round-trip preserves all fields."""
    tid, name = "W10-PROV5", "SelectionRecord to_dict/from_dict round-trip"
    try:
        from moo.regression.schema import SelectionRecord
        sr = SelectionRecord(
            program_id="test_p",
            source_sha256="1234567890abcdef" * 4,
            selected_strategy="-O3",
            selection_source="ml_optimizer",
            model_identifier="ppo_v2",
            trace_id="tr_42",
            timestamp="2026-10-04T12:00:00",
        )
        d = sr.to_dict()
        sr2 = SelectionRecord.from_dict(d)
        assert sr2.program_id == sr.program_id
        assert sr2.source_sha256 == sr.source_sha256
        assert sr2.selected_strategy == sr.selected_strategy
        assert sr2.selection_source == sr.selection_source
        assert sr2.model_identifier == sr.model_identifier
        assert sr2.trace_id == sr.trace_id
        assert sr2.timestamp == sr.timestamp
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-NOISE: Noise-Aware Regression & Measurement Reliability
# ===========================================================================

def test_noise1_unreliable_timing_yields_inconclusive():
    """When timing is marked unreliable, execution_time change is INCONCLUSIVE."""
    tid, name = "W10-NOISE1", "Unreliable timing yields INCONCLUSIVE status"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change(
            "execution_time",
            baseline_val=0.100,
            target_val=0.080,
            target_is_reliable=False,
            target_cv=0.15,
        )
        assert mc.status == ComparisonStatus.INCONCLUSIVE
        assert mc.is_reliable is False
        assert "unreliable" in mc.reason
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise2_delta_within_cv_envelope_yields_inconclusive():
    """When percentage delta is within CV noise band, change is INCONCLUSIVE."""
    tid, name = "W10-NOISE2", "Delta within CV noise band yields INCONCLUSIVE"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change(
            "execution_time",
            baseline_val=0.100,
            target_val=0.097,
            baseline_cv=0.05,
            target_cv=0.05,
            baseline_is_reliable=True,
            target_is_reliable=True,
        )
        assert mc.status == ComparisonStatus.INCONCLUSIVE
        assert "noise" in mc.reason or "inconclusive" in mc.reason
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise3_control_identical_inputs_strictly_unchanged():
    """Identical control inputs strictly evaluate as UNCHANGED."""
    tid, name = "W10-NOISE3", "Identical control inputs strictly evaluate as UNCHANGED"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change(
            "execution_time",
            baseline_val=0.100,
            target_val=0.100,
            baseline_cv=0.02,
            target_cv=0.02,
        )
        assert mc.status == ComparisonStatus.UNCHANGED
        assert mc.delta == 0.0
        assert mc.percent_change == 0.0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise4_low_noise_confident_classification():
    """High delta with low CV noise is reliably classified as IMPROVED."""
    tid, name = "W10-NOISE4", "High delta with low noise is classified as IMPROVED"
    try:
        from moo.regression.detector import detect_metric_change
        from moo.regression.schema import ComparisonStatus
        mc = detect_metric_change(
            "execution_time",
            baseline_val=0.100,
            target_val=0.075,
            baseline_cv=0.01,
            target_cv=0.01,
            baseline_is_reliable=True,
            target_is_reliable=True,
        )
        assert mc.status == ComparisonStatus.IMPROVED
        assert mc.is_reliable is True
        assert mc.confidence.upper() == "HIGH"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-DERIV: Derived Signals & Metric Families
# ===========================================================================

def test_deriv1_signal_family_grouping():
    """Metrics are categorized into canonical families."""
    tid, name = "W10-DERIV1", "Metrics mapped to canonical families"
    try:
        from moo.regression.detector import METRIC_SIGNAL_FAMILIES
        assert METRIC_SIGNAL_FAMILIES.get("execution_time") == "performance"
        assert METRIC_SIGNAL_FAMILIES.get("code_size") == "size"
        assert METRIC_SIGNAL_FAMILIES.get("security_sink_calls") == "security"
        assert METRIC_SIGNAL_FAMILIES.get("energy") == "performance"
        assert METRIC_SIGNAL_FAMILIES.get("carbon") == "performance"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_deriv2_family_status_aggregation():
    """StrategyComparison populates family_comparisons and family_status."""
    tid, name = "W10-DERIV2", "Family comparisons aggregated correctly"
    try:
        from moo.regression.comparator import compare_strategies
        from moo.regression.schema import OverallStatus
        m_base = {
            "measurement": {
                "timing": {"median_s": 0.100},
                "code_size": {"primary_value": 1000},
            }
        }
        m_target = {
            "measurement": {
                "timing": {"median_s": 0.080},
                "code_size": {"primary_value": 900},
            }
        }
        sc = compare_strategies(
            reference_data=m_base,
            target_data=m_target,
            target_strategy_name="-O2",
            reference_strategy_name="baseline (-O0)",
        )
        assert "performance" in sc.family_comparisons
        assert "size" in sc.family_comparisons
        assert sc.family_status.get("performance") == OverallStatus.IMPROVED
        assert sc.family_status.get("size") == OverallStatus.IMPROVED
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_deriv3_derived_relationships_documented():
    """Energy and carbon are documented as derived from execution_time."""
    tid, name = "W10-DERIV3", "Derived relationships documented"
    try:
        from moo.regression.detector import DERIVED_METRIC_RELATIONSHIPS
        assert "elapsed_time" in DERIVED_METRIC_RELATIONSHIPS.get("energy", "")
        assert "energy" in DERIVED_METRIC_RELATIONSHIPS.get("carbon", "")
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-HGUARD: Historical Comparison Guards & Compatibility
# ===========================================================================

def test_hguard1_matching_source_hash_comparable():
    """Matching source_sha256 allows historical comparison."""
    tid, name = "W10-HGUARD1", "Matching source_sha256 allows historical comparison"
    try:
        from moo.regression.historical import compare_historical_runs
        sha = "c" * 64
        rec1 = _make_mock_record("p1")
        rec1["source_sha256"] = sha
        rec2 = _make_mock_record("p1")
        rec2["source_sha256"] = sha
        hcomp = compare_historical_runs([rec1], [rec2], "run1", "run2")
        pcomp = hcomp.programs["p1"]
        assert pcomp.status == "ok"
        assert pcomp.environment_compatible is True
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hguard2_mismatched_source_hash_incomparable():
    """Mismatched source_sha256 marks historical program INCOMPARABLE."""
    tid, name = "W10-HGUARD2", "Mismatched source_sha256 produces source_mismatch"
    try:
        from moo.regression.historical import compare_historical_runs
        from moo.regression.schema import OverallStatus
        rec1 = _make_mock_record("p1")
        rec1["source_sha256"] = "1" * 64
        rec2 = _make_mock_record("p1")
        rec2["source_sha256"] = "2" * 64
        hcomp = compare_historical_runs([rec1], [rec2], "run1", "run2")
        pcomp = hcomp.programs["p1"]
        assert pcomp.status == "source_mismatch"
        assert pcomp.overall_status == OverallStatus.INCOMPARABLE
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_hguard3_incompatible_environment_detected():
    """Mismatched toolchain or platform marks environment_compatible False."""
    tid, name = "W10-HGUARD3", "Environment mismatch flagged in historical comparison"
    try:
        from moo.regression.historical import compare_historical_runs
        sha = "d" * 64
        rec1 = _make_mock_record("p1")
        rec1["source_sha256"] = sha
        rec2 = _make_mock_record("p1")
        rec2["source_sha256"] = sha
        prev_manifest = {"toolchain": {"clang_version": "17.0.1"}}
        curr_manifest = {"toolchain": {"clang_version": "18.1.0"}}
        hcomp = compare_historical_runs(
            [rec1], [rec2], "run1", "run2",
            previous_manifest=prev_manifest,
            current_manifest=curr_manifest,
        )
        pcomp = hcomp.programs["p1"]
        assert pcomp.environment_compatible is False
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W10-CACHE: MOO Cache Validity & Collision Prevention
# ===========================================================================

def test_cache1_valid_report_with_matching_sha_loaded():
    """Valid MOO report with matching source_sha256 is loaded by selector_bridge."""
    tid, name = "W10-CACHE1", "Valid report with matching source_sha256 loaded"
    try:
        from moo.selector_bridge import get_pareto_frontier_for
        import hashlib
        tmpdir = tempfile.mkdtemp()
        try:
            src = os.path.join(tmpdir, "test_cache.c")
            with open(src, "w", encoding="utf-8") as f:
                f.write("int main() { return 0; }\n")
            sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
            rep_data = {
                "schema_version": "moo.report.1.0",
                "source_file": "test_cache.c",
                "source_path": src,
                "source_sha256": sha,
                "pareto_frontier": ["-O2", "-O3"],
                "pareto_dominated": [],
                "pareto_invalid": [],
                "candidates": [],
                "pipeline_error": None,
            }
            with open(os.path.join(tmpdir, "moo_test_cache_c_2026-10-04_12-00-00.json"), "w") as f:
                json.dump(rep_data, f)
            frontier = get_pareto_frontier_for(src, report_dir=tmpdir)
            assert frontier == ["-O2", "-O3"]
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_cache2_mismatched_source_hash_rejected():
    """Report with mismatched source_sha256 is rejected by selector_bridge."""
    tid, name = "W10-CACHE2", "Report with mismatched source_sha256 rejected"
    try:
        from moo.selector_bridge import get_pareto_frontier_for
        tmpdir = tempfile.mkdtemp()
        try:
            src = os.path.join(tmpdir, "test_cache.c")
            with open(src, "w", encoding="utf-8") as f:
                f.write("int main() { return 1; }\n")
            rep_data = {
                "schema_version": "moo.report.1.0",
                "source_file": "test_cache.c",
                "source_path": src,
                "source_sha256": "wrong_hash" * 4,
                "pareto_frontier": ["-O2"],
                "pareto_dominated": [],
                "pareto_invalid": [],
                "candidates": [],
                "pipeline_error": None,
            }
            with open(os.path.join(tmpdir, "moo_test_cache_c_2026-10-04_12-00-00.json"), "w") as f:
                json.dump(rep_data, f)
            frontier = get_pareto_frontier_for(src, report_dir=tmpdir)
            assert frontier == [], "Mismatched hash must return empty frontier"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_cache3_legacy_unverified_report_rejected():
    """Legacy report lacking schema_version or source_sha256 is rejected as unverified."""
    tid, name = "W10-CACHE3", "Legacy report lacking validation metadata rejected"
    try:
        from moo.selector_bridge import get_pareto_frontier_for
        tmpdir = tempfile.mkdtemp()
        try:
            src = os.path.join(tmpdir, "test_cache.c")
            with open(src, "w", encoding="utf-8") as f:
                f.write("int main() { return 2; }\n")
            rep_data = {
                "source_file": "test_cache.c",
                "source_path": src,
                "pareto_frontier": ["-O2"],
                "pareto_dominated": [],
                "pareto_invalid": [],
                "candidates": [],
                "pipeline_error": None,
            }
            with open(os.path.join(tmpdir, "moo_test_cache_c_2026-10-04_12-00-00.json"), "w") as f:
                json.dump(rep_data, f)
            frontier = get_pareto_frontier_for(src, report_dir=tmpdir)
            assert frontier == [], "Legacy unverified report must return empty frontier"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_cache4_directory_path_collision_prevented():
    """Files with same basename in different directories do not collide incorrectly."""
    tid, name = "W10-CACHE4", "Path collision across directories prevented"
    try:
        from moo.selector_bridge import get_pareto_frontier_for
        import hashlib
        tmpdir = tempfile.mkdtemp()
        dir_a = os.path.join(tmpdir, "dir_a")
        dir_b = os.path.join(tmpdir, "dir_b")
        os.makedirs(dir_a)
        os.makedirs(dir_b)
        try:
            src_a = os.path.join(dir_a, "main.c")
            src_b = os.path.join(dir_b, "main.c")
            with open(src_a, "w", encoding="utf-8") as f:
                f.write("int main() { return 10; }\n")
            with open(src_b, "w", encoding="utf-8") as f:
                f.write("int main() { return 20; }\n")
            sha_a = hashlib.sha256(open(src_a, "rb").read()).hexdigest()
            rep_data = {
                "schema_version": "moo.report.1.0",
                "source_file": "main.c",
                "source_path": src_a,
                "source_sha256": sha_a,
                "pareto_frontier": ["-O3"],
                "pareto_dominated": [],
                "pareto_invalid": [],
                "candidates": [],
                "pipeline_error": None,
            }
            with open(os.path.join(tmpdir, "moo_main_c_2026-10-04_12-00-00.json"), "w") as f:
                json.dump(rep_data, f)
            frontier_b = get_pareto_frontier_for(src_b, report_dir=tmpdir)
            assert frontier_b == [], "Query for dir_b/main.c must not reuse cache from dir_a/main.c"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


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
    print("TOACD — Week 10 Optimization Regression & Comparison Tests")
    print("=" * 70)

    print("\n--- W10-SCHEMA: Schema Model Validation ---")
    test_schema1_metric_comparison_roundtrip()
    test_schema2_strategy_comparison_roundtrip()
    test_schema3_program_comparison_roundtrip()
    test_schema4_historical_comparison_roundtrip()
    test_schema5_regression_report_roundtrip()
    test_schema6_schema_version_constant()
    test_schema7_text_summary_rendering()

    print("\n--- W10-COMP: Comparisons & Direction Correctness ---")
    test_comp1_baseline_vs_selected_execution_time()
    test_comp2_baseline_vs_selected_regression()
    test_comp3_code_size_direction_correctness()
    test_comp4_security_sinks_direction_correctness()
    test_comp5_all_strategies_compared()
    test_comp6_strategy_vs_strategy_arbitrary_reference()
    test_comp7_percent_calculation_precision()

    print("\n--- W10-REG: Regression, Improvement, & Threshold Detection ---")
    test_reg1_exact_no_change_detection()
    test_reg2_within_threshold_classified_unchanged()
    test_reg3_threshold_boundary_behavior()
    test_reg4_zero_threshold_strictness()
    test_reg5_per_metric_threshold_overrides()
    test_reg6_multi_metric_overall_improved()
    test_reg7_multi_metric_overall_regressed()
    test_reg8_multi_metric_overall_mixed()

    print("\n--- W10-HIST: Cross-Run Historical Comparisons ---")
    test_hist1_historical_run_delta()
    test_hist2_historical_missing_previous_program()
    test_hist3_historical_missing_current_program()
    test_hist4_historical_failure_in_previous()
    test_hist5_historical_failure_in_current()
    test_hist6_historical_per_strategy_comparison()

    print("\n--- W10-FAIL: Failure Isolation & Missing Metric Handling ---")
    test_fail1_missing_metric_handled_safely()
    test_fail2_nan_and_inf_handled_safely()
    test_fail3_pipeline_error_program_handled()
    test_fail4_malformed_record_dict_handled()
    test_fail5_candidate_without_measurement_handled()
    test_fail6_non_existent_selected_strategy()

    print("\n--- W10-DET: Determinism & Stability ---")
    test_det1_comparison_determinism_50_runs()
    test_det2_report_generation_determinism()
    test_det3_stable_ordering_of_strategies()
    test_det4_report_file_save_and_load_stability()

    print("\n--- W10-SCOPE: Architecture & Scope Guard ---")
    test_scope1_no_week11_comparison_modules()
    test_scope2_week8_scope_guards_unbroken()
    test_scope3_gui_file_untouched()
    test_scope4_optimization_selection_logic_unchanged()
    test_scope5_week9_bench_outputs_reused()

    print("\n--- W10-PROV: Selection Provenance Enforcement ---")
    test_prov1_valid_selection_record_accepted()
    test_prov2_missing_selection_refuses_fabrication()
    test_prov3_mismatched_source_sha256_rejected()
    test_prov4_mismatched_program_id_rejected()
    test_prov5_selection_record_roundtrip()

    print("\n--- W10-NOISE: Noise-Aware Regression & Measurement Reliability ---")
    test_noise1_unreliable_timing_yields_inconclusive()
    test_noise2_delta_within_cv_envelope_yields_inconclusive()
    test_noise3_control_identical_inputs_strictly_unchanged()
    test_noise4_low_noise_confident_classification()

    print("\n--- W10-DERIV: Derived Signals & Metric Families ---")
    test_deriv1_signal_family_grouping()
    test_deriv2_family_status_aggregation()
    test_deriv3_derived_relationships_documented()

    print("\n--- W10-HGUARD: Historical Comparison Guards & Compatibility ---")
    test_hguard1_matching_source_hash_comparable()
    test_hguard2_mismatched_source_hash_incomparable()
    test_hguard3_incompatible_environment_detected()

    print("\n--- W10-CACHE: MOO Cache Validity & Collision Prevention ---")
    test_cache1_valid_report_with_matching_sha_loaded()
    test_cache2_mismatched_source_hash_rejected()
    test_cache3_legacy_unverified_report_rejected()
    test_cache4_directory_path_collision_prevented()

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
