"""
moo/tests/test_stage2_pareto.py
Stage 2 focused tests — normalization, dominance, and Pareto frontier.

Tests are purely unit-level: they use synthetic RawObjectives values and do
NOT require clang/llvm-size/real executables.  They run in milliseconds.

Test plan
---------
N1  Normalization — improvement (< 1.0)
N2  Normalization — regression (> 1.0)
N3  Normalization — equal to baseline (= 1.0)
N4  Normalization — zero baseline → NormalizationError sentinel, no NaN/inf
N5  Normalization — None raw value → NormalizationError sentinel
N6  Normalization — None baseline value → NormalizationError sentinel
N7  Normalization — negative baseline → NormalizationError sentinel
N8  Normalization — all four objectives together

D1  dominates() — A clearly dominates B (all objectives)
D2  dominates() — A does NOT dominate B (B better on one objective)
D3  dominates() — equal values → neither dominates
D4  dominates() — partial improvement: A better on 2, equal on 2 → A dominates B
D5  dominates() — one invalid objective is skipped gracefully

P1  Pareto frontier — one clearly dominated candidate is excluded
P2  Pareto frontier — two non-dominated trade-off candidates both on frontier
P3  Pareto frontier — single candidate is always on frontier
P4  Pareto frontier — all equal → all on frontier
P5  Pareto frontier — multiple objectives, 3 candidates with clear dominance ordering
P6  Pareto frontier — empty input
P7  Pareto frontier — strategy names preserved exactly

I1  interpret_normalized — improvement text
I2  interpret_normalized — regression text
I3  interpret_normalized — equal text
I4  interpret_normalized — invalid sentinel text
"""

from __future__ import annotations

import math
import os
import sys

# Ensure moo package is importable when run directly
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo.objectives import (
    ALL_OBJECTIVES,
    OBJECTIVE_CODE_SIZE,
    OBJECTIVE_ENERGY,
    OBJECTIVE_EXECUTION_TIME,
    OBJECTIVE_CARBON,
    NormalizationError,
    RawObjectives,
    NormalizedObjectiveVector,
    normalize,
    interpret_normalized,
)
from moo.pareto import dominates, extract_pareto_frontier, CandidateEntry


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

PASS_STR = "\033[32mPASS\033[0m"
FAIL_STR = "\033[31mFAIL\033[0m"

_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = ""):
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    status = PASS_STR if passed else FAIL_STR
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")


def _make_raw(
    strategy: str,
    t: float | None = 1.0,
    e: float | None = 45.0,
    cs: int | None = 60000,
    co: float | None = 0.005,
) -> RawObjectives:
    return RawObjectives(
        strategy=strategy,
        execution_time_s=t,
        energy_j=e,
        code_size_bytes=cs,
        carbon_g=co,
    )


def _make_vec(
    strategy: str,
    norm_vals: tuple,  # (exec_time, energy, code_size, carbon) — floats or sentinels
    objectives=ALL_OBJECTIVES,
) -> NormalizedObjectiveVector:
    """Build a NormalizedObjectiveVector directly from normalized values (for tests)."""
    n = len(objectives)
    raw = tuple(None for _ in range(n))
    base = tuple(None for _ in range(n))
    notes = tuple("" for _ in range(n))
    return NormalizedObjectiveVector(
        strategy=strategy,
        objectives=objectives,
        raw_values=raw,
        baseline_values=base,
        normalized_values=norm_vals,
        normalization_notes=notes,
    )


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

def n1_improvement():
    tid, name = "N1", "normalization — improvement (< 1.0)"
    base = _make_raw("baseline", t=1.0, e=45.0, cs=60000, co=0.005)
    cand = _make_raw("-O2", t=0.5, e=22.5, cs=50000, co=0.0025)
    v = normalize(cand, base)
    vals = v.normalized_values
    ok = all(isinstance(x, float) and x < 1.0 for x in vals)
    report(tid, name, ok,
           f"exec={vals[0]:.3f} energy={vals[1]:.3f} size={vals[2]:.3f} carbon={vals[3]:.3f}")


def n2_regression():
    tid, name = "N2", "normalization — regression (> 1.0)"
    base = _make_raw("baseline", t=1.0, e=45.0, cs=60000, co=0.005)
    cand = _make_raw("-O3", t=2.0, e=90.0, cs=120000, co=0.01)
    v = normalize(cand, base)
    vals = v.normalized_values
    ok = all(isinstance(x, float) and x > 1.0 for x in vals)
    report(tid, name, ok,
           f"exec={vals[0]:.3f} energy={vals[1]:.3f} size={vals[2]:.3f} carbon={vals[3]:.3f}")


def n3_equal():
    tid, name = "N3", "normalization — equal to baseline (= 1.0)"
    base = _make_raw("baseline", t=1.0, e=45.0, cs=60000, co=0.005)
    cand = _make_raw("-O0", t=1.0, e=45.0, cs=60000, co=0.005)
    v = normalize(cand, base)
    vals = v.normalized_values
    ok = all(isinstance(x, float) and math.isclose(x, 1.0) for x in vals)
    report(tid, name, ok,
           f"exec={vals[0]:.4f} energy={vals[1]:.4f} size={vals[2]:.4f} carbon={vals[3]:.4f}")


def n4_zero_baseline():
    tid, name = "N4", "normalization — zero baseline → sentinel, no NaN/inf"
    base = _make_raw("baseline", t=0.0, e=0.0, cs=0, co=0.0)
    cand = _make_raw("cand", t=1.0, e=10.0, cs=5000, co=0.001)
    v = normalize(cand, base)
    vals = v.normalized_values
    notes = v.normalization_notes
    # All should be sentinel strings, none should be NaN or inf
    ok = all(
        isinstance(x, str) and x == NormalizationError.ZERO_BASELINE
        for x in vals
    )
    no_nan_inf = all(
        not (isinstance(x, float) and not math.isfinite(x))
        for x in vals
    )
    ok = ok and no_nan_inf
    report(tid, name, ok,
           f"sentinels={vals[0]!r} notes_present={all(n for n in notes)}")


def n5_none_raw():
    tid, name = "N5", "normalization — None raw value → MISSING_RAW sentinel"
    base = _make_raw("baseline", t=1.0, e=45.0, cs=60000, co=0.005)
    cand = _make_raw("cand", t=None, e=None, cs=None, co=None)
    v = normalize(cand, base)
    vals = v.normalized_values
    ok = all(x == NormalizationError.MISSING_RAW for x in vals)
    report(tid, name, ok, f"sentinels: {set(vals)}")


def n6_none_baseline():
    tid, name = "N6", "normalization — None baseline value → MISSING_BASELINE sentinel"
    base = _make_raw("baseline", t=None, e=None, cs=None, co=None)
    cand = _make_raw("cand", t=1.0, e=45.0, cs=60000, co=0.005)
    v = normalize(cand, base)
    vals = v.normalized_values
    ok = all(x == NormalizationError.MISSING_BASELINE for x in vals)
    report(tid, name, ok, f"sentinels: {set(vals)}")


def n7_negative_baseline():
    tid, name = "N7", "normalization — negative baseline → NEGATIVE_BASELINE sentinel"
    base = _make_raw("baseline", t=-1.0, e=-5.0, cs=-1, co=-0.1)
    cand = _make_raw("cand", t=1.0, e=45.0, cs=60000, co=0.005)
    v = normalize(cand, base)
    vals = v.normalized_values
    # code_size_bytes is int; -1 cast to float(-1) → negative
    ok = all(x == NormalizationError.NEGATIVE_BASELINE for x in vals)
    report(tid, name, ok, f"sentinels: {set(vals)}")


def n8_all_four_objectives():
    tid, name = "N8", "normalization — all four objectives with mixed results"
    base = _make_raw("baseline", t=1.0, e=45.0, cs=60000, co=0.005)
    # exec improves, energy regresses, code_size improves, carbon regresses
    cand = _make_raw("mixed", t=0.8, e=50.0, cs=50000, co=0.006)
    v = normalize(cand, base)
    vals = v.normalized_values
    exec_t, energy, size, carbon = vals
    ok = (
        isinstance(exec_t, float) and exec_t < 1.0      # improvement
        and isinstance(energy, float) and energy > 1.0  # regression
        and isinstance(size, float) and size < 1.0      # improvement
        and isinstance(carbon, float) and carbon > 1.0  # regression
        and v.objectives == ALL_OBJECTIVES
        and v.strategy == "mixed"
    )
    report(tid, name, ok,
           f"exec={exec_t:.3f} energy={energy:.3f} size={size:.3f} carbon={carbon:.3f}")


# ---------------------------------------------------------------------------
# Dominance tests
# ---------------------------------------------------------------------------

def d1_clear_dominance():
    tid, name = "D1", "dominates() — A clearly dominates B (all objectives)"
    # A better on all four objectives
    a = _make_vec("A", norm_vals=(0.8, 0.8, 0.8, 0.8))
    b = _make_vec("B", norm_vals=(1.0, 1.0, 1.0, 1.0))
    ok = dominates(a, b) and not dominates(b, a)
    report(tid, name, ok,
           f"A→B={dominates(a,b)} B→A={dominates(b,a)}")


def d2_no_dominance():
    tid, name = "D2", "dominates() — A does NOT dominate B (B better on one objective)"
    # A wins exec_time and energy; B wins code_size; tied on carbon
    a = _make_vec("A", norm_vals=(0.7, 0.8, 1.2, 1.0))
    b = _make_vec("B", norm_vals=(1.0, 1.0, 0.9, 1.0))
    ok = not dominates(a, b) and not dominates(b, a)
    report(tid, name, ok,
           f"A→B={dominates(a,b)} B→A={dominates(b,a)}")


def d3_equal_no_dominance():
    tid, name = "D3", "dominates() — equal values → neither dominates"
    a = _make_vec("A", norm_vals=(1.0, 1.0, 1.0, 1.0))
    b = _make_vec("A_copy", norm_vals=(1.0, 1.0, 1.0, 1.0))
    ok = not dominates(a, b) and not dominates(b, a)
    report(tid, name, ok)


def d4_partial_improvement():
    tid, name = "D4", "dominates() — better on 2, equal on 2 → A dominates B"
    # <= everywhere, < in at least one
    a = _make_vec("A", norm_vals=(0.9, 0.9, 1.0, 1.0))
    b = _make_vec("B", norm_vals=(1.0, 1.0, 1.0, 1.0))
    ok = dominates(a, b) and not dominates(b, a)
    report(tid, name, ok,
           f"A→B={dominates(a,b)} B→A={dominates(b,a)}")


def d5_invalid_objective_skipped():
    tid, name = "D5", "dominates() — invalid objective skipped, rest compared"
    # Objective 3 (carbon) is invalid in both; comparison uses remaining 3
    # A dominates B on the 3 valid objectives
    a = _make_vec("A", norm_vals=(0.8, 0.8, 0.8, NormalizationError.ZERO_BASELINE))
    b = _make_vec("B", norm_vals=(1.0, 1.0, 1.0, NormalizationError.ZERO_BASELINE))
    ok = dominates(a, b) and not dominates(b, a)
    report(tid, name, ok,
           f"A→B={dominates(a,b)} B→A={dominates(b,a)}")


# ---------------------------------------------------------------------------
# Pareto frontier tests
# ---------------------------------------------------------------------------

def p1_one_dominated():
    tid, name = "P1", "Pareto frontier — dominated candidate excluded"
    # A dominates C on all objectives; B and A are trade-offs
    a = _make_vec("A", norm_vals=(0.8, 1.2, 0.8, 1.2))   # fast+small, more energy/carbon
    b = _make_vec("B", norm_vals=(1.2, 0.8, 1.2, 0.8))   # slow+large, less energy/carbon
    c = _make_vec("C", norm_vals=(1.0, 1.0, 1.0, 1.0))   # baseline-equivalent (dominated by A+B? no — only if A<=C on all AND strict on one)
    # Actually let's make C clearly dominated by A: A <= C everywhere, strict somewhere
    # A=(0.8,1.2,0.8,1.2) vs C=(1.0,1.3,0.9,1.3) → A wins exec+size; C worse on energy+carbon too
    c = _make_vec("C", norm_vals=(1.0, 1.3, 0.9, 1.3))
    result = extract_pareto_frontier([a, b, c])
    ok = (
        "C" not in result.frontier
        and "A" in result.frontier
        and "B" in result.frontier
        and "C" in result.dominated
    )
    report(tid, name, ok,
           f"frontier={result.frontier} dominated={result.dominated}")


def p2_two_tradeoff_candidates():
    tid, name = "P2", "Pareto frontier — two trade-off candidates both on frontier"
    # A better on exec_time + energy, B better on code_size + carbon → trade-off
    a = _make_vec("fast", norm_vals=(0.6, 0.6, 1.4, 1.4))
    b = _make_vec("small", norm_vals=(1.4, 1.4, 0.6, 0.6))
    result = extract_pareto_frontier([a, b])
    ok = (
        set(result.frontier) == {"fast", "small"}
        and result.dominated == []
    )
    report(tid, name, ok,
           f"frontier={result.frontier} dominated={result.dominated}")


def p3_single_candidate():
    tid, name = "P3", "Pareto frontier — single candidate always on frontier"
    only = _make_vec("only", norm_vals=(1.0, 1.0, 1.0, 1.0))
    result = extract_pareto_frontier([only])
    ok = result.frontier == ["only"] and result.dominated == []
    report(tid, name, ok)


def p4_all_equal():
    tid, name = "P4", "Pareto frontier — all equal → all on frontier"
    vecs = [_make_vec(f"S{i}", norm_vals=(1.0, 1.0, 1.0, 1.0)) for i in range(4)]
    result = extract_pareto_frontier(vecs)
    ok = (
        set(result.frontier) == {f"S{i}" for i in range(4)}
        and result.dominated == []
    )
    report(tid, name, ok,
           f"frontier_size={len(result.frontier)}")


def p5_multi_candidate_ordering():
    tid, name = "P5", "Pareto frontier — 3 candidates, clear ordering"
    # best clearly dominates mid; mid clearly dominates worst
    best = _make_vec("best",  norm_vals=(0.5, 0.5, 0.5, 0.5))
    mid  = _make_vec("mid",   norm_vals=(0.8, 0.8, 0.8, 0.8))
    worst= _make_vec("worst", norm_vals=(1.2, 1.2, 1.2, 1.2))
    result = extract_pareto_frontier([best, mid, worst])
    ok = (
        result.frontier == ["best"]
        and set(result.dominated) == {"mid", "worst"}
    )
    report(tid, name, ok,
           f"frontier={result.frontier} dominated={result.dominated}")


def p6_empty_input():
    tid, name = "P6", "Pareto frontier — empty input handled gracefully"
    result = extract_pareto_frontier([])
    ok = result.frontier == [] and result.dominated == [] and len(result.notes) > 0
    report(tid, name, ok, f"notes={result.notes}")


def p7_strategy_names_preserved():
    tid, name = "P7", "Pareto frontier — strategy names preserved exactly"
    names = ["-O0", "-O1", "-O2", "-O3", "mem2reg,instcombine"]
    # All equal so all on frontier
    vecs = [_make_vec(n, norm_vals=(1.0, 1.0, 1.0, 1.0)) for n in names]
    result = extract_pareto_frontier(vecs)
    ok = set(result.frontier) == set(names)
    report(tid, name, ok, f"frontier names match: {ok}")


# ---------------------------------------------------------------------------
# Interpretation tests
# ---------------------------------------------------------------------------

def i1_interpret_improvement():
    tid, name = "I1", "interpret_normalized — improvement text"
    s = interpret_normalized(0.7)
    ok = "improved" in s and "30.0%" in s
    report(tid, name, ok, repr(s))


def i2_interpret_regression():
    tid, name = "I2", "interpret_normalized — regression text"
    s = interpret_normalized(1.5)
    ok = "regressed" in s and "50.0%" in s
    report(tid, name, ok, repr(s))


def i3_interpret_equal():
    tid, name = "I3", "interpret_normalized — equal text"
    s = interpret_normalized(1.0005)  # within default threshold
    ok = "equal" in s
    report(tid, name, ok, repr(s))


def i4_interpret_invalid():
    tid, name = "I4", "interpret_normalized — sentinel string → invalid text"
    s = interpret_normalized(NormalizationError.ZERO_BASELINE)
    ok = "invalid" in s
    report(tid, name, ok, repr(s))


# ---------------------------------------------------------------------------
# Example trace (printed to stdout, not a pass/fail test)
# ---------------------------------------------------------------------------

def _print_example():
    """Print a small worked example: raw → normalized → Pareto."""
    print("\n" + "=" * 65)
    print("Example: raw → normalized → Pareto")
    print("=" * 65)

    baseline = _make_raw("baseline(-O0)", t=1.000, e=45.00, cs=70000, co=0.0054)
    c_o1 = _make_raw("-O1", t=0.850, e=38.25, cs=62000, co=0.0046)
    c_o2 = _make_raw("-O2", t=0.700, e=31.50, cs=58000, co=0.0038)
    c_o3 = _make_raw("-O3", t=0.650, e=29.25, cs=80000, co=0.0035)   # code bloat!
    c_m2r = _make_raw("mem2reg,instcombine", t=0.780, e=35.10, cs=55000, co=0.0042)

    candidates = [c_o1, c_o2, c_o3, c_m2r]
    from moo.pareto import pareto_from_raw
    vectors, pareto = pareto_from_raw(candidates, baseline)

    print(f"\n{'Strategy':<25} {'exec':>7} {'energy':>7} {'size':>7} {'carbon':>7}  status")
    print("-" * 70)
    for v in vectors:
        vals = [
            f"{x:.3f}" if isinstance(x, float) else "ERR"
            for x in v.normalized_values
        ]
        is_f = v.strategy in pareto.frontier
        tag = "FRONTIER" if is_f else "dominated"
        print(f"  {v.strategy:<23} {vals[0]:>7} {vals[1]:>7} {vals[2]:>7} {vals[3]:>7}  {tag}")

    print(f"\nPareto frontier ({len(pareto.frontier)} strategies): {pareto.frontier}")
    print(f"Dominated       ({len(pareto.dominated)} strategies): {pareto.dominated}")
    if pareto.notes:
        for note in pareto.notes:
            print(f"  NOTE: {note}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Force UTF-8 on Windows consoles that default to cp1252
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print("TOACD MOO Stage 2 - Objectives & Pareto Tests")
    print("=" * 65)
    print("\n--- Normalization tests ---")
    n1_improvement()
    n2_regression()
    n3_equal()
    n4_zero_baseline()
    n5_none_raw()
    n6_none_baseline()
    n7_negative_baseline()
    n8_all_four_objectives()

    print("\n--- Dominance tests ---")
    d1_clear_dominance()
    d2_no_dominance()
    d3_equal_no_dominance()
    d4_partial_improvement()
    d5_invalid_objective_skipped()

    print("\n--- Pareto frontier tests ---")
    p1_one_dominated()
    p2_two_tradeoff_candidates()
    p3_single_candidate()
    p4_all_equal()
    p5_multi_candidate_ordering()
    p6_empty_input()
    p7_strategy_names_preserved()

    print("\n--- Interpretation tests ---")
    i1_interpret_improvement()
    i2_interpret_regression()
    i3_interpret_equal()
    i4_interpret_invalid()

    _print_example()

    # Summary
    print("=" * 65)
    passed = sum(1 for _, _, s in _results if s == "PASS")
    failed = sum(1 for _, _, s in _results if s == "FAIL")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 65 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
