"""
moo/tests/test_stage4_integration.py — Stage 4 integration tests.

Tests the full selector_bridge ↔ cached-report ↔ optimization_selector chain
using REAL moo_*.json reports that were produced by the Stage 3 pipeline.

Test plan
---------
I1  get_pareto_frontier_for(TC1_loop_heavy.c) → non-empty list from real report
I2  get_pareto_frontier_for(security_checks.c) → non-empty list from real report
I3  moo_aware_select with TC1 frontier and real DQN-style q_values → valid strategy
I4  moo_aware_select with security_checks frontier → valid strategy on frontier
I5  MOO filtering actually occurs: chosen strategy is on Pareto frontier
I6  Fallback to argmax when frontier is empty (simulated unavailability)
I7  Fallback works correctly when moo module import path mangled (env simulation)
I8  Cached report is used (no re-run): same call returns same frontier on repeat
I9  invalidate_cache removes only the matching moo_*.json files
I10 Selector smoke test: optimization_selector.get_best_optimization() returns
    a strategy that is on the MOO Pareto frontier for TC1_loop_heavy.c

Requirements
------------
- Real moo_*.json reports must exist in moo/reports/
- clang is NOT required (no live pipeline runs in these tests)
- ml_optimizer_model.pth must exist for I10
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR    = os.path.dirname(_SCRIPT_DIR)          # moo/
_PS_DIR     = os.path.dirname(_MOO_DIR)             # Python Scripts/
_MOO_PARENT = os.path.dirname(_PS_DIR)              # outer compiler-optimization-selector-main/
# For `from moo.xxx` imports
if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)

from moo.selector_bridge import (
    SelectionResult,
    _source_key,
    _find_latest_moo_report,
    get_pareto_frontier_for,
    moo_aware_select,
    invalidate_cache,
)

# ---------------------------------------------------------------------------
# Locate real test files
# ---------------------------------------------------------------------------

# Resolve test cases directory (two levels up from Python Scripts)
_CODES_DIR = os.path.dirname(_PS_DIR)
_TC_DIR    = os.path.join(_CODES_DIR, "test_cases")
TC1_PATH   = os.path.join(_TC_DIR, "TC1_loop_heavy.c")
SC_PATH    = os.path.join(_TC_DIR, "security_checks.c")

_REPORT_DIR = os.path.join(_MOO_DIR, "reports")

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{'PASS' if passed else 'FAIL'}] {tid}: {name}{suffix}")


def skip(tid: str, name: str, reason: str = "") -> None:
    _results.append((tid, name, "SKIP"))
    print(f"  [SKIP] {tid}: {name}  {reason}")


def _real_reports_exist() -> bool:
    """True if the moo/reports/ directory has at least one moo_*.json file."""
    if not os.path.isdir(_REPORT_DIR):
        return False
    return any(
        f.startswith("moo_") and f.endswith(".json")
        for f in os.listdir(_REPORT_DIR)
    )


# Real ACTIONS list from the project (copied so we don't import ml_optimizer)
_ACTIONS = [
    "-O0", "-O1", "-O2", "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
]

# Simulated DQN Q-values that prefer -O3 most strongly
_Q_HIGH_O3 = [0.10, 0.60, 0.55, 0.90, 0.30, 0.20, 0.15, 0.12, 0.08]

# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def i1_tc1_frontier_from_real_report():
    tid = "I1"
    name = "get_pareto_frontier_for(TC1_loop_heavy.c) → non-empty from real report"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    result = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    ok = isinstance(result, list) and len(result) > 0
    report(tid, name, ok, f"frontier={result}")


def i2_sc_frontier_from_real_report():
    tid = "I2"
    name = "get_pareto_frontier_for(security_checks.c) → non-empty from real report"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    result = get_pareto_frontier_for(SC_PATH, report_dir=_REPORT_DIR)
    ok = isinstance(result, list) and len(result) > 0
    report(tid, name, ok, f"frontier={result}")


def i3_moo_aware_select_with_tc1_frontier():
    tid = "I3"
    name = "moo_aware_select with TC1 real frontier → valid SelectionResult"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    frontier = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    r = moo_aware_select(TC1_PATH, _Q_HIGH_O3, _ACTIONS, frontier)
    ok = (
        isinstance(r, SelectionResult)
        and isinstance(r.strategy, str)
        and r.strategy in _ACTIONS
        and isinstance(r.reason, str)
        and isinstance(r.frontier, list)
        and isinstance(r.q_rank, list)
        and isinstance(r.moo_active, bool)
        and isinstance(r.filtered_out, list)
    )
    report(tid, name, ok,
           f"strategy={r.strategy!r} moo_active={r.moo_active}")


def i4_moo_aware_select_with_sc_frontier():
    tid = "I4"
    name = "moo_aware_select with security_checks real frontier → strategy on frontier"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    frontier = get_pareto_frontier_for(SC_PATH, report_dir=_REPORT_DIR)
    if not frontier:
        skip(tid, name, "frontier is empty for security_checks")
        return
    r = moo_aware_select(SC_PATH, _Q_HIGH_O3, _ACTIONS, frontier)
    in_frontier = r.strategy in frontier
    ok = r.moo_active and in_frontier
    report(tid, name, ok,
           f"strategy={r.strategy!r} in_frontier={in_frontier} frontier={frontier}")


def i5_moo_filtering_occurs():
    tid = "I5"
    name = "MOO filtering: chosen strategy is on Pareto frontier (not argmax) when argmax not Pareto-optimal"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    # Use TC1 frontier; if -O3 is not on frontier, moo_active should be True
    frontier = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    if not frontier:
        skip(tid, name, "TC1 frontier is empty")
        return

    argmax_strategy = _ACTIONS[_Q_HIGH_O3.index(max(_Q_HIGH_O3))]  # should be -O3
    r = moo_aware_select(TC1_PATH, _Q_HIGH_O3, _ACTIONS, frontier)

    if argmax_strategy in frontier:
        # Argmax happens to be Pareto-optimal: verify selected == argmax
        ok = r.strategy == argmax_strategy
        report(tid, name, ok,
               f"argmax={argmax_strategy!r} is on frontier; selected={r.strategy!r}")
    else:
        # Argmax is NOT Pareto-optimal: verify MOO filtered it
        ok = r.moo_active and r.strategy in frontier and argmax_strategy not in frontier
        report(tid, name, ok,
               f"argmax={argmax_strategy!r} NOT on frontier; "
               f"selected={r.strategy!r} moo_active={r.moo_active}")


def i6_empty_frontier_fallback_to_argmax():
    tid = "I6"
    name = "Fallback to argmax when frontier is empty (MOO unavailable)"
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, [])
    # argmax should be -O3 (Q=0.90)
    expected = _ACTIONS[_Q_HIGH_O3.index(max(_Q_HIGH_O3))]
    ok = r.strategy == expected and r.moo_active is False and r.frontier == []
    report(tid, name, ok,
           f"strategy={r.strategy!r} expected={expected!r} moo_active={r.moo_active}")


def i7_fallback_when_get_frontier_returns_empty():
    tid = "I7"
    name = "Selector falls back to argmax when get_pareto_frontier_for returns []"
    # Point at a nonexistent report dir → get_pareto_frontier_for returns []
    frontier = get_pareto_frontier_for(
        TC1_PATH,
        report_dir="/nonexistent/path/that/does/not/exist",
    )
    ok_frontier_empty = frontier == []
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    expected = _ACTIONS[_Q_HIGH_O3.index(max(_Q_HIGH_O3))]
    ok = ok_frontier_empty and r.strategy == expected and r.moo_active is False
    report(tid, name, ok,
           f"frontier={frontier!r} strategy={r.strategy!r} moo_active={r.moo_active}")


def i8_cached_report_used_on_repeat():
    tid = "I8"
    name = "Cached report is used on repeated calls (same result, no re-run)"
    if not _real_reports_exist():
        skip(tid, name, "moo/reports/ has no moo_*.json files")
        return
    # Call twice — should return identical results (cache is file-based)
    f1 = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    f2 = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    ok = f1 == f2
    report(tid, name, ok, f"call1={f1} call2={f2}")


def i9_invalidate_cache():
    tid = "I9"
    name = "invalidate_cache removes only matching moo_*.json files"
    tmpdir = tempfile.mkdtemp()
    try:
        # Write a report for test.c and one for other.c
        test_report = os.path.join(tmpdir, "moo_test_c_2026-01-01_00-00-00.json")
        other_report = os.path.join(tmpdir, "moo_other_c_2026-01-01_00-00-00.json")
        with open(test_report, "w") as f:
            json.dump({"test": True}, f)
        with open(other_report, "w") as f:
            json.dump({"test": True}, f)

        removed = invalidate_cache(
            os.path.join(tmpdir, "test.c"),
            report_dir=tmpdir,
        )
        # test.c report removed; other.c report preserved
        ok = (
            removed == 1
            and not os.path.exists(test_report)
            and os.path.exists(other_report)
        )
        report(tid, name, ok,
               f"removed={removed} test_gone={not os.path.exists(test_report)} "
               f"other_kept={os.path.exists(other_report)}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def i10_selector_smoke_test():
    """
    End-to-end smoke test: call optimization_selector.get_best_optimization()
    on TC1_loop_heavy.c and verify:
      1. It returns a non-empty string (does not crash)
      2. The returned strategy is a known ACTIONS entry
      3. When a real frontier is available, the strategy is Pareto-optimal
    """
    tid = "I10"
    name = "Selector smoke test: get_best_optimization() returns Pareto-optimal strategy"

    model_path = os.path.join(_PS_DIR, "ml_optimizer_model.pth")
    if not os.path.exists(model_path):
        skip(tid, name, f"model not found at {model_path}")
        return
    if not os.path.exists(TC1_PATH):
        skip(tid, name, f"TC1_loop_heavy.c not found at {TC1_PATH}")
        return

    # Import the selector — must not crash
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "optimization_selector",
            os.path.join(_PS_DIR, "optimization_selector.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["optimization_selector"] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        report(tid, name, False, f"import failed: {exc}")
        return

    try:
        strategy = mod.get_best_optimization(TC1_PATH)
    except Exception as exc:
        report(tid, name, False, f"get_best_optimization raised: {exc}")
        return

    if strategy is None:
        report(tid, name, False, "get_best_optimization returned None")
        return

    in_actions = strategy in _ACTIONS
    if not in_actions:
        report(tid, name, False, f"strategy={strategy!r} not in ACTIONS")
        return

    # Check whether the strategy is Pareto-optimal
    frontier = get_pareto_frontier_for(TC1_PATH, report_dir=_REPORT_DIR)
    if frontier:
        on_frontier = strategy in frontier
        ok = on_frontier
        report(tid, name, ok,
               f"strategy={strategy!r} on_frontier={on_frontier} frontier={frontier}")
    else:
        # No frontier available → just verify a valid strategy was returned
        report(tid, name, True,
               f"strategy={strategy!r} (no cached frontier to verify Pareto membership)")


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
    print("TOACD MOO Stage 4 - Integration Tests")
    print("=" * 65)

    print(f"\n  REPORT_DIR : {_REPORT_DIR}")
    print(f"  TC1_PATH   : {TC1_PATH}")
    print(f"  SC_PATH    : {SC_PATH}")
    print(f"  Reports exist: {_real_reports_exist()}")

    print("\n--- Cache + frontier loading tests ---")
    i1_tc1_frontier_from_real_report()
    i2_sc_frontier_from_real_report()
    i8_cached_report_used_on_repeat()
    i9_invalidate_cache()

    print("\n--- MOO-aware selection tests ---")
    i3_moo_aware_select_with_tc1_frontier()
    i4_moo_aware_select_with_sc_frontier()
    i5_moo_filtering_occurs()

    print("\n--- Fallback behavior tests ---")
    i6_empty_frontier_fallback_to_argmax()
    i7_fallback_when_get_frontier_returns_empty()

    print("\n--- End-to-end smoke test ---")
    i10_selector_smoke_test()

    print()
    print("=" * 65)
    passed  = sum(1 for _, _, s in _results if s == "PASS")
    failed  = sum(1 for _, _, s in _results if s == "FAIL")
    skipped = sum(1 for _, _, s in _results if s == "SKIP")
    total   = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 65 + "\n")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
