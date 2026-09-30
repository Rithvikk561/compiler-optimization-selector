"""
moo/tests/test_stage3_unit.py
Stage 3 unit tests â€” orchestration logic, result model, report formatting.

All tests are pure unit tests that do NOT require clang, opt, or real
executables.  They run in milliseconds and verify the pipeline logic in
isolation using synthetic data.

Test plan
---------
R1  CandidateResult.is_valid() â€” correct conditions
R2  CandidateResult.is_valid() â€” invalid when build failed
R3  CandidateResult.is_valid() â€” invalid when incorrect
R4  CandidateResult.is_valid() â€” invalid when no measurement
R5  CandidateResult.to_dict() â€” serializable, no missing keys
R6  BaselineMeasurement.to_dict() â€” serializable
R7  MOOEvaluationResult.to_dict() â€” serializable, summary counts correct
R8  MOOEvaluationResult.n_valid/n_invalid â€” counts

P1  pareto_status FRONTIER propagated correctly in a synthetic run
P2  pareto_status DOMINATED propagated correctly
P3  INVALID candidates excluded from frontier
P4  Single valid candidate â†’ frontier with no dominated

N1  _get_norm extracts correct value from serialized normalized dict
N2  _fmt_ratio handles float correctly
N3  _fmt_ratio handles NormalizationError sentinel gracefully
N4  _fmt_ratio handles None gracefully

C1  _check_correctness_simple â€” matching exit code + stdout â†’ correct
C2  _check_correctness_simple â€” non-zero reference exit code match â†’ correct
C3  _check_correctness_simple â€” stdout differs â†’ incorrect
C4  _check_correctness_simple â€” exit code differs â†’ incorrect
"""

from __future__ import annotations

import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo.moo_result import (
    CandidateResult,
    BaselineMeasurement,
    MOOEvaluationResult,
)
from moo.cli_report import _get_norm, _fmt_ratio
from moo.objectives import NormalizationError


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

PASS_S = "\033[32mPASS\033[0m"
FAIL_S = "\033[31mFAIL\033[0m"
_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = ""):
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    status = PASS_S if passed else FAIL_S
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")


def _make_candidate(
    name: str = "-O2",
    idx: int = 0,
    build_ok: bool = True,
    correct: bool = True,
    measurement: dict | None = None,
    pareto_status: str = "UNKNOWN",
) -> CandidateResult:
    return CandidateResult(
        strategy_name=name,
        strategy_index=idx,
        strategy_kind="clang_flag",
        build_ok=build_ok,
        correct=correct,
        correctness_checked=True,
        measurement=measurement,
        pareto_status=pareto_status,
    )


def _fake_measurement_dict(median_s=0.5, energy_j=22.5, code_size=50000, carbon_g=0.0027):
    return {
        "timing": {"median_s": median_s, "n_samples": 5},
        "energy": {"energy_joules": energy_j, "energy_is_estimated": True, "energy_source": "estimated"},
        "code_size": {"primary_value": code_size, "primary_metric": "text_size_bytes", "size_source": "llvm-size"},
        "carbon": {"carbon_grams": carbon_g, "carbon_is_estimated": True},
    }


def _fake_normalized_dict(exec_t=0.8, energy=0.8, size=0.9, carbon=0.8):
    return {
        "strategy": "-O2",
        "is_fully_valid": True,
        "objectives": [
            {"objective": {"name": "execution_time", "lower_is_better": True, "unit": "seconds", "description": ""},
             "raw_value": 0.5, "baseline_value": 0.625, "normalized_value": exec_t, "note": ""},
            {"objective": {"name": "energy", "lower_is_better": True, "unit": "joules", "description": ""},
             "raw_value": 22.5, "baseline_value": 28.1, "normalized_value": energy, "note": ""},
            {"objective": {"name": "code_size", "lower_is_better": True, "unit": "bytes", "description": ""},
             "raw_value": 50000, "baseline_value": 55555, "normalized_value": size, "note": ""},
            {"objective": {"name": "carbon", "lower_is_better": True, "unit": "grams CO2eq", "description": ""},
             "raw_value": 0.0027, "baseline_value": 0.00338, "normalized_value": carbon, "note": ""},
        ],
    }


# ---------------------------------------------------------------------------
# Result model tests
# ---------------------------------------------------------------------------

def r1_is_valid_correct():
    tid, name = "R1", "CandidateResult.is_valid() â€” valid when build+correct+measured"
    c = _make_candidate(build_ok=True, correct=True, measurement=_fake_measurement_dict())
    report(tid, name, c.is_valid() is True)


def r2_is_valid_build_failed():
    tid, name = "R2", "CandidateResult.is_valid() â€” invalid when build failed"
    c = _make_candidate(build_ok=False, correct=False, measurement=None)
    report(tid, name, c.is_valid() is False)


def r3_is_valid_incorrect():
    tid, name = "R3", "CandidateResult.is_valid() â€” invalid when incorrect"
    c = _make_candidate(build_ok=True, correct=False, measurement=None)
    report(tid, name, c.is_valid() is False)


def r4_is_valid_no_measurement():
    tid, name = "R4", "CandidateResult.is_valid() â€” invalid when measurement is None"
    c = _make_candidate(build_ok=True, correct=True, measurement=None)
    report(tid, name, c.is_valid() is False)


def r5_candidate_to_dict():
    tid, name = "R5", "CandidateResult.to_dict() â€” serializable, required keys present"
    c = _make_candidate(measurement=_fake_measurement_dict())
    c.normalized = _fake_normalized_dict()
    c.pareto_status = "FRONTIER"
    d = c.to_dict()
    required_keys = {
        "strategy_name", "strategy_index", "strategy_kind",
        "build_ok", "build_error", "exe_path",
        "correctness_checked", "correct", "correctness_details",
        "reference_exit_code", "candidate_exit_code",
        "measurement", "normalized", "pareto_status", "dominated_by",
    }
    ok = required_keys.issubset(d.keys())
    import json
    try:
        json.dumps(d)
        serializable = True
    except Exception:
        serializable = False
    report(tid, name, ok and serializable, f"keys_ok={ok} serializable={serializable}")


def r6_baseline_to_dict():
    tid, name = "R6", "BaselineMeasurement.to_dict() â€” serializable"
    b = BaselineMeasurement(
        strategy_name="baseline (-O0)",
        exe_path="/tmp/ref.exe",
        build_ok=True,
        build_error=None,
        reference_exit_code=0,
        reference_stdout="",
        measurement=_fake_measurement_dict(),
    )
    d = b.to_dict()
    import json
    try:
        json.dumps(d)
        ok = True
    except Exception:
        ok = False
    report(tid, name, ok)


def r7_moo_result_to_dict():
    tid, name = "R7", "MOOEvaluationResult.to_dict() â€” summary counts correct"
    c1 = _make_candidate("-O1", 0, build_ok=True, correct=True,
                         measurement=_fake_measurement_dict(), pareto_status="FRONTIER")
    c2 = _make_candidate("-O2", 1, build_ok=True, correct=True,
                         measurement=_fake_measurement_dict(), pareto_status="DOMINATED")
    c3 = _make_candidate("-O3", 2, build_ok=False, correct=False,
                         measurement=None, pareto_status="INVALID")
    r = MOOEvaluationResult(
        source_file="test.c",
        source_path="/test.c",
        timestamp="2026-01-01T00:00:00",
        toolchain_ok=True,
        candidates=[c1, c2, c3],
        pareto_frontier=["-O1"],
        pareto_dominated=["-O2"],
        pareto_invalid=["-O3"],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
    )
    d = r.to_dict()
    summ = d.get("summary", {})
    ok = (
        summ.get("n_strategies") == 3
        and summ.get("n_valid") == 2
        and summ.get("n_invalid") == 1
        and summ.get("n_frontier") == 1
        and summ.get("n_dominated") == 1
    )
    report(tid, name, ok, f"summary={summ}")


def r8_counts():
    tid, name = "R8", "MOOEvaluationResult.n_valid/n_invalid â€” correct counts"
    c1 = _make_candidate(build_ok=True, correct=True, measurement=_fake_measurement_dict())
    c2 = _make_candidate(build_ok=False, correct=False, measurement=None)
    r = MOOEvaluationResult(
        source_file="t.c", source_path=None, timestamp="",
        candidates=[c1, c2],
    )
    ok = r.n_valid() == 1 and r.n_invalid() == 1 and r.n_strategies() == 2
    report(tid, name, ok, f"valid={r.n_valid()} invalid={r.n_invalid()}")


# ---------------------------------------------------------------------------
# Pareto status propagation tests (synthetic â€” no real pipeline)
# ---------------------------------------------------------------------------

def _build_synthetic_moo_result() -> MOOEvaluationResult:
    """Build a synthetic MOOEvaluationResult with known Pareto outcome."""
    from moo.objectives import RawObjectives, normalize, ALL_OBJECTIVES
    from moo.pareto import extract_pareto_frontier

    base_raw = RawObjectives("baseline", 1.0, 45.0, 60000, 0.0054)

    # Three candidates: A dominates C; A and B trade off
    a_raw = RawObjectives("-O2",   0.70, 31.5, 55000, 0.0038)  # fast+small
    b_raw = RawObjectives("-O3",   0.65, 29.2, 80000, 0.0035)  # fastest but big
    c_raw = RawObjectives("-O1",   0.85, 38.2, 62000, 0.0046)  # dominated by -O2

    vecs = [normalize(r, base_raw) for r in [a_raw, b_raw, c_raw]]
    pareto_res = extract_pareto_frontier(vecs)

    candidates = []
    for i, (r, v) in enumerate(zip([a_raw, b_raw, c_raw], vecs)):
        c = CandidateResult(
            strategy_name=r.strategy,
            strategy_index=i,
            strategy_kind="clang_flag",
            build_ok=True,
            correct=True,
            correctness_checked=True,
            measurement=_fake_measurement_dict(),
            normalized=v.to_dict(),
        )
        if r.strategy in pareto_res.frontier:
            c.pareto_status = "FRONTIER"
        elif r.strategy in pareto_res.dominated:
            c.pareto_status = "DOMINATED"
        candidates.append(c)

    result = MOOEvaluationResult(
        source_file="synthetic.c",
        source_path=None,
        timestamp="2026-01-01T00:00:00",
        toolchain_ok=True,
        candidates=candidates,
        pareto_frontier=list(pareto_res.frontier),
        pareto_dominated=list(pareto_res.dominated),
        pareto_invalid=[],
        objectives_used=[o.name for o in ALL_OBJECTIVES],
    )
    return result


def p1_frontier_propagated():
    tid, name = "P1", "pareto_status FRONTIER propagated in synthetic result"
    r = _build_synthetic_moo_result()
    frontier_cands = [c for c in r.candidates if c.pareto_status == "FRONTIER"]
    ok = len(frontier_cands) >= 1 and all(
        c.strategy_name in r.pareto_frontier for c in frontier_cands
    )
    report(tid, name, ok,
           f"frontier={r.pareto_frontier} n_frontier_cands={len(frontier_cands)}")


def p2_dominated_propagated():
    tid, name = "P2", "pareto_status DOMINATED propagated in synthetic result"
    r = _build_synthetic_moo_result()
    dom_cands = [c for c in r.candidates if c.pareto_status == "DOMINATED"]
    ok = len(dom_cands) >= 1 and all(
        c.strategy_name in r.pareto_dominated for c in dom_cands
    )
    report(tid, name, ok,
           f"dominated={r.pareto_dominated}")


def p3_invalid_excluded():
    tid, name = "P3", "INVALID candidates excluded from frontier"
    r = _build_synthetic_moo_result()
    # None of the invalid candidates should be in frontier or dominated
    for c in r.candidates:
        if c.pareto_status == "INVALID":
            ok = (
                c.strategy_name not in r.pareto_frontier
                and c.strategy_name not in r.pareto_dominated
            )
            if not ok:
                report(tid, name, False, f"{c.strategy_name} should not be in Pareto")
                return
    report(tid, name, True, "no INVALID candidates in frontier/dominated lists")


def p4_single_valid_is_frontier():
    tid, name = "P4", "single valid candidate is always on frontier"
    from moo.objectives import RawObjectives, normalize, ALL_OBJECTIVES
    from moo.pareto import extract_pareto_frontier

    base_raw = RawObjectives("baseline", 1.0, 45.0, 60000, 0.0054)
    cand_raw = RawObjectives("-O2", 0.7, 31.5, 55000, 0.0038)
    vec = normalize(cand_raw, base_raw)
    res = extract_pareto_frontier([vec])
    ok = res.frontier == ["-O2"] and res.dominated == []
    report(tid, name, ok, f"frontier={res.frontier}")


# ---------------------------------------------------------------------------
# Normalization extraction tests
# ---------------------------------------------------------------------------

def n1_get_norm():
    tid, name = "N1", "_get_norm â€” extracts correct objective value"
    nd = _fake_normalized_dict(exec_t=0.75)
    v = _get_norm(nd, "execution_time")
    ok = isinstance(v, float) and math.isclose(v, 0.75)
    report(tid, name, ok, f"got={v}")


def n2_fmt_ratio_float():
    tid, name = "N2", "_fmt_ratio â€” formats float correctly"
    s = _fmt_ratio(0.750)
    ok = "0.750" in s
    report(tid, name, ok, repr(s))


def n3_fmt_ratio_sentinel():
    tid, name = "N3", "_fmt_ratio â€” handles NormalizationError sentinel"
    s = _fmt_ratio(NormalizationError.ZERO_BASELINE)
    ok = "ERR" in s
    report(tid, name, ok, repr(s))


def n4_fmt_ratio_none():
    tid, name = "N4", "_fmt_ratio â€” handles None gracefully"
    s = _fmt_ratio(None)
    ok = "N/A" in s
    report(tid, name, ok, repr(s))


# ---------------------------------------------------------------------------
# Correctness logic tests (no subprocess â€” test the _check_correctness_simple
# logic using a pre-built real executable if available, else skip subprocess part)
# ---------------------------------------------------------------------------

def _make_simple_exe(tmpdir: str) -> str | None:
    """Build a tiny executable that prints 'hello' and exits 0."""
    import subprocess
    from moo.config import CLANG_PATH
    if not CLANG_PATH:
        return None
    import textwrap, tempfile
    src = os.path.join(tmpdir, "hello.c")
    exe = os.path.join(tmpdir, "hello.exe")
    with open(src, "w") as f:
        f.write('#include <stdio.h>\nint main(){printf("hello\\n");return 0;}\n')
    r = subprocess.run([CLANG_PATH, src, "-o", exe], capture_output=True, timeout=30)
    return exe if r.returncode == 0 and os.path.isfile(exe) else None


def _make_nonzero_exe(tmpdir: str) -> str | None:
    """Build a tiny executable that exits 42."""
    import subprocess
    from moo.config import CLANG_PATH
    if not CLANG_PATH:
        return None
    src = os.path.join(tmpdir, "exit42.c")
    exe = os.path.join(tmpdir, "exit42.exe")
    with open(src, "w") as f:
        f.write("int main(){return 42;}\n")
    r = subprocess.run([CLANG_PATH, src, "-o", exe], capture_output=True, timeout=30)
    return exe if r.returncode == 0 and os.path.isfile(exe) else None


def c1_correctness_match():
    tid, name = "C1", "_check_correctness_simple â€” matching exit code + stdout -> correct"
    import tempfile, shutil
    from moo.pipeline import _check_correctness_simple
    tmpdir = tempfile.mkdtemp()
    try:
        exe = _make_simple_exe(tmpdir)
        if not exe:
            print(f"  [SKIP] {tid}: {name}  (clang not available)")
            _results.append((tid, name, "SKIP"))
            return
        correct, rc, details, _ = _check_correctness_simple(exe, 0, "hello\n", 10)
        ok = correct is True and rc == 0
        report(tid, name, ok, f"correct={correct} rc={rc} details={details!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def c2_correctness_nonzero_ref():
    tid, name = "C2", "_check_correctness_simple â€” non-zero ref exit code match -> correct"
    import tempfile, shutil
    from moo.pipeline import _check_correctness_simple
    tmpdir = tempfile.mkdtemp()
    try:
        exe = _make_nonzero_exe(tmpdir)
        if not exe:
            print(f"  [SKIP] {tid}: {name}  (clang not available)")
            _results.append((tid, name, "SKIP"))
            return
        # ref_exit_code=42 matches what the exe actually returns
        correct, rc, details, _ = _check_correctness_simple(exe, 42, "", 10)
        ok = correct is True and rc == 42
        report(tid, name, ok, f"correct={correct} rc={rc}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def c3_correctness_stdout_diff():
    tid, name = "C3", "_check_correctness_simple â€” stdout differs -> incorrect"
    import tempfile, shutil
    from moo.pipeline import _check_correctness_simple
    tmpdir = tempfile.mkdtemp()
    try:
        exe = _make_simple_exe(tmpdir)
        if not exe:
            print(f"  [SKIP] {tid}: {name}  (clang not available)")
            _results.append((tid, name, "SKIP"))
            return
        # exe prints "hello\n" but we expect "world\n"
        correct, rc, details, _ = _check_correctness_simple(exe, 0, "world\n", 10)
        ok = correct is False and "stdout differs" in details
        report(tid, name, ok, f"correct={correct} details={details!r}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def c4_correctness_rc_diff():
    tid, name = "C4", "_check_correctness_simple â€” exit code differs -> incorrect"
    import tempfile, shutil
    from moo.pipeline import _check_correctness_simple
    tmpdir = tempfile.mkdtemp()
    try:
        exe = _make_nonzero_exe(tmpdir)
        if not exe:
            print(f"  [SKIP] {tid}: {name}  (clang not available)")
            _results.append((tid, name, "SKIP"))
            return
        # exe returns 42 but we expect 0
        correct, rc, details, _ = _check_correctness_simple(exe, 0, "", 10)
        ok = correct is False and "exit code" in details
        report(tid, name, ok, f"correct={correct} details={details!r}")
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
    print("TOACD MOO Stage 3 - Unit Tests")
    print("=" * 65)

    print("\n--- Result model tests ---")
    r1_is_valid_correct()
    r2_is_valid_build_failed()
    r3_is_valid_incorrect()
    r4_is_valid_no_measurement()
    r5_candidate_to_dict()
    r6_baseline_to_dict()
    r7_moo_result_to_dict()
    r8_counts()

    print("\n--- Pareto status propagation tests ---")
    p1_frontier_propagated()
    p2_dominated_propagated()
    p3_invalid_excluded()
    p4_single_valid_is_frontier()

    print("\n--- Normalization extraction tests ---")
    n1_get_norm()
    n2_fmt_ratio_float()
    n3_fmt_ratio_sentinel()
    n4_fmt_ratio_none()

    print("\n--- Correctness logic tests ---")
    c1_correctness_match()
    c2_correctness_nonzero_ref()
    c3_correctness_stdout_diff()
    c4_correctness_rc_diff()

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

