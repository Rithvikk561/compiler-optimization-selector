"""
moo/tests/test_stage1_measurement.py
Stage 1 focused tests for the measurement foundation.

Tests
-----
T1  TimingStats.from_samples — statistics calculation
T2  measure_execution — repeated timing, raw samples, statistics
T3  measure_code_size — llvm-size .text and fallback
T4  estimate_energy — explicit source, is_estimated=True
T5  derive_carbon — explicit source, is_estimated=True
T6  correctness.compare_executables — TC1 self-match (correct=True)
T7  correctness.compare_executables — security_checks non-zero ref exit code
T8  correctness.check_self_consistent — TC1 determinism
T9  measure_all — end-to-end pipeline

Week 5 additions (measurement quality metadata):
T10 TimingStats.cv — coefficient of variation calculated correctly
T11 MeasurementResult quality counters — n_timeouts, n_errors, timing_is_reliable
T12 timing_is_reliable — calls measure_execution(), tests True/False (mock-based)

Week 5 Change 1b — defect fixes + clang-free reliability tests:
T13 timeout counted exactly once, NOT in n_errors (mock-based)
T14 non-zero exit code not counted as error (mock-based)
T15 fewer than 5 valid samples => timing_is_reliable False (mock-based)
T16 timeout present => timing_is_reliable False (mock-based)
T17 subprocess error present => timing_is_reliable False (mock-based)
T18 median zero => timing_is_reliable False (mock-based)
T19 CV threshold boundary — below -> True, above -> False (mock-based)
T20 warmup runs excluded from n_timeouts and n_errors (mock-based)
T21 existing median/energy/carbon values unchanged by new fields (mock-based)

All tests use TC1_loop_heavy.c and security_checks.c from the existing
test_cases directory.  A temporary build directory is used; no source file
is modified.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import traceback

# Ensure moo package is importable when run as a script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))  # .../Python Scripts/
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo import config
from moo.measurement import (
    TimingStats,
    ExecutionRecord,
    measure_execution,
    measure_code_size,
    estimate_energy,
    derive_carbon,
    measure_all,
)
from moo import correctness as crct
from unittest.mock import patch as _mock_patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

_results: list[tuple[str, str, str]] = []   # (id, name, status_str)


def report(tid: str, name: str, passed: bool, note: str = ""):
    status = PASS if passed else FAIL
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")


def skip(tid: str, name: str, reason: str):
    _results.append((tid, name, "SKIP"))
    print(f"  [{SKIP}] {tid}: {name}  (skipped: {reason})")


def _build_exe(src_path: str, out_exe: str, flag: str = "-O0") -> bool:
    """Compile src_path → out_exe with clang; return True on success."""
    if not config.CLANG_PATH:
        return False
    cmd = [config.CLANG_PATH, flag, src_path, "-o", out_exe]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def t1_timing_stats():
    tid, name = "T1", "TimingStats.from_samples — statistics"
    try:
        samples = [100_000_000, 110_000_000, 90_000_000, 105_000_000, 95_000_000]
        ts = TimingStats.from_samples(samples)
        ok = (
            ts.n_samples == 5
            and ts.min_ns == 90_000_000
            and ts.max_ns == 110_000_000
            and abs(ts.mean_ns - 100_000_000) < 1
            and ts.stdev_ns > 0
            and ts.median_s == ts.median_ns / 1e9
        )
        # Single-sample edge case
        ts1 = TimingStats.from_samples([42])
        ok = ok and ts1.stdev_ns == 0.0 and ts1.n_samples == 1
        report(tid, name, ok)
    except Exception as exc:
        report(tid, name, False, str(exc))


def t2_measure_execution(tc1_exe: str | None):
    tid, name = "T2", "measure_execution — raw samples, statistics"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        res = measure_execution(
            tc1_exe,
            strategy="-O0",
            warmup_runs=2,
            measure_runs=5,
        )
        ok = (
            len(res.raw_samples_ns) == 5
            and res.timing is not None
            and res.timing.n_samples == 5
            and res.timing.min_ns <= res.timing.median_ns <= res.timing.max_ns
            and res.timing.stdev_ns >= 0
            and len(res.all_return_codes) == 5
            and res.last_return_code is not None
        )
        note = (
            f"median={res.timing.median_s*1000:.2f}ms "
            f"stdev={res.timing.stdev_ns/1e6:.3f}ms"
            if res.timing else ""
        )
        report(tid, name, ok, note)
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t3_code_size(tc1_exe: str | None):
    tid, name = "T3", "measure_code_size — .text section or fallback"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        cs = measure_code_size(tc1_exe)
        ok = (
            cs.file_size_bytes > 0
            and cs.primary_value > 0
            and cs.size_source != ""
            and cs.primary_metric in ("text_size_bytes", "file_size_bytes")
        )
        if cs.text_size_bytes is not None:
            note = (
                f".text={cs.text_size_bytes}B file={cs.file_size_bytes}B "
                f"source={cs.size_source!r}"
            )
        else:
            note = f"fallback file={cs.file_size_bytes}B source={cs.size_source!r}"
        report(tid, name, ok, note)
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t4_energy():
    tid, name = "T4", "estimate_energy — explicit source, is_estimated=True"
    try:
        en = estimate_energy(1.0)  # 1 second
        ok = (
            en.energy_is_estimated is True
            and en.energy_joules > 0
            and "estimated" in en.energy_source.lower()
            and str(config.CPU_TDP_WATTS) in en.energy_source
        )
        report(tid, name, ok, f"energy={en.energy_joules:.4f}J source={en.energy_source!r}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def t5_carbon():
    tid, name = "T5", "derive_carbon — explicit source, is_estimated=True"
    try:
        en = estimate_energy(1.0)
        co = derive_carbon(en)
        ok = (
            co.carbon_is_estimated is True
            and co.carbon_grams > 0
            and co.grid_intensity_g_per_kwh == config.GRID_INTENSITY_G_PER_KWH
            and co.grid_intensity_source != ""
            and co.energy_source != ""
        )
        report(tid, name, ok,
               f"carbon={co.carbon_grams:.6f}g intensity={co.grid_intensity_g_per_kwh}gCO2eq/kWh")
    except Exception as exc:
        report(tid, name, False, str(exc))


def t6_correctness_tc1(tc1_exe: str | None):
    """Self-match: reference == candidate, so correct must be True."""
    tid, name = "T6", "correctness.compare_executables — TC1 self-match (correct=True)"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        res = crct.compare_executables(tc1_exe, tc1_exe)
        ok = (
            res.checked is True
            and res.correct is True
            and res.exit_code_match is True
            and res.stdout_match is True
        )
        report(tid, name, ok,
               f"correct={res.correct} exit_code_match={res.exit_code_match} details={res.details!r}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t7_correctness_security(sc_ref_exe: str | None, sc_o2_exe: str | None):
    """
    security_checks may return a non-zero exit code.
    A self-match must still report correct=True.
    """
    tid, name = "T7", "correctness — security_checks non-zero ref exit code handled"
    if not sc_ref_exe:
        skip(tid, name, "security_checks reference executable not built")
        return
    try:
        # First, confirm the reference actually has a non-zero exit code
        import subprocess as _sp
        r = _sp.run([sc_ref_exe], capture_output=True, timeout=10)
        ref_rc = r.returncode
        print(f"        security_checks reference exit code: {ref_rc}")

        # Self-match must be correct even with non-zero exit code
        res_self = crct.compare_executables(sc_ref_exe, sc_ref_exe)
        ok_self = res_self.correct is True and res_self.exit_code_match is True

        # If we have an O2 build, compare against it too
        if sc_o2_exe and os.path.isfile(sc_o2_exe):
            res_o2 = crct.compare_executables(sc_ref_exe, sc_o2_exe)
            print(f"        O2 vs ref: correct={res_o2.correct} "
                  f"ref_rc={res_o2.reference_exit_code} cand_rc={res_o2.candidate_exit_code}")
            note = (
                f"self_match=PASS ref_rc={ref_rc} O2_correct={res_o2.correct}"
            )
        else:
            note = f"self_match=PASS ref_rc={ref_rc} (no O2 build for cross-compare)"

        report(tid, name, ok_self, note)
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t8_self_consistent(tc1_exe: str | None):
    tid, name = "T8", "correctness.check_self_consistent — TC1 determinism"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        res = crct.check_self_consistent(tc1_exe, n_runs=3)
        ok = res.checked is True and res.correct is True
        report(tid, name, ok, f"correct={res.correct} details={res.details!r}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t9_measure_all(tc1_exe: str | None):
    tid, name = "T9", "measure_all — end-to-end pipeline"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        res = measure_all(tc1_exe, strategy="-O0", warmup_runs=1, measure_runs=3)
        ok = (
            res.timing is not None
            and res.code_size is not None
            and res.energy is not None
            and res.carbon is not None
            and res.energy.energy_is_estimated is True
            and res.carbon.carbon_is_estimated is True
            and len(res.raw_samples_ns) == 3
        )
        d = res.to_dict()
        ok = ok and isinstance(d["timing"], dict) and isinstance(d["code_size"], dict)
        report(tid, name, ok,
               f"timing={res.timing.median_s*1000:.2f}ms "
               f"code_size={res.code_size.primary_value}B "
               f"energy={res.energy.energy_joules:.4f}J "
               f"carbon={res.carbon.carbon_grams:.6f}g")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Week 5 — Measurement quality metadata tests
# ---------------------------------------------------------------------------

def t10_timing_stats_cv():
    """T10: TimingStats.cv — coefficient of variation calculated correctly."""
    tid, name = "T10", "TimingStats.cv — coefficient of variation"
    try:
        # Known samples: stdev / median should equal cv.
        import statistics as _st
        samples = [100_000_000, 110_000_000, 90_000_000, 105_000_000, 95_000_000]
        ts = TimingStats.from_samples(samples)

        expected_cv = _st.stdev(samples) / _st.median(samples)
        cv_close = abs(ts.cv - expected_cv) < 1e-12

        # Single-sample edge case: cv must be 0.0
        ts1 = TimingStats.from_samples([42_000_000])
        cv_single_zero = ts1.cv == 0.0

        # n_timeouts defaults to 0 when not supplied
        ts_no_to = TimingStats.from_samples([100_000_000, 200_000_000])
        n_to_default_zero = ts_no_to.n_timeouts == 0

        # n_timeouts is passed through correctly
        ts_with_to = TimingStats.from_samples([100_000_000, 200_000_000], n_timeouts=1)
        n_to_passed = ts_with_to.n_timeouts == 1

        # cv and n_timeouts appear in to_dict()
        d = ts.to_dict()
        dict_has_cv = "cv" in d and "n_timeouts" in d

        ok = cv_close and cv_single_zero and n_to_default_zero and n_to_passed and dict_has_cv
        report(tid, name, ok,
               f"cv={ts.cv:.6f} expected={expected_cv:.6f} "
               f"single_zero={cv_single_zero} to_dict_ok={dict_has_cv}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t11_measurement_result_quality_counters(tc1_exe: str | None):
    """T11: MeasurementResult — n_timeouts, n_errors, timing_is_reliable present."""
    tid, name = "T11", "MeasurementResult — n_timeouts, n_errors, timing_is_reliable"
    if not tc1_exe:
        skip(tid, name, "TC1 executable not built")
        return
    try:
        res = measure_execution(
            tc1_exe,
            strategy="-O0",
            warmup_runs=1,
            measure_runs=5,
        )
        # All three new fields must exist with the correct types
        has_n_timeouts = isinstance(res.n_timeouts, int)
        has_n_errors = isinstance(res.n_errors, int)
        has_reliable = res.timing_is_reliable is True or res.timing_is_reliable is False

        # For a clean short-lived process: no timeouts, no errors expected
        no_unexpected_timeouts = res.n_timeouts == 0
        no_unexpected_errors = res.n_errors == 0

        # n_timeouts from MeasurementResult must match timing.n_timeouts
        timing_n_to_match = (
            res.timing is not None
            and res.timing.n_timeouts == res.n_timeouts
        )

        # to_dict() must carry all three new keys
        d = res.to_dict()
        dict_keys_ok = (
            "n_timeouts" in d
            and "n_errors" in d
            and "timing_is_reliable" in d
        )

        ok = (
            has_n_timeouts
            and has_n_errors
            and has_reliable
            and no_unexpected_timeouts
            and no_unexpected_errors
            and timing_n_to_match
            and dict_keys_ok
        )
        report(tid, name, ok,
               f"n_timeouts={res.n_timeouts} n_errors={res.n_errors} "
               f"timing_is_reliable={res.timing_is_reliable} "
               f"cv={res.timing.cv:.4f}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t12_timing_is_reliable_threshold():
    """T12: timing_is_reliable — calls measure_execution(), tests True/False via mock."""
    tid, name = "T12", "timing_is_reliable — measure_execution() integration (mock)"
    try:
        # Below threshold: 5 identical 100ms samples.
        # n_samples=5 >= MIN_RELIABLE_SAMPLES, cv=0.0, no timeouts/errors, median>0
        # => timing_is_reliable must be True
        low_cv_recs = [_ok_rec(100_000_000)] * 5
        res_low = _mock_measure([], low_cv_recs)
        low_reliable = res_low.timing_is_reliable is True

        # Above threshold: 5 samples with huge spread -> cv >> CV_WARN_THRESHOLD
        # => timing_is_reliable must be False
        high_cv_recs = [
            _ok_rec(100_000_000),
            _ok_rec(100_000_000_000),   # 100s — vastly inflates stdev
            _ok_rec(100_000_000),
            _ok_rec(100_000_000_000),
            _ok_rec(100_000_000),
        ]
        res_high = _mock_measure([], high_cv_recs)
        high_unreliable = res_high.timing_is_reliable is False

        ok = low_reliable and high_unreliable
        report(tid, name, ok,
               f"low(cv={res_low.timing.cv:.4f})->reliable={res_low.timing_is_reliable} | "
               f"high(cv={res_high.timing.cv:.4f})->reliable={res_high.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Week 5 Change 1b — clang-free mock helpers
# ---------------------------------------------------------------------------

def _ok_rec(elapsed_ns: int) -> ExecutionRecord:
    """Successful run: no error, return code 0."""
    return ExecutionRecord(
        return_code=0, stdout="", stderr="", elapsed_ns=elapsed_ns
    )


def _timeout_rec(elapsed_ns: int = 30_000_000_000) -> ExecutionRecord:
    """Timed-out run: timed_out=True AND error set."""
    return ExecutionRecord(
        return_code=-1, stdout="", stderr="",
        elapsed_ns=elapsed_ns, timed_out=True,
        error="TimeoutExpired after 30s",
    )


def _error_rec() -> ExecutionRecord:
    """Subprocess-level error run (not a timeout): error set, timed_out=False."""
    return ExecutionRecord(
        return_code=-1, stdout="", stderr="",
        elapsed_ns=0, timed_out=False,
        error="OSError: [Errno 2] No such file or directory",
    )


def _nonzero_rec(elapsed_ns: int, rc: int = 1) -> ExecutionRecord:
    """Non-zero exit code run — valid, timed, NOT an error."""
    return ExecutionRecord(
        return_code=rc, stdout="output", stderr="", elapsed_ns=elapsed_ns
    )


def _mock_measure(
    warmup_recs: list[ExecutionRecord],
    measure_recs: list[ExecutionRecord],
) -> object:
    """
    Call measure_execution() with mocked _run_once records.
    Patches os.path.isfile so no real executable is needed.
    warmup_recs are consumed first, then measure_recs.
    """
    side_effects = list(warmup_recs) + list(measure_recs)
    with _mock_patch("moo.measurement._run_once") as mock_run, \
         _mock_patch("moo.measurement.os.path.isfile", return_value=True):
        mock_run.side_effect = side_effects
        return measure_execution(
            exe_path="__mock__.exe",
            strategy="test",
            warmup_runs=len(warmup_recs),
            measure_runs=len(measure_recs),
        )


# ---------------------------------------------------------------------------
# Week 5 Change 1b — clang-free reliability tests (T13–T21)
# ---------------------------------------------------------------------------

def t13_timeout_counted_once_not_in_errors():
    """T13: timeout increments n_timeouts exactly once and NOT n_errors."""
    tid, name = "T13", "timeout counted once — NOT in n_errors (mock)"
    try:
        # 4 normal runs + 1 timeout
        recs = [_ok_rec(100_000_000)] * 4 + [_timeout_rec()]
        res = _mock_measure([], recs)

        timeout_counted_once = res.n_timeouts == 1
        timeout_not_in_errors = res.n_errors == 0
        # Only the 4 normal runs land in raw_samples_ns (timeout is excluded)
        raw_count_correct = len(res.raw_samples_ns) == 4

        ok = timeout_counted_once and timeout_not_in_errors and raw_count_correct
        report(tid, name, ok,
               f"n_timeouts={res.n_timeouts} n_errors={res.n_errors} "
               f"len(raw_samples_ns)={len(res.raw_samples_ns)}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t14_nonzero_exit_code_not_an_error():
    """T14: non-zero exit code is a valid timed run — NOT counted as error."""
    tid, name = "T14", "non-zero exit code not counted as error (mock)"
    try:
        # 5 runs that return exit code 1 — not errors, not timeouts
        recs = [_nonzero_rec(100_000_000, rc=1)] * 5
        res = _mock_measure([], recs)

        no_timeouts = res.n_timeouts == 0
        no_errors = res.n_errors == 0
        all_timed = len(res.raw_samples_ns) == 5
        all_rcs_nonzero = all(rc == 1 for rc in res.all_return_codes)

        ok = no_timeouts and no_errors and all_timed and all_rcs_nonzero
        report(tid, name, ok,
               f"n_timeouts={res.n_timeouts} n_errors={res.n_errors} "
               f"len(raw)={len(res.raw_samples_ns)} rcs={res.all_return_codes}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t15_fewer_than_5_samples_unreliable():
    """T15: fewer than MIN_RELIABLE_SAMPLES valid samples => timing_is_reliable False."""
    tid, name = "T15", "< MIN_RELIABLE_SAMPLES samples => unreliable (mock)"
    try:
        # Only 4 valid samples — below the minimum of 5
        recs = [_ok_rec(100_000_000)] * 4
        res = _mock_measure([], recs)

        has_timing = res.timing is not None
        n_samples_short = res.timing.n_samples == 4
        unreliable = res.timing_is_reliable is False

        ok = has_timing and n_samples_short and unreliable
        report(tid, name, ok,
               f"n_samples={res.timing.n_samples} "
               f"MIN_RELIABLE_SAMPLES={config.MIN_RELIABLE_SAMPLES} "
               f"timing_is_reliable={res.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t16_timeout_present_unreliable():
    """T16: n_timeouts > 0 => timing_is_reliable False even when n_samples >= 5."""
    tid, name = "T16", "timeout present => unreliable (mock)"
    try:
        # 5 valid runs + 1 timeout: n_samples==5 >= 5, but n_timeouts=1
        recs = [_ok_rec(100_000_000)] * 5 + [_timeout_rec()]
        res = _mock_measure([], recs)

        n_samples_ok = res.timing.n_samples == 5
        timeout_recorded = res.n_timeouts == 1
        no_errors = res.n_errors == 0
        unreliable = res.timing_is_reliable is False

        ok = n_samples_ok and timeout_recorded and no_errors and unreliable
        report(tid, name, ok,
               f"n_samples={res.timing.n_samples} n_timeouts={res.n_timeouts} "
               f"n_errors={res.n_errors} timing_is_reliable={res.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t17_subprocess_error_present_unreliable():
    """T17: n_errors > 0 => timing_is_reliable False even when n_samples >= 5."""
    tid, name = "T17", "subprocess error present => unreliable (mock)"
    try:
        # 5 valid runs + 1 subprocess error (not timeout)
        recs = [_ok_rec(100_000_000)] * 5 + [_error_rec()]
        res = _mock_measure([], recs)

        n_samples_ok = res.timing.n_samples == 5
        error_recorded = res.n_errors == 1
        no_timeouts = res.n_timeouts == 0
        unreliable = res.timing_is_reliable is False

        ok = n_samples_ok and error_recorded and no_timeouts and unreliable
        report(tid, name, ok,
               f"n_samples={res.timing.n_samples} n_errors={res.n_errors} "
               f"n_timeouts={res.n_timeouts} timing_is_reliable={res.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t18_median_zero_unreliable():
    """T18: median_ns == 0 => timing_is_reliable False."""
    tid, name = "T18", "median_ns == 0 => unreliable (mock)"
    try:
        # 5 runs all returning elapsed_ns=0
        recs = [_ok_rec(0)] * 5
        res = _mock_measure([], recs)

        median_is_zero = res.timing.median_ns == 0.0
        unreliable = res.timing_is_reliable is False

        ok = median_is_zero and unreliable
        report(tid, name, ok,
               f"median_ns={res.timing.median_ns} "
               f"timing_is_reliable={res.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t19_cv_threshold_boundary():
    """T19: at/below threshold -> True; above threshold -> False."""
    tid, name = "T19", "CV threshold boundary — below->True, above->False (mock)"
    try:
        threshold = config.CV_WARN_THRESHOLD  # default 0.10

        # Below threshold: 5 identical samples — cv exactly 0.0 <= 0.10
        recs_low = [_ok_rec(100_000_000)] * 5
        res_low = _mock_measure([], recs_low)
        below_ok = res_low.timing_is_reliable is True

        # Above threshold: 5 samples with large spread — cv >> 0.10
        # [100ms, 100s, 100ms, 100s, 100ms] -> huge stdev, cv >> threshold
        recs_high = [
            _ok_rec(100_000_000),
            _ok_rec(100_000_000_000),
            _ok_rec(100_000_000),
            _ok_rec(100_000_000_000),
            _ok_rec(100_000_000),
        ]
        res_high = _mock_measure([], recs_high)
        above_ok = (
            res_high.timing.cv > threshold
            and res_high.timing_is_reliable is False
        )

        ok = below_ok and above_ok
        report(tid, name, ok,
               f"low_cv={res_low.timing.cv:.4f}->reliable={res_low.timing_is_reliable} | "
               f"high_cv={res_high.timing.cv:.4f}->reliable={res_high.timing_is_reliable} "
               f"threshold={threshold}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t20_warmup_runs_not_counted():
    """T20: timeout/error in warmup runs are NOT counted in n_timeouts/n_errors."""
    tid, name = "T20", "warmup runs excluded from n_timeouts/n_errors (mock)"
    try:
        # Warmup: 1 timeout + 1 error.  Measure: 5 clean normal runs.
        warmup = [_timeout_rec(), _error_rec()]
        measure = [_ok_rec(100_000_000)] * 5
        res = _mock_measure(warmup, measure)

        no_timeouts = res.n_timeouts == 0
        no_errors = res.n_errors == 0
        all_five_timed = len(res.raw_samples_ns) == 5
        reliable = res.timing_is_reliable is True

        ok = no_timeouts and no_errors and all_five_timed and reliable
        report(tid, name, ok,
               f"warmup_recs=2 (1 timeout+1 error) measure_recs=5 | "
               f"n_timeouts={res.n_timeouts} n_errors={res.n_errors} "
               f"len(raw)={len(res.raw_samples_ns)} reliable={res.timing_is_reliable}")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


def t21_median_energy_carbon_unchanged():
    """T21: adding quality fields does NOT change median, energy, or carbon values."""
    tid, name = "T21", "median/energy/carbon unchanged by quality fields (mock)"
    try:
        # 5 identical 100ms (100_000_000 ns) runs.
        # Expected: median_s = 0.1
        #           energy_joules = 0.1 * 45.0 * 1.0 = 4.5
        #           carbon_grams  = 4.5 * 436.0 / 3_600_000
        recs = [_ok_rec(100_000_000)] * 5
        res = _mock_measure([], recs)

        expected_median_s = 0.1
        expected_energy_j = expected_median_s * config.CPU_TDP_WATTS * config.CPU_UTILISATION
        expected_carbon_g = (
            expected_energy_j * config.GRID_INTENSITY_G_PER_KWH / 3_600_000.0
        )

        median_ok = abs(res.timing.median_s - expected_median_s) < 1e-9
        energy_ok = abs(res.energy.energy_joules - expected_energy_j) < 1e-9
        carbon_ok = abs(res.carbon.carbon_grams - expected_carbon_g) < 1e-12

        ok = median_ok and energy_ok and carbon_ok
        report(tid, name, ok,
               f"median_s={res.timing.median_s:.4f} (expected {expected_median_s}) | "
               f"energy_J={res.energy.energy_joules:.4f} (expected {expected_energy_j:.4f}) | "
               f"carbon_g={res.carbon.carbon_grams:.8f} (expected {expected_carbon_g:.8f})")
    except Exception as exc:
        report(tid, name, False, str(exc))
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 65)
    print("TOACD MOO Stage 1 — Measurement Foundation Tests")
    print("=" * 65)

    # Environment check
    print(f"\n  CLANG_PATH    : {config.CLANG_PATH}")
    print(f"  LLVM_SIZE_PATH: {config.LLVM_SIZE_PATH}")
    print(f"  WARMUP_RUNS   : {config.WARMUP_RUNS}")
    print(f"  MEASURE_RUNS  : {config.MEASURE_RUNS}")
    print(f"  TEST_FILE_TC1 : {config.TEST_FILE_TC1}")
    print(f"  TEST_FILE_SC  : {config.TEST_FILE_SC}")

    # Build test executables in a temporary directory
    tmpdir = tempfile.mkdtemp(prefix="toacd_stage1_test_")
    print(f"\n  Build directory: {tmpdir}")

    tc1_exe = None
    sc_ref_exe = None
    sc_o2_exe = None

    try:
        if config.CLANG_PATH:
            if config.TEST_FILE_TC1:
                tc1_path = os.path.join(tmpdir, "tc1.exe")
                if _build_exe(config.TEST_FILE_TC1, tc1_path, "-O0"):
                    tc1_exe = tc1_path
                    print(f"  Built: {tc1_exe}")
                else:
                    print("  WARNING: TC1 build failed")
            else:
                print("  WARNING: TC1_loop_heavy.c not found")

            if config.TEST_FILE_SC:
                sc_ref_path = os.path.join(tmpdir, "sc_ref.exe")
                if _build_exe(config.TEST_FILE_SC, sc_ref_path, "-O0"):
                    sc_ref_exe = sc_ref_path
                    print(f"  Built: {sc_ref_exe}")
                else:
                    print("  WARNING: security_checks reference build failed")

                sc_o2_path = os.path.join(tmpdir, "sc_o2.exe")
                if _build_exe(config.TEST_FILE_SC, sc_o2_path, "-O2"):
                    sc_o2_exe = sc_o2_path
                    print(f"  Built: {sc_o2_exe}")
                else:
                    print("  INFO: security_checks -O2 build failed (optional)")
            else:
                print("  WARNING: security_checks.c not found")
        else:
            print("  WARNING: clang not found — executable tests will be skipped")

        print("\n" + "-" * 65)
        print("Running tests...")
        print("-" * 65)

        t1_timing_stats()
        t2_measure_execution(tc1_exe)
        t3_code_size(tc1_exe)
        t4_energy()
        t5_carbon()
        t6_correctness_tc1(tc1_exe)
        t7_correctness_security(sc_ref_exe, sc_o2_exe)
        t8_self_consistent(tc1_exe)
        t9_measure_all(tc1_exe)
        # Week 5 quality-metadata tests
        t10_timing_stats_cv()
        t11_measurement_result_quality_counters(tc1_exe)
        t12_timing_is_reliable_threshold()
        # Week 5 Change 1b — clang-free reliability tests
        t13_timeout_counted_once_not_in_errors()
        t14_nonzero_exit_code_not_an_error()
        t15_fewer_than_5_samples_unreliable()
        t16_timeout_present_unreliable()
        t17_subprocess_error_present_unreliable()
        t18_median_zero_unreliable()
        t19_cv_threshold_boundary()
        t20_warmup_runs_not_counted()
        t21_median_energy_carbon_unchanged()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Summary
    print("\n" + "=" * 65)
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
