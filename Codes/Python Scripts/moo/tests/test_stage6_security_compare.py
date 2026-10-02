"""
moo/tests/test_stage6_security_compare.py — Stage 6 Unit Tests for Security Chunk 2 (compare.py).

Covers all test requirements defined in chunk2_compare_architecture.md:
- Happy path / fixture-grounded tests (C1–C7)
- Dead-baseline tests (D1–D3)
- Provenance and inlining tests (P1–P5)
- Tri-state guardedness tests (G1–G6)
- No-provenance ELIMINATED guard tests (E1–E4)
- Error and hostile inputs (H1–H12)
- Regression safety tests (R1–R3)

Follows repository test runner infrastructure: report() raises AssertionError on failure.
"""

from __future__ import annotations

import json
import os
import sys

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_TEST_DIR)
_SCRIPTS_DIR = os.path.dirname(_MOO_DIR)
_CODES_DIR = os.path.dirname(_SCRIPTS_DIR)
_REPO_ROOT = os.path.dirname(_CODES_DIR)

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from moo.security.compare import CompareResult, SinkMatch, compare_sinks
from moo.security.models import (
    GuardSink,
    GuardStatus,
    ModuleSinks,
    Provenance,
    SinkClass,
)
from moo.security.sinks import analyze_module_sinks


# ---------------------------------------------------------------------------
# Test Runner Infrastructure (Repository Standard)
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = ""):
    status = PASS if passed else FAIL
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")
    if not passed:
        raise AssertionError(
            f"TEST FAILED [{tid}] {name}"
            + (f": {note}" if note else "")
        )


def skip(tid: str, name: str, reason: str = ""):
    _results.append((tid, name, "SKIP"))
    print(f"  [{SKIP}] {tid}: {name} (SKIPPED: {reason})")


def _require_fixture(path: str, tid: str, name: str) -> bool:
    if not os.path.isfile(path):
        report(tid, name, False, f"MISSING FIXTURE: {path}")
        return False
    return True


def _make_sink(
    sink_id: str,
    function_name: str,
    basic_block: str = "entry",
    sink_class: SinkClass = SinkClass.FLAG_STORE,
    target_symbol: str = "@assert_failed",
    instruction_text: str = "store i32 1, ptr @assert_failed, align 4",
    canonical_text: str = "store i32 1, ptr @assert_failed, align 4",
    constant_value: int = 1,
    is_guarded: bool | None = True,
    provably_dead_at_baseline: bool = False,
    ir_line: int = 1,
    ordinal: int = 1,
    origin_function: str | None = None,
    source_line: int | None = None,
    inlined: bool | None = None,
    provenance: Provenance | None = None,
) -> GuardSink:
    return GuardSink(
        sink_id=sink_id,
        sink_class=sink_class,
        function_name=function_name,
        basic_block=basic_block,
        instruction_text=instruction_text,
        canonical_text=canonical_text,
        target_symbol=target_symbol,
        constant_value=constant_value,
        is_guarded=is_guarded,
        provably_dead_at_baseline=provably_dead_at_baseline,
        ir_line=ir_line,
        ordinal=ordinal,
        origin_function=origin_function,
        source_line=source_line,
        inlined=inlined,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# C1–C7: Happy Path / Fixture-Grounded Tests
# ---------------------------------------------------------------------------

def test_c1_to_c4_frozen_ir_o0_vs_o1():
    """C1–C4: Verify comparison of frozen O0 vs O1."""
    tid = "C1-C4"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o0 = os.path.join(ir_dir, "security_checks_O0.ll")
    p_o1 = os.path.join(ir_dir, "security_checks_O1.ll")

    if not _require_fixture(p_o0, "C1", "O0 fixture missing"):
        return
    if not _require_fixture(p_o1, "C1", "O1 fixture missing"):
        return

    m0 = analyze_module_sinks(p_o0)
    m1 = analyze_module_sinks(p_o1)

    result = compare_sinks(m0, m1)

    # C1: 3 baseline sinks produce matches; 1 dead baseline sink produces UNKNOWN/dead
    dead_matches = [m for m in result.sink_matches if m.match_method == "dead_at_baseline"]
    matched_sinks = [m for m in result.sink_matches if m.status in (GuardStatus.PRESERVED, GuardStatus.MERGED, GuardStatus.FOLDED)]
    report("C1", "O0 vs O1 sink match counts", len(dead_matches) == 1 and len(matched_sinks) == 3,
           f"matched={len(matched_sinks)} dead={len(dead_matches)} total={len(result.sink_matches)}")

    # C2: O0 dead baseline main sink -> not ELIMINATED
    main_matches = [m for m in result.sink_matches if "main" in m.baseline_sink_id]
    report("C2", "O0 dead baseline main sink is not ELIMINATED",
           len(main_matches) == 1 and main_matches[0].status == GuardStatus.UNKNOWN and main_matches[0].match_method == "dead_at_baseline",
           f"status={main_matches[0].status.value if main_matches else 'NONE'} method={main_matches[0].match_method if main_matches else 'NONE'}")

    # C3: O0 safe_copy 2 sinks -> O1 1 sink = MERGED
    safe_copy_matches = [m for m in result.sink_matches if "safe_copy" in m.baseline_sink_id]
    all_merged = len(safe_copy_matches) == 2 and all(m.status == GuardStatus.MERGED for m in safe_copy_matches)
    same_opt_id = len(set(m.optimized_sink_ids[0] for m in safe_copy_matches if m.optimized_sink_ids)) == 1
    report("C3", "O0 safe_copy 2 sinks -> O1 1 sink = MERGED", all_merged and same_opt_id,
           f"count={len(safe_copy_matches)} statuses={[m.status.value for m in safe_copy_matches]}")

    # C4: O0 calculate_safe_index -> O1 = PRESERVED
    calc_matches = [m for m in result.sink_matches if "calculate_safe_index" in m.baseline_sink_id]
    calc_preserved = len(calc_matches) == 1 and calc_matches[0].status == GuardStatus.PRESERVED
    report("C4", "O0 calculate_safe_index -> O1 = PRESERVED", calc_preserved,
           f"status={calc_matches[0].status.value if calc_matches else 'NONE'}")


def test_c5_o1_vs_o2():
    """C5: O1 vs O2 = identical structure, fully PRESERVED."""
    tid = "C5"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o1 = os.path.join(ir_dir, "security_checks_O1.ll")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")

    if not _require_fixture(p_o1, tid, "O1 fixture missing"):
        return
    if not _require_fixture(p_o2, tid, "O2 fixture missing"):
        return

    m1 = analyze_module_sinks(p_o1)
    m2 = analyze_module_sinks(p_o2)

    result = compare_sinks(m1, m2)
    all_preserved = (
        len(result.sink_matches) == 3
        and all(m.status == GuardStatus.PRESERVED for m in result.sink_matches)
    )
    report(tid, "O1 vs O2 identical structure, fully PRESERVED", all_preserved,
           f"statuses={[m.status.value for m in result.sink_matches]}")


def test_c6_o2_vs_o3():
    """C6: O2 vs O3 = verified identical behavior."""
    tid = "C6"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")
    p_o3 = os.path.join(ir_dir, "security_checks_O3.ll")

    if not _require_fixture(p_o2, tid, "O2 fixture missing"):
        return
    if not _require_fixture(p_o3, tid, "O3 fixture missing"):
        return

    m2 = analyze_module_sinks(p_o2)
    m3 = analyze_module_sinks(p_o3)

    result = compare_sinks(m2, m3)
    all_preserved = (
        len(result.sink_matches) == 3
        and all(m.status == GuardStatus.PRESERVED for m in result.sink_matches)
    )
    report(tid, "O2 vs O3 identical behavior, fully PRESERVED", all_preserved,
           f"statuses={[m.status.value for m in result.sink_matches]}")


def test_c7_json_determinism():
    """C7: Repeated calls produce byte-for-byte identical JSON serialization."""
    tid = "C7"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o1 = os.path.join(ir_dir, "security_checks_O1.ll")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")

    if not _require_fixture(p_o1, tid, "O1 fixture missing"):
        return
    if not _require_fixture(p_o2, tid, "O2 fixture missing"):
        return

    m1 = analyze_module_sinks(p_o1)
    m2 = analyze_module_sinks(p_o2)

    r1 = compare_sinks(m1, m2)
    r2 = compare_sinks(m1, m2)

    j1 = json.dumps(r1.to_dict(), sort_keys=True)
    j2 = json.dumps(r2.to_dict(), sort_keys=True)
    report(tid, "Repeat call on same inputs = identical JSON", j1 == j2)


# ---------------------------------------------------------------------------
# D1–D3: Dead-Baseline Tests
# ---------------------------------------------------------------------------

def test_d1_dead_baseline_absent():
    """D1: Baseline sink provably_dead_at_baseline=True absent from optimized -> UNKNOWN (not ELIMINATED)."""
    tid = "D1"
    b_sink = _make_sink("b_dead", "foo", provably_dead_at_baseline=True)
    base = ModuleSinks(functions=["foo"], sinks=[b_sink], parse_ok=True)
    opt = ModuleSinks(functions=["foo"], sinks=[], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
        and result.sink_matches[0].match_method == "dead_at_baseline"
        and "dead at baseline" in result.sink_matches[0].notes[0].lower()
    )
    report(tid, "Dead baseline sink absent -> UNKNOWN (not ELIMINATED)", ok,
           f"status={result.sink_matches[0].status.value} method={result.sink_matches[0].match_method}")


def test_d2_dead_baseline_present():
    """D2: Baseline sink provably_dead_at_baseline=True present in optimized -> Still UNKNOWN/dead_at_baseline."""
    tid = "D2"
    b_sink = _make_sink("b_dead", "foo", provably_dead_at_baseline=True)
    o_sink = _make_sink("o_live", "foo", provably_dead_at_baseline=False)
    base = ModuleSinks(functions=["foo"], sinks=[b_sink], parse_ok=True)
    opt = ModuleSinks(functions=["foo"], sinks=[o_sink], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].match_method == "dead_at_baseline"
        and o_sink.sink_id in result.unmatched_optimized_ids
    )
    report(tid, "Dead baseline sink present in opt -> Still UNKNOWN/dead_at_baseline", ok)


def test_d3_all_baseline_dead():
    """D3: All baseline sinks dead -> All UNKNOWN, compare_ok=True, no regression findings."""
    tid = "D3"
    b1 = _make_sink("b1", "f1", ordinal=1, provably_dead_at_baseline=True)
    b2 = _make_sink("b2", "f2", ordinal=2, provably_dead_at_baseline=True)
    base = ModuleSinks(functions=["f1", "f2"], sinks=[b1, b2], parse_ok=True)
    opt = ModuleSinks(functions=["f1", "f2"], sinks=[], parse_ok=True)

    result = compare_sinks(base, opt)
    elim_count = sum(1 for m in result.sink_matches if m.status == GuardStatus.ELIMINATED)
    ok = (
        len(result.sink_matches) == 2
        and all(m.status == GuardStatus.UNKNOWN for m in result.sink_matches)
        and elim_count == 0
        and result.compare_ok is True
    )
    report(tid, "All baseline dead -> All UNKNOWN, 0 regressions, compare_ok=True", ok)


# ---------------------------------------------------------------------------
# P1–P5: Provenance and Inlining Tests
# ---------------------------------------------------------------------------

def test_p1_provenance_inlined_match():
    """P1: Baseline direct sink -> optimized inlined counterpart (same origin_function, source_line)."""
    tid = "P1"
    b = _make_sink(
        "b1", "calc", ordinal=1, origin_function="calc", source_line=25, inlined=False, provenance=Provenance.DIRECT
    )
    o = _make_sink(
        "o1", "main", ordinal=1, origin_function="calc", source_line=25, inlined=True, provenance=Provenance.INLINED
    )
    base = ModuleSinks(functions=["calc"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["main"], sinks=[o], parse_ok=True, provenance_available=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.sink_matches[0].match_method == "provenance"
        and result.sink_matches[0].optimized_sink_ids == ["o1"]
    )
    report(tid, "Baseline direct -> inlined counterpart matched via provenance", ok,
           f"status={result.sink_matches[0].status.value} method={result.sink_matches[0].match_method}")


def test_p2_provenance_unavailable_opt_absent():
    """P2: provenance_available=False on optimized, baseline sink absent -> UNKNOWN, NOT ELIMINATED."""
    tid = "P2"
    b = _make_sink(
        "b1", "f", ordinal=1, origin_function="f", source_line=10, inlined=False, provenance=Provenance.DIRECT
    )
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
    )
    report(tid, "provenance_available=False on opt -> UNKNOWN, NOT ELIMINATED", ok,
           f"status={result.sink_matches[0].status.value}")


def test_p3_provenance_unavailable_both():
    """P3: provenance_available=False on both -> Phase 2 skipped; Phase 3/4 only."""
    tid = "P3"
    b = _make_sink("b1", "f", ordinal=1)
    o = _make_sink("o1", "f", ordinal=1)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["f"], sinks=[o], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.sink_matches[0].match_method == "canonical_text"
    )
    report(tid, "provenance_available=False both -> matched via canonical_text", ok,
           f"status={result.sink_matches[0].status.value} method={result.sink_matches[0].match_method}")


def test_p4_baseline_inlined_sink():
    """P4: Baseline INLINED sink -> optimized INLINED sink in different function."""
    tid = "P4"
    b = _make_sink(
        "b1", "caller1", origin_function="helper", source_line=50, inlined=True, provenance=Provenance.INLINED
    )
    o = _make_sink(
        "o1", "caller2", origin_function="helper", source_line=50, inlined=True, provenance=Provenance.INLINED
    )
    base = ModuleSinks(functions=["caller1"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["caller2"], sinks=[o], parse_ok=True, provenance_available=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.sink_matches[0].match_method == "provenance"
    )
    report(tid, "Baseline INLINED sink matched in optimized different function", ok,
           f"status={result.sink_matches[0].status.value}")


def test_p5_baseline_direct_cloned():
    """P5: Baseline DIRECT sink, optimized function cloned (2 copies) -> PRESERVED (one clone claimed)."""
    tid = "P5"
    b = _make_sink("b1", "f", ordinal=1)
    o1 = _make_sink("o1", "f.clone.1", ordinal=1)
    o2 = _make_sink("o2", "f.clone.2", ordinal=2)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["f.clone.1", "f.clone.2"], sinks=[o1, o2], parse_ok=True)

    result = compare_sinks(base, opt)
    # Since canonical_text matches both clones in other functions (no same_fn), len(cands) == 2 -> ambiguous -> UNKNOWN
    # Or if one is claimed -> PRESERVED. Either way, never ELIMINATED!
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status in (GuardStatus.PRESERVED, GuardStatus.MERGED, GuardStatus.UNKNOWN)
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
    )
    report(tid, "Baseline direct sink with cloned opt sinks -> safe outcome (not ELIMINATED)", ok,
           f"status={result.sink_matches[0].status.value}")


def test_p6_phase2_multi_candidate_ambiguous():
    """P6: Multiple provenance candidates -> recorded in ambiguous_candidates and UNKNOWN notes."""
    tid = "P6"
    b = _make_sink(
        "b1", "f", ordinal=1, origin_function="f", source_line=10, provenance=Provenance.DIRECT
    )
    o1 = _make_sink(
        "o1", "f", ordinal=1, origin_function="f", source_line=10, provenance=Provenance.DIRECT,
        canonical_text="text_diff_1"
    )
    o2 = _make_sink(
        "o2", "f", ordinal=2, origin_function="f", source_line=10, provenance=Provenance.DIRECT,
        canonical_text="text_diff_2"
    )
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["f"], sinks=[o1, o2], parse_ok=True, provenance_available=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].match_method == "ambiguous_multi_candidate"
        and "o1" in result.sink_matches[0].notes[0]
        and "o2" in result.sink_matches[0].notes[0]
    )
    report(tid, "Phase 2 multi-candidate -> ambiguous_multi_candidate with candidate IDs", ok)


# ---------------------------------------------------------------------------
# G1–G8: Tri-State Guardedness Tests
# ---------------------------------------------------------------------------

def test_g1_to_g6_guardedness_truth_table():
    """G1–G8: Guardedness truth table."""
    cases = [
        ("G1", True, True, GuardStatus.PRESERVED, "HIGH", "both guarded -> PRESERVED"),
        ("G2", True, False, GuardStatus.FOLDED, "HIGH", "guarded -> unconditional = FOLDED"),
        ("G3", True, None, GuardStatus.UNKNOWN, "LOW", "guarded -> None = UNKNOWN"),
        ("G4", None, False, GuardStatus.UNKNOWN, "LOW", "None -> False = UNKNOWN"),
        ("G5", False, False, GuardStatus.PRESERVED, "HIGH", "unconditional -> unconditional = PRESERVED"),
        ("G6", None, None, GuardStatus.PRESERVED, "LOW", "None -> None = PRESERVED (uncertain guardedness)"),
        ("G7", False, None, GuardStatus.PRESERVED, "LOW", "False -> None = PRESERVED (uncertain opt guardedness)"),
        ("G8", None, True, GuardStatus.PRESERVED, "LOW", "None -> True = PRESERVED (uncertain base guardedness)"),
    ]

    for tid, b_g, o_g, expected_status, expected_conf, desc in cases:
        b = _make_sink("b", "f", is_guarded=b_g)
        o = _make_sink("o", "f", is_guarded=o_g)
        base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
        opt = ModuleSinks(functions=["f"], sinks=[o], parse_ok=True)

        res = compare_sinks(base, opt)
        actual_status = res.sink_matches[0].status
        actual_conf = res.sink_matches[0].confidence
        passed = (actual_status == expected_status and actual_conf == expected_conf)
        report(tid, desc, passed, f"status={actual_status.value} conf={actual_conf}")


# ---------------------------------------------------------------------------
# E1–E4: No-Provenance ELIMINATED Guard Tests
# ---------------------------------------------------------------------------

def test_e1_no_provenance_absent():
    """E1: provenance_available=False, baseline sink absent -> UNKNOWN, NOT ELIMINATED."""
    tid = "E1"
    b = _make_sink("b1", "f", provably_dead_at_baseline=False)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
    )
    report(tid, "provenance_available=False absent -> UNKNOWN (not ELIMINATED)", ok,
           f"status={result.sink_matches[0].status.value}")


def test_e2_provenance_negative_search_eliminated():
    """E2: All 8 conditions satisfied -> ELIMINATED via provenance negative search."""
    tid = "E2"
    b = _make_sink(
        "b1", "f", origin_function="f", source_line=42, provably_dead_at_baseline=False, provenance=Provenance.DIRECT
    )
    # Optimized module has debug metadata, parse_ok, but zero sinks with matching (origin_function, source_line)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.ELIMINATED
        and result.sink_matches[0].confidence == "HIGH"
        and result.sink_matches[0].match_method == "provenance_negative_search"
    )
    report(tid, "Provenance negative search -> ELIMINATED", ok,
           f"status={result.sink_matches[0].status.value} method={result.sink_matches[0].match_method}")


def test_e3_provenance_base_true_opt_false():
    """E3: provenance_available=True on baseline, False on optimized -> UNKNOWN (not ELIMINATED)."""
    tid = "E3"
    b = _make_sink("b1", "f", origin_function="f", source_line=42, provenance=Provenance.DIRECT)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
    )
    report(tid, "provenance_available opt=False -> UNKNOWN (not ELIMINATED)", ok,
           f"status={result.sink_matches[0].status.value}")


def test_e4_sink_absent_renamed():
    """E4: Sink absent from opt but renamed function -> UNKNOWN (not ELIMINATED)."""
    tid = "E4"
    b = _make_sink("b1", "original_func")
    base = ModuleSinks(functions=["original_func"], sinks=[b], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["renamed_func"], sinks=[], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
    )
    report(tid, "Renamed function without provenance -> UNKNOWN (not ELIMINATED)", ok)


def test_e5_baseline_parse_not_ok_never_eliminated():
    """E5: baseline.parse_ok=False -> UNKNOWN (even with full provenance, never ELIMINATED)."""
    tid = "E5"
    b = _make_sink(
        "b1", "f", origin_function="f", source_line=42, provably_dead_at_baseline=False, provenance=Provenance.DIRECT
    )
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=False, provenance_available=True)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.sink_matches[0].status != GuardStatus.ELIMINATED
        and result.compare_ok is False
    )
    report(tid, "baseline.parse_ok=False -> UNKNOWN (never ELIMINATED)", ok,
           f"status={result.sink_matches[0].status.value} compare_ok={result.compare_ok}")


# ---------------------------------------------------------------------------
# H1–H12: Error and Hostile Inputs
# ---------------------------------------------------------------------------

def test_h1_baseline_parse_not_ok():
    """H1: baseline.parse_ok=False -> compare_ok=False, all matches confidence=LOW, warning emitted."""
    tid = "H1"
    b = _make_sink("b1", "f")
    o = _make_sink("o1", "f")
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=False)
    opt = ModuleSinks(functions=["f"], sinks=[o], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        result.compare_ok is False
        and result.sink_matches[0].confidence == "LOW"
        and any("parse_ok=false" in w.lower() for w in result.comparison_warnings)
    )
    report(tid, "baseline.parse_ok=False -> compare_ok=False, confidence=LOW, warning", ok)


def test_h2_optimized_parse_not_ok():
    """H2: optimized.parse_ok=False -> compare_ok=False, all matches confidence=LOW, warning emitted."""
    tid = "H2"
    b = _make_sink("b1", "f")
    o = _make_sink("o1", "f")
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[o], parse_ok=False)

    result = compare_sinks(base, opt)
    ok = (
        result.compare_ok is False
        and result.sink_matches[0].confidence == "LOW"
        and any("parse_ok=false" in w.lower() for w in result.comparison_warnings)
    )
    report(tid, "optimized.parse_ok=False -> compare_ok=False, confidence=LOW, warning", ok)


def test_h3_empty_baseline():
    """H3: baseline.sinks=[] -> sink_matches=[], 3 unmatched_optimized_ids, no error."""
    tid = "H3"
    base = ModuleSinks(functions=["f"], sinks=[], parse_ok=True)
    o1 = _make_sink("o1", "f", ordinal=1)
    o2 = _make_sink("o2", "f", ordinal=2)
    o3 = _make_sink("o3", "f", ordinal=3)
    opt = ModuleSinks(functions=["f"], sinks=[o1, o2, o3], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 0
        and len(result.unmatched_optimized_ids) == 3
        and result.compare_ok is True
    )
    report(tid, "Empty baseline -> sink_matches=[], 3 unmatched_opt_ids", ok)


def test_h4_empty_optimized():
    """H4: optimized.sinks=[] -> All 3 baseline -> UNKNOWN, NOT ELIMINATED (no provenance)."""
    tid = "H4"
    b1 = _make_sink("b1", "f", ordinal=1)
    b2 = _make_sink("b2", "f", ordinal=2)
    b3 = _make_sink("b3", "f", ordinal=3)
    base = ModuleSinks(functions=["f"], sinks=[b1, b2, b3], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 3
        and all(m.status == GuardStatus.UNKNOWN for m in result.sink_matches)
        and all(m.status != GuardStatus.ELIMINATED for m in result.sink_matches)
    )
    report(tid, "Empty optimized -> All baseline UNKNOWN (not ELIMINATED)", ok)


def test_h5_both_empty():
    """H5: Both sinks empty -> No error, sink_matches=[] and unmatched_optimized_ids=[]."""
    tid = "H5"
    base = ModuleSinks(functions=[], sinks=[], parse_ok=True)
    opt = ModuleSinks(functions=[], sinks=[], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 0
        and len(result.unmatched_optimized_ids) == 0
        and result.compare_ok is True
    )
    report(tid, "Both empty -> No error, empty result", ok)


def test_h6_ambiguous_multi_candidate():
    """H6: Multiple baseline sinks with multiple identical candidates -> Ambiguous -> UNKNOWN."""
    tid = "H6"
    b1 = _make_sink("b1", "f", ordinal=1)
    b2 = _make_sink("b2", "f", ordinal=2)
    o1 = _make_sink("o1", "f", ordinal=1)
    o2 = _make_sink("o2", "f", ordinal=2)
    base = ModuleSinks(functions=["f"], sinks=[b1, b2], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[o1, o2], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 2
        and all(m.status == GuardStatus.UNKNOWN for m in result.sink_matches)
        and all(m.match_method == "ambiguous_multi_candidate" for m in result.sink_matches)
    )
    report(tid, "Multiple identical candidates -> Ambiguous -> UNKNOWN", ok,
           f"statuses={[m.status.value for m in result.sink_matches]}")


def test_h7_baseline_guarded_none_absent():
    """H7: Baseline sink has is_guarded=None, optimized absent -> UNKNOWN."""
    tid = "H7"
    b = _make_sink("b1", "f", is_guarded=None)
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = len(result.sink_matches) == 1 and result.sink_matches[0].status == GuardStatus.UNKNOWN
    report(tid, "Baseline is_guarded=None absent -> UNKNOWN", ok)


def test_h8_exception_safety():
    """H8: Internal exception during comparison -> Caught, returns CompareResult with UNKNOWN."""
    tid = "H8"
    b = _make_sink("b1", "f")
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)

    # Broken object that raises on attribute access
    class BrokenModuleSinks:
        ir_path = None
        parse_ok = True
        parse_warnings = []
        provenance_available = True

        @property
        def sinks(self):
            raise RuntimeError("Forced simulation error")

    broken_opt = BrokenModuleSinks()
    result = compare_sinks(base, broken_opt)  # type: ignore

    ok = (
        isinstance(result, CompareResult)
        and len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.UNKNOWN
        and result.compare_ok is False
        and any("forced simulation error" in w.lower() for w in result.comparison_warnings)
    )
    report(tid, "Exception safety -> Returns CompareResult with UNKNOWN and warning", ok)


def test_h9_determinism_synthetic():
    """H9: Synthetic modules fed twice produce identical JSON serialization."""
    tid = "H9"
    b1 = _make_sink("b1", "f", ordinal=1)
    b2 = _make_sink("b2", "g", ordinal=2)
    o1 = _make_sink("o1", "f", ordinal=1)
    base = ModuleSinks(functions=["f", "g"], sinks=[b1, b2], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[o1], parse_ok=True)

    r1 = compare_sinks(base, opt)
    r2 = compare_sinks(base, opt)
    ok = json.dumps(r1.to_dict(), sort_keys=True) == json.dumps(r2.to_dict(), sort_keys=True)
    report(tid, "Synthetic inputs fed twice -> Identical JSON", ok)


def test_h10_optimized_more_sinks():
    """H10: Optimized has more sinks than baseline -> unmatched_optimized_ids populated."""
    tid = "H10"
    b = _make_sink("b1", "f", ordinal=1)
    o1 = _make_sink("o1", "f", ordinal=1)
    o2 = _make_sink(
        "o2",
        "f",
        ordinal=2,
        sink_class=SinkClass.ABORT_CALL,
        target_symbol="@abort",
        canonical_text="call void @abort()",
    )
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[o1, o2], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.unmatched_optimized_ids == ["o2"]
    )
    report(tid, "Optimized has more sinks -> unmatched_optimized_ids populated", ok,
           f"unmatched={result.unmatched_optimized_ids}")


def test_h11_sink_id_not_identity_key():
    """H11: Sinks match even when sink_id values differ cross-optimization."""
    tid = "H11"
    b = _make_sink("sink_safe_copy_if.then_1", "safe_copy")
    o = _make_sink("sink_safe_copy_entry_99", "safe_copy")
    base = ModuleSinks(functions=["safe_copy"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["safe_copy"], sinks=[o], parse_ok=True)

    result = compare_sinks(base, opt)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.sink_matches[0].optimized_sink_ids == ["sink_safe_copy_entry_99"]
    )
    report(tid, "sink_id differences do not prevent matching", ok)


def test_h12_empty_canonical_text():
    """H12: Empty canonical_text skips Phase 3 and falls back safely."""
    tid = "H12"
    b = _make_sink("b1", "f", canonical_text="", instruction_text="")
    o = _make_sink("o1", "f", canonical_text="", instruction_text="")
    base = ModuleSinks(functions=["f"], sinks=[b], parse_ok=True)
    opt = ModuleSinks(functions=["f"], sinks=[o], parse_ok=True)

    result = compare_sinks(base, opt)
    # Should be matched via Phase 4a (same_function_weak)
    ok = (
        len(result.sink_matches) == 1
        and result.sink_matches[0].status == GuardStatus.PRESERVED
        and result.sink_matches[0].match_method == "same_function_weak"
    )
    report(tid, "Empty canonical_text falls back to Phase 4a weak matching", ok,
           f"method={result.sink_matches[0].match_method}")


# ---------------------------------------------------------------------------
# R1–R3: Regression Safety Tests
# ---------------------------------------------------------------------------

def test_r1_dead_baseline_never_eliminated():
    """R1: provably_dead_at_baseline=True sink -> assert status != ELIMINATED."""
    tid = "R1"
    b = _make_sink("b_dead", "foo", provably_dead_at_baseline=True)
    base = ModuleSinks(functions=["foo"], sinks=[b], parse_ok=True, provenance_available=True)
    opt = ModuleSinks(functions=["foo"], sinks=[], parse_ok=True, provenance_available=True)

    res = compare_sinks(base, opt)
    ok = res.sink_matches[0].status != GuardStatus.ELIMINATED
    report(tid, "Dead baseline sink status is never ELIMINATED", ok)


def test_r2_all_unknown_zero_regressions():
    """R2: When all baseline sinks are UNKNOWN, 0 ELIMINATED entries exist."""
    tid = "R2"
    b1 = _make_sink("b1", "f", ordinal=1)
    b2 = _make_sink("b2", "f", ordinal=2)
    base = ModuleSinks(functions=["f"], sinks=[b1, b2], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    res = compare_sinks(base, opt)
    elim_count = sum(1 for m in res.sink_matches if m.status == GuardStatus.ELIMINATED)
    ok = (
        len(res.sink_matches) == 2
        and all(m.status == GuardStatus.UNKNOWN for m in res.sink_matches)
        and elim_count == 0
    )
    report(tid, "All unknown baseline sinks -> exactly 0 regressions", ok)


def test_r3_all_live_empty_opt_no_provenance():
    """R3: All live baseline sinks with empty opt and no provenance -> All UNKNOWN, 0 ELIMINATED."""
    tid = "R3"
    b1 = _make_sink("b1", "f", ordinal=1, provably_dead_at_baseline=False)
    b2 = _make_sink("b2", "f", ordinal=2, provably_dead_at_baseline=False)
    base = ModuleSinks(functions=["f"], sinks=[b1, b2], parse_ok=True, provenance_available=False)
    opt = ModuleSinks(functions=["f"], sinks=[], parse_ok=True, provenance_available=False)

    res = compare_sinks(base, opt)
    elim_count = sum(1 for m in res.sink_matches if m.status == GuardStatus.ELIMINATED)
    ok = (
        len(res.sink_matches) == 2
        and all(m.status == GuardStatus.UNKNOWN for m in res.sink_matches)
        and elim_count == 0
    )
    report(tid, "Live baseline with empty opt (no provenance) -> 0 ELIMINATED", ok)


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_all_tests():
    print("\n" + "=" * 65)
    print("TOACD MOO Stage 6 — Security Chunk 2 (compare.py) Unit Tests")
    print("=" * 65 + "\n")

    print("--- C1–C7: Happy Path & Fixture Tests ---")
    test_c1_to_c4_frozen_ir_o0_vs_o1()
    test_c5_o1_vs_o2()
    test_c6_o2_vs_o3()
    test_c7_json_determinism()

    print("\n--- D1–D3: Dead-Baseline Tests ---")
    test_d1_dead_baseline_absent()
    test_d2_dead_baseline_present()
    test_d3_all_baseline_dead()

    print("\n--- P1–P6: Provenance and Inlining Tests ---")
    test_p1_provenance_inlined_match()
    test_p2_provenance_unavailable_opt_absent()
    test_p3_provenance_unavailable_both()
    test_p4_baseline_inlined_sink()
    test_p5_baseline_direct_cloned()
    test_p6_phase2_multi_candidate_ambiguous()

    print("\n--- G1–G8: Tri-State Guardedness Truth Table Tests ---")
    test_g1_to_g6_guardedness_truth_table()

    print("\n--- E1–E5: No-Provenance ELIMINATED Guard Tests ---")
    test_e1_no_provenance_absent()
    test_e2_provenance_negative_search_eliminated()
    test_e3_provenance_base_true_opt_false()
    test_e4_sink_absent_renamed()
    test_e5_baseline_parse_not_ok_never_eliminated()

    print("\n--- H1–H12: Error and Hostile Inputs Tests ---")
    test_h1_baseline_parse_not_ok()
    test_h2_optimized_parse_not_ok()
    test_h3_empty_baseline()
    test_h4_empty_optimized()
    test_h5_both_empty()
    test_h6_ambiguous_multi_candidate()
    test_h7_baseline_guarded_none_absent()
    test_h8_exception_safety()
    test_h9_determinism_synthetic()
    test_h10_optimized_more_sinks()
    test_h11_sink_id_not_identity_key()
    test_h12_empty_canonical_text()

    print("\n--- R1–R3: Regression Safety Tests ---")
    test_r1_dead_baseline_never_eliminated()
    test_r2_all_unknown_zero_regressions()
    test_r3_all_live_empty_opt_no_provenance()

    n_pass = sum(1 for _, _, r in _results if r == "PASS")
    n_fail = sum(1 for _, _, r in _results if r == "FAIL")
    n_skip = sum(1 for _, _, r in _results if r == "SKIP")
    total = len(_results)

    print("\n" + "=" * 65)
    print(f"Results: {n_pass}/{total} passed, {n_fail} failed, {n_skip} skipped")
    print("=" * 65 + "\n")

    if n_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
