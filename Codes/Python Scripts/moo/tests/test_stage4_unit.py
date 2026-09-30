"""
moo/tests/test_stage4_unit.py — Stage 4 unit tests.

Tests the selector_bridge module in complete isolation:
no clang, no opt, no real files, no pipeline runs.

Test plan
---------
U1  Q-value ranking: highest-Q frontier candidate is selected
U2  AI top choice rejected when not Pareto-efficient; next frontier picks up
U3  All strategies on frontier: highest-Q wins (same as argmax)
U4  Empty frontier: falls back to pure argmax
U5  Frontier contains strategies not in ACTIONS: falls back to argmax
U6  Single strategy on frontier: always selected regardless of Q rank
U7  Action ordering: indices match ACTIONS list positions exactly
U8  Deterministic: same inputs produce same output every call
U9  Fallback on exception: moo_aware_select never raises
U10 get_pareto_frontier_for: missing report dir → returns []
U11 get_pareto_frontier_for: malformed JSON → returns []
U12 get_pareto_frontier_for: valid report → returns frontier list
U13 get_pareto_frontier_for: report with pipeline_error → returns []
U14 SelectionResult attributes: moo_active=True when MOO filtered
U15 SelectionResult attributes: moo_active=False when frontier empty
U16 filtered_out: only strategies with Q > selected are reported
U17 _source_key: correct key derived from path
U18 _find_latest_moo_report: returns most recent when multiple files
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import shutil

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo.selector_bridge import (
    SelectionResult,
    _source_key,
    _find_latest_moo_report,
    _load_moo_report,
    get_pareto_frontier_for,
    moo_aware_select,
    invalidate_cache,
)


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A representative 9-element ACTIONS list (matches real project ACTIONS)
_ACTIONS = [
    "-O0", "-O1", "-O2", "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
]

# Q-values designed so: -O3 (idx=3) has highest Q, -O1 (idx=1) has second,
# -O2 (idx=2) third, and so on.
_Q_HIGH_O3 = [0.1, 0.6, 0.5, 0.9, 0.3, 0.2, 0.15, 0.12, 0.08]


def _make_moo_report_dict(
    source_file: str,
    frontier: list[str],
    dominated: list[str],
    pipeline_error: str | None = None,
) -> dict:
    """Build a minimal valid moo_*.json dict."""
    candidates = []
    for i, name in enumerate(_ACTIONS):
        status = "FRONTIER" if name in frontier else (
            "DOMINATED" if name in dominated else "INVALID"
        )
        candidates.append({
            "strategy_name": name,
            "strategy_index": i,
            "strategy_kind": "clang_flag" if name.startswith("-O") else "opt_passes",
            "build_ok": True,
            "build_error": None,
            "exe_path": None,
            "correctness_checked": True,
            "correct": True,
            "correctness_details": "",
            "reference_exit_code": 0,
            "candidate_exit_code": 0,
            "measurement": {"timing": {"median_s": 0.5}},
            "normalized": None,
            "pareto_status": status,
            "dominated_by": [],
        })
    return {
        "source_file": source_file,
        "source_path": f"/test/{source_file}",
        "timestamp": "2026-10-01T00:00:00",
        "toolchain_ok": True,
        "toolchain_notes": [],
        "baseline": None,
        "candidates": candidates,
        "pareto_frontier": list(frontier),
        "pareto_dominated": list(dominated),
        "pareto_invalid": [],
        "objectives_used": ["execution_time", "energy", "code_size", "carbon"],
        "pipeline_error": pipeline_error,
        "summary": {
            "n_strategies": len(_ACTIONS),
            "n_valid": len(frontier) + len(dominated),
            "n_invalid": 0,
            "n_frontier": len(frontier),
            "n_dominated": len(dominated),
        },
    }


def _write_report(tmpdir: str, source_file: str, data: dict, ts: str = "2026-10-01_01-00-00") -> str:
    safe = source_file.replace(".", "_").replace(" ", "_")
    fname = f"moo_{safe}_{ts}.json"
    path = os.path.join(tmpdir, fname)
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ---------------------------------------------------------------------------
# moo_aware_select tests
# ---------------------------------------------------------------------------

def u1_highest_q_frontier_selected():
    tid, name = "U1", "highest-Q frontier candidate is selected"
    # Frontier is [-O1, -O2]; -O3 has highest Q but is NOT on frontier
    # -O1 (idx=1, Q=0.6) has higher Q than -O2 (idx=2, Q=0.5) on frontier
    frontier = ["-O1", "-O2"]
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    ok = r.strategy == "-O1" and r.moo_active is True
    report(tid, name, ok, f"strategy={r.strategy!r} moo_active={r.moo_active}")


def u2_ai_top_rejected_when_not_frontier():
    tid, name = "U2", "AI top choice rejected when not Pareto-efficient"
    # -O3 has highest Q=0.9 but only [-O1, -O2] are on frontier
    frontier = ["-O1", "-O2"]
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    ok = (
        r.strategy != "-O3"          # AI top not selected
        and "-O3" in r.filtered_out  # -O3 appears in filtered_out
        and r.moo_active is True
    )
    report(tid, name, ok, f"strategy={r.strategy!r} filtered_out={r.filtered_out}")


def u3_all_frontier_highest_q_wins():
    tid, name = "U3", "when all strategies on frontier, highest-Q wins (same as argmax)"
    # All 9 on frontier
    frontier = list(_ACTIONS)
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    # Should pick -O3 (highest Q=0.9)
    ok = r.strategy == "-O3" and r.filtered_out == []
    report(tid, name, ok, f"strategy={r.strategy!r}")


def u4_empty_frontier_fallback():
    tid, name = "U4", "empty frontier → pure argmax fallback"
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, [])
    # Should pick -O3 (highest Q=0.9) exactly as argmax
    ok = r.strategy == "-O3" and r.moo_active is False
    report(tid, name, ok, f"strategy={r.strategy!r} moo_active={r.moo_active}")


def u5_frontier_not_in_actions_fallback():
    tid, name = "U5", "frontier strategies not in ACTIONS → argmax fallback"
    # Frontier contains strategy names that don't exist in ACTIONS
    frontier = ["nonexistent_pass_A", "nonexistent_pass_B"]
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    # Falls back to argmax: -O3
    ok = r.strategy == "-O3" and r.moo_active is False
    report(tid, name, ok, f"strategy={r.strategy!r} moo_active={r.moo_active}")


def u6_single_strategy_frontier():
    tid, name = "U6", "single strategy on frontier is always selected"
    frontier = ["mem2reg,simplifycfg"]  # low Q=0.2 but only frontier member
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    ok = r.strategy == "mem2reg,simplifycfg" and r.moo_active is True
    report(tid, name, ok, f"strategy={r.strategy!r}")


def u7_action_ordering():
    tid, name = "U7", "action indices match ACTIONS list positions"
    # q_rank should be in descending Q-value order
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, [])
    # Top of q_rank should be the action with highest q_value
    if r.q_rank:
        top_action, top_q = r.q_rank[0]
        ok = top_action == "-O3" and math.isclose(top_q, 0.9)
    else:
        ok = False
    report(tid, name, ok, f"q_rank[0]={r.q_rank[0] if r.q_rank else 'empty'}")


def u8_deterministic():
    tid, name = "U8", "same inputs produce same output on repeated calls"
    frontier = ["-O1"]
    r1 = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    r2 = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    ok = r1.strategy == r2.strategy and r1.reason == r2.reason
    report(tid, name, ok, f"r1={r1.strategy!r} r2={r2.strategy!r}")


def u9_no_exception_on_bad_input():
    tid, name = "U9", "moo_aware_select never raises on malformed input"
    try:
        # Mismatched lengths
        r = moo_aware_select("test.c", [0.5], _ACTIONS, ["-O1"])
        ok = isinstance(r.strategy, str)
    except Exception as e:
        ok = False
        report(tid, name, False, f"raised: {e}")
        return
    report(tid, name, ok, f"strategy={r.strategy!r}")


# ---------------------------------------------------------------------------
# get_pareto_frontier_for tests
# ---------------------------------------------------------------------------

def u10_missing_report_dir():
    tid, name = "U10", "get_pareto_frontier_for: missing report dir → []"
    result = get_pareto_frontier_for(
        "/fake/path/to/test.c",
        report_dir="/this/dir/does/not/exist",
    )
    ok = result == []
    report(tid, name, ok, f"result={result!r}")


def u11_malformed_json():
    tid, name = "U11", "get_pareto_frontier_for: malformed JSON → []"
    tmpdir = tempfile.mkdtemp()
    try:
        # Write a malformed JSON file with the right filename pattern
        fname = "moo_test_c_2026-10-01_00-00-00.json"
        with open(os.path.join(tmpdir, fname), "w") as f:
            f.write("{not valid json")
        result = get_pareto_frontier_for(
            os.path.join(tmpdir, "test.c"),
            report_dir=tmpdir,
        )
        ok = result == []
        report(tid, name, ok, f"result={result!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def u12_valid_report_returns_frontier():
    tid, name = "U12", "get_pareto_frontier_for: valid report → frontier list"
    tmpdir = tempfile.mkdtemp()
    try:
        data = _make_moo_report_dict(
            "test.c",
            frontier=["-O1", "-O3"],
            dominated=["-O0", "-O2"],
        )
        _write_report(tmpdir, "test.c", data)
        result = get_pareto_frontier_for(
            os.path.join(tmpdir, "test.c"),
            report_dir=tmpdir,
        )
        ok = sorted(result) == sorted(["-O1", "-O3"])
        report(tid, name, ok, f"result={result!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def u13_pipeline_error_in_report():
    tid, name = "U13", "get_pareto_frontier_for: report with pipeline_error → []"
    tmpdir = tempfile.mkdtemp()
    try:
        data = _make_moo_report_dict(
            "test.c",
            frontier=[],
            dominated=[],
            pipeline_error="Reference build failed: compiler not found",
        )
        _write_report(tmpdir, "test.c", data)
        result = get_pareto_frontier_for(
            os.path.join(tmpdir, "test.c"),
            report_dir=tmpdir,
        )
        ok = result == []
        report(tid, name, ok, f"result={result!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def u14_moo_active_when_filtered():
    tid, name = "U14", "SelectionResult.moo_active=True when MOO actually filtered"
    # -O3 is highest-Q but NOT on frontier → MOO filtered it
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, ["-O1"])
    ok = r.moo_active is True and r.strategy == "-O1"
    report(tid, name, ok, f"moo_active={r.moo_active} strategy={r.strategy!r}")


def u15_moo_inactive_when_frontier_empty():
    tid, name = "U15", "SelectionResult.moo_active=False when frontier is empty"
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, [])
    ok = r.moo_active is False
    report(tid, name, ok, f"moo_active={r.moo_active}")


def u16_filtered_out_only_higher_q():
    tid, name = "U16", "filtered_out contains only strategies with Q > selected"
    # Frontier: [-O1, -O2]. Selected will be -O1 (Q=0.6).
    # filtered_out should be -O3 (Q=0.9 > 0.6) only. -O0 (Q=0.1) has lower Q.
    frontier = ["-O1", "-O2"]
    r = moo_aware_select("test.c", _Q_HIGH_O3, _ACTIONS, frontier)
    # selected = -O1 (Q=0.6); filtered_out must only contain strategies with Q > 0.6
    selected_q = dict(zip(_ACTIONS, _Q_HIGH_O3))[r.strategy]
    all_higher_q_correct = all(
        dict(zip(_ACTIONS, _Q_HIGH_O3))[act] > selected_q
        for act in r.filtered_out
    )
    ok = all_higher_q_correct and "-O3" in r.filtered_out
    report(tid, name, ok, f"filtered_out={r.filtered_out} selected_q={selected_q}")


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------

def u17_source_key():
    tid, name = "U17", "_source_key: derives correct key from path"
    tests = [
        (r"C:\path\to\TC1_loop_heavy.c", "TC1_loop_heavy_c"),
        ("/some/path/security_checks.c", "security_checks_c"),
        ("simple.c", "simple_c"),
        ("with spaces.c", "with_spaces_c"),
    ]
    results = []
    for path, expected in tests:
        got = _source_key(path)
        results.append((path, expected, got, got == expected))
    ok = all(r[3] for r in results)
    report(tid, name, ok, f"mismatches={[r for r in results if not r[3]]}")


def u18_find_latest_moo_report():
    tid, name = "U18", "_find_latest_moo_report: returns most recent when multiple files"
    tmpdir = tempfile.mkdtemp()
    try:
        import time
        data = _make_moo_report_dict("test.c", frontier=["-O1"], dominated=["-O0"])
        # Write two files with different timestamps in name; touch second to be newer
        p1 = _write_report(tmpdir, "test.c", data, ts="2026-09-01_00-00-00")
        time.sleep(0.05)  # ensure different mtime
        p2 = _write_report(tmpdir, "test.c", data, ts="2026-10-01_00-00-00")
        # p2 was written later → should be selected
        found = _find_latest_moo_report(
            os.path.join(tmpdir, "test.c"),
            report_dir=tmpdir,
        )
        ok = found is not None and os.path.basename(found) == os.path.basename(p2)
        report(tid, name, ok, f"found={os.path.basename(found) if found else None!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
    print("TOACD MOO Stage 4 - Unit Tests")
    print("=" * 65)

    print("\n--- moo_aware_select tests ---")
    u1_highest_q_frontier_selected()
    u2_ai_top_rejected_when_not_frontier()
    u3_all_frontier_highest_q_wins()
    u4_empty_frontier_fallback()
    u5_frontier_not_in_actions_fallback()
    u6_single_strategy_frontier()
    u7_action_ordering()
    u8_deterministic()
    u9_no_exception_on_bad_input()

    print("\n--- get_pareto_frontier_for tests ---")
    u10_missing_report_dir()
    u11_malformed_json()
    u12_valid_report_returns_frontier()
    u13_pipeline_error_in_report()
    u14_moo_active_when_filtered()
    u15_moo_inactive_when_frontier_empty()
    u16_filtered_out_only_higher_q()

    print("\n--- Internal helper tests ---")
    u17_source_key()
    u18_find_latest_moo_report()

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
