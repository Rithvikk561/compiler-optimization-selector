"""
moo/tests/test_stage3_integration.py
Stage 3 integration tests — real pipeline runs on existing test programs.

These tests REQUIRE:
  - clang (from config.CLANG_PATH)
  - TC1_loop_heavy.c
  - security_checks.c

Each test runs the complete evaluate_program() pipeline and verifies the
full contract:
  - baseline is measured
  - all 9 strategies are attempted
  - failed strategies recorded (not crashing the whole run)
  - correctness checked
  - invalid candidates not in Pareto
  - valid candidates normalized
  - Pareto frontier produced
  - security_checks non-zero exit code handled correctly
  - JSON report is serializable
"""

from __future__ import annotations

import json
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo import config
from moo.pipeline import evaluate_program
from moo.cli_report import print_moo_summary, save_moo_report


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

PASS_S = "\033[32mPASS\033[0m"
FAIL_S = "\033[31mFAIL\033[0m"
SKIP_S = "\033[33mSKIP\033[0m"
_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = ""):
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    status = PASS_S if passed else FAIL_S
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")


def skip(tid: str, name: str, reason: str):
    _results.append((tid, name, "SKIP"))
    print(f"  [{SKIP_S}] {tid}: {name}  (skipped: {reason})")


# ---------------------------------------------------------------------------
# TC1 integration tests
# ---------------------------------------------------------------------------

_tc1_result = None   # cached so tests share one run
_sc_result = None


def _run_tc1():
    global _tc1_result
    if _tc1_result is not None:
        return _tc1_result
    print(f"\n  Running pipeline on TC1_loop_heavy.c ...")
    _tc1_result = evaluate_program(
        source_path=config.TEST_FILE_TC1,
        source_name="TC1_loop_heavy.c",
        warmup_runs=1,     # keep integration test fast
        measure_runs=3,
    )
    return _tc1_result


def _run_sc():
    global _sc_result
    if _sc_result is not None:
        return _sc_result
    print(f"\n  Running pipeline on security_checks.c ...")
    _sc_result = evaluate_program(
        source_path=config.TEST_FILE_SC,
        source_name="security_checks.c",
        warmup_runs=1,
        measure_runs=3,
    )
    return _sc_result


# ---------------------------------------------------------------------------
# TC1 tests
# ---------------------------------------------------------------------------

def i1_tc1_pipeline_runs():
    tid, name = "I1", "TC1: pipeline runs without exception"
    if not config.TEST_FILE_TC1:
        skip(tid, name, "TC1_loop_heavy.c not found")
        return
    if not config.CLANG_PATH:
        skip(tid, name, "clang not available")
        return
    r = _run_tc1()
    ok = r is not None and r.pipeline_error is None
    report(tid, name, ok, f"pipeline_error={r.pipeline_error!r}")


def i2_tc1_baseline_measured():
    tid, name = "I2", "TC1: baseline is measured with timing"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    b = r.baseline
    ok = (
        b is not None
        and b.build_ok
        and b.measurement is not None
        and b.measurement.get("timing") is not None
        and b.measurement["timing"].get("median_s", 0) > 0
    )
    med = b.measurement["timing"].get("median_s") if b and b.measurement else None
    report(tid, name, ok, f"baseline_median_s={med}")


def i3_tc1_all_9_strategies_attempted():
    tid, name = "I3", "TC1: all 9 strategies attempted"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    n = len(r.candidates)
    expected = len(config.ACTIONS)
    ok = n == expected
    report(tid, name, ok, f"got {n}, expected {expected}")


def i4_tc1_failures_recorded_not_crash():
    tid, name = "I4", "TC1: failed strategies recorded, not exception"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    # Any INVALID candidate must have build_error or correctness_details set
    ok = True
    for c in r.candidates:
        if c.pareto_status == "INVALID":
            if not c.build_error and not c.correctness_details:
                ok = False
                print(f"    INVALID candidate {c.strategy_name!r} has no failure details")
    report(tid, name, ok, f"n_invalid={r.n_invalid()}")


def i5_tc1_correctness_checked():
    tid, name = "I5", "TC1: correctness is checked for every built candidate"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    not_checked = [c for c in r.candidates if c.build_ok and not c.correctness_checked]
    ok = len(not_checked) == 0
    report(tid, name, ok, f"not_checked={[c.strategy_name for c in not_checked]}")


def i6_tc1_invalid_not_in_pareto():
    tid, name = "I6", "TC1: invalid candidates not in Pareto frontier/dominated"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    ok = True
    for c in r.candidates:
        if c.pareto_status == "INVALID":
            if c.strategy_name in r.pareto_frontier or c.strategy_name in r.pareto_dominated:
                ok = False
                print(f"    {c.strategy_name!r} is INVALID but appears in Pareto")
    report(tid, name, ok)


def i7_tc1_valid_normalized():
    tid, name = "I7", "TC1: valid candidates have normalized objectives"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    valid_without_norm = [
        c for c in r.candidates
        if c.is_valid() and c.normalized is None
    ]
    ok = len(valid_without_norm) == 0
    report(tid, name, ok,
           f"valid_without_norm={[c.strategy_name for c in valid_without_norm]}")


def i8_tc1_pareto_frontier_exists():
    tid, name = "I8", "TC1: Pareto frontier is produced (non-empty when valid candidates exist)"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    if r.n_valid() == 0:
        skip(tid, name, "no valid candidates — cannot verify frontier"); return
    ok = len(r.pareto_frontier) > 0
    report(tid, name, ok, f"frontier={r.pareto_frontier}")


def i9_tc1_json_serializable():
    tid, name = "I9", "TC1: full result is JSON-serializable"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    try:
        s = json.dumps(r.to_dict(), default=str)
        ok = len(s) > 100
    except Exception as exc:
        ok = False
        report(tid, name, False, str(exc))
        return
    report(tid, name, ok, f"json_len={len(s)}")


# ---------------------------------------------------------------------------
# security_checks tests
# ---------------------------------------------------------------------------

def i10_sc_pipeline_runs():
    tid, name = "I10", "security_checks: pipeline runs without exception"
    if not config.TEST_FILE_SC:
        skip(tid, name, "security_checks.c not found"); return
    if not config.CLANG_PATH:
        skip(tid, name, "clang unavailable"); return
    r = _run_sc()
    ok = r is not None and r.pipeline_error is None
    report(tid, name, ok, f"pipeline_error={r.pipeline_error!r}")


def i11_sc_nonzero_reference_handled():
    tid, name = "I11", "security_checks: non-zero reference exit code correctly captured"
    if not config.TEST_FILE_SC or not config.CLANG_PATH:
        skip(tid, name, "security_checks or clang unavailable"); return
    r = _run_sc()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    b = r.baseline
    ok = b is not None and b.reference_exit_code is not None
    ref_rc = b.reference_exit_code if b else None
    report(tid, name, ok, f"reference_exit_code={ref_rc}")
    if ok and ref_rc != 0:
        print(f"    (expected: security_checks reference exit code is {ref_rc}, non-zero is correct)")


def i12_sc_correctness_uses_reference_not_zero():
    tid, name = "I12", "security_checks: correctness compares to reference, not zero"
    if not config.TEST_FILE_SC or not config.CLANG_PATH:
        skip(tid, name, "security_checks or clang unavailable"); return
    r = _run_sc()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    b = r.baseline
    if not b or b.reference_exit_code == 0:
        skip(tid, name, "reference exit code is 0 — non-zero case not triggered"); return

    # Check that at least one correct candidate has a non-zero exit code
    correct_with_nonzero = [
        c for c in r.candidates
        if c.correct and c.candidate_exit_code is not None and c.candidate_exit_code != 0
    ]
    # Check that NO correct candidate with a matching non-zero exit code was marked invalid
    falsely_invalid = [
        c for c in r.candidates
        if c.candidate_exit_code == b.reference_exit_code
        and c.pareto_status == "INVALID"
        and not c.build_error  # it built OK but correctness failed?
    ]
    ok = len(falsely_invalid) == 0
    report(tid, name, ok,
           f"correct_with_nonzero_rc={len(correct_with_nonzero)} "
           f"falsely_invalid={[c.strategy_name for c in falsely_invalid]}")


def i13_sc_all_strategies_attempted():
    tid, name = "I13", "security_checks: all strategies attempted"
    if not config.TEST_FILE_SC or not config.CLANG_PATH:
        skip(tid, name, "security_checks or clang unavailable"); return
    r = _run_sc()
    if r.pipeline_error:
        skip(tid, name, f"pipeline error: {r.pipeline_error}"); return
    ok = len(r.candidates) == len(config.ACTIONS)
    report(tid, name, ok, f"got {len(r.candidates)}, expected {len(config.ACTIONS)}")


def i14_sc_json_serializable():
    tid, name = "I14", "security_checks: full result is JSON-serializable"
    if not config.TEST_FILE_SC or not config.CLANG_PATH:
        skip(tid, name, "security_checks or clang unavailable"); return
    r = _run_sc()
    try:
        s = json.dumps(r.to_dict(), default=str)
        ok = len(s) > 100
    except Exception as exc:
        report(tid, name, False, str(exc)); return
    report(tid, name, ok, f"json_len={len(s)}")


# ---------------------------------------------------------------------------
# Report printing test (non-crashing)
# ---------------------------------------------------------------------------

def i15_cli_report_prints():
    tid, name = "I15", "CLI report prints without exception"
    if not config.TEST_FILE_TC1 or not config.CLANG_PATH:
        skip(tid, name, "TC1 or clang unavailable"); return
    r = _run_tc1()
    import io
    buf = io.StringIO()
    try:
        print_moo_summary(r, file=buf)
        output = buf.getvalue()
        ok = "Pareto" in output or "frontier" in output.lower()
    except Exception as exc:
        report(tid, name, False, str(exc)); return
    report(tid, name, ok, f"output_len={len(output)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print("TOACD MOO Stage 3 - Integration Tests")
    print("=" * 65)
    print(f"\n  CLANG_PATH    : {config.CLANG_PATH}")
    print(f"  OPT_PATH      : {config.OPT_PATH}")
    print(f"  N_ACTIONS     : {len(config.ACTIONS)}")
    print(f"  TEST_FILE_TC1 : {config.TEST_FILE_TC1}")
    print(f"  TEST_FILE_SC  : {config.TEST_FILE_SC}")

    print("\n--- TC1_loop_heavy.c tests ---")
    i1_tc1_pipeline_runs()
    i2_tc1_baseline_measured()
    i3_tc1_all_9_strategies_attempted()
    i4_tc1_failures_recorded_not_crash()
    i5_tc1_correctness_checked()
    i6_tc1_invalid_not_in_pareto()
    i7_tc1_valid_normalized()
    i8_tc1_pareto_frontier_exists()
    i9_tc1_json_serializable()

    print("\n--- security_checks.c tests ---")
    i10_sc_pipeline_runs()
    i11_sc_nonzero_reference_handled()
    i12_sc_correctness_uses_reference_not_zero()
    i13_sc_all_strategies_attempted()
    i14_sc_json_serializable()

    print("\n--- Report printing ---")
    i15_cli_report_prints()

    # Print full summaries for both programs
    if _tc1_result and not _tc1_result.pipeline_error:
        print_moo_summary(_tc1_result)
    if _sc_result and not _sc_result.pipeline_error:
        print_moo_summary(_sc_result)

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
