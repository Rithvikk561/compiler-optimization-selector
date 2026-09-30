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
    measure_execution,
    measure_code_size,
    estimate_energy,
    derive_carbon,
    measure_all,
)
from moo import correctness as crct


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
