"""
moo/tests/test_stage5_measurement_quality.py
Stage 5 focused tests: Surface Measurement Quality in MOO Results (Week 5 Change #2).

All tests are deterministic and clang-free unit tests.

Tests
-----
Q1  Mocked measurement execution -> MOOEvaluationResult.to_dict() -> quality block appears
Q2  CV is serialized exactly
Q3  Timeout/error counts serialized, timeout NOT counted as error
Q4  Reliable timing produces status="reliable" and no warnings
Q5  Unreliable timing produces "unreliable" with readable warnings citing recorded facts
Q6  Legacy/pre-Week-5 measurement dictionaries produce "unknown", legacy_missing, None counts/CV
Q7  Partial/malformed measurement dictionaries never raise
Q8  Overall status precedence: unreliable > unknown > reliable
Q9  None measurement, missing baseline, and empty candidates handled safely
Q10 Pareto behavior and legacy keys completely unchanged
Q11 print_moo_summary displays warnings for unreliable/unknown and stays quiet for reliable
Q12 selector_bridge can still load a report containing measurement_quality
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_PARENT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _MOO_PARENT not in sys.path:
    sys.path.insert(0, _MOO_PARENT)

from moo.measurement_quality import assess_measurement, build_measurement_quality
from moo.moo_result import CandidateResult, BaselineMeasurement, MOOEvaluationResult
from moo.cli_report import print_moo_summary
from moo import selector_bridge
from moo.pareto import extract_pareto_frontier


# ---------------------------------------------------------------------------
# Test infrastructure
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


def skip(tid: str, name: str, reason: str):
    _results.append((tid, name, "SKIP"))
    print(f"  [{SKIP}] {tid}: {name}  (skipped: {reason})")


# ---------------------------------------------------------------------------
# Synthetic test fixtures (clang-free)
# ---------------------------------------------------------------------------

def _make_measurement_dict(
    median_s: float = 0.020,
    cv: float = 0.05,
    n_samples: int = 10,
    n_timeouts: int = 0,
    n_errors: int = 0,
    timing_is_reliable: bool | None = True,
    energy_joules: float = 0.9,
    code_size_bytes: int = 62800,
    carbon_grams: float = 0.0001,
) -> dict:
    """Create a synthetic Week 5 MeasurementResult.to_dict() payload."""
    return {
        "strategy": "-O2",
        "exe_path": "/fake/exe",
        "warmup_runs": 3,
        "measure_runs": n_samples,
        "raw_samples_ns": [int(median_s * 1e9)] * n_samples,
        "timing": {
            "n_samples": n_samples,
            "median_ns": median_s * 1e9,
            "min_ns": (median_s * 0.95) * 1e9,
            "max_ns": (median_s * 1.05) * 1e9,
            "mean_ns": median_s * 1e9,
            "stdev_ns": (median_s * cv) * 1e9,
            "median_s": median_s,
            "mean_s": median_s,
            "cv": cv,
            "n_timeouts": n_timeouts,
        },
        "last_return_code": 0,
        "last_stdout": "",
        "last_stderr": "",
        "all_return_codes": [0] * n_samples,
        "code_size": {
            "file_path": "/fake/exe",
            "file_size_bytes": code_size_bytes + 4000,
            "text_size_bytes": code_size_bytes,
            "data_size_bytes": 100,
            "bss_size_bytes": 50,
            "size_source": "llvm-size .text section",
            "primary_metric": "text_size_bytes",
            "primary_value": code_size_bytes,
        },
        "energy": {
            "energy_joules": energy_joules,
            "energy_source": "estimated: elapsed_time * TDP(45.0W)",
            "energy_is_estimated": True,
        },
        "carbon": {
            "carbon_grams": carbon_grams,
            "grid_intensity_g_per_kwh": 436.0,
            "grid_intensity_source": "IEA 2023",
            "energy_source": "estimated",
            "carbon_is_estimated": True,
        },
        "measurement_error": None,
        "n_timeouts": n_timeouts,
        "n_errors": n_errors,
        "timing_is_reliable": timing_is_reliable,
    }


def _make_eval_result(
    base_m: dict | None,
    cand_ms: list[tuple[str, int, dict | None]],
) -> MOOEvaluationResult:
    """Assemble a synthetic MOOEvaluationResult."""
    baseline = None
    if base_m is not None:
        baseline = BaselineMeasurement(
            strategy_name="baseline (-O0)",
            exe_path="/fake/base.exe",
            build_ok=True,
            build_error=None,
            reference_exit_code=0,
            reference_stdout="",
            measurement=base_m,
        )

    candidates = []
    for name, idx, m in cand_ms:
        c = CandidateResult(
            strategy_name=name,
            strategy_index=idx,
            strategy_kind="clang_flag",
            build_ok=(m is not None),
            build_error=None if m is not None else "Build failed",
            exe_path=f"/fake/{name}.exe" if m is not None else None,
            correctness_checked=True,
            correct=True,
            measurement=m,
            pareto_status="FRONTIER" if m is not None else "INVALID",
        )
        candidates.append(c)

    return MOOEvaluationResult(
        source_file="test_program.c",
        source_path="/fake/test_program.c",
        timestamp="2026-10-01T17:00:00",
        toolchain_ok=True,
        baseline=baseline,
        candidates=candidates,
        pareto_frontier=[c.strategy_name for c in candidates if c.build_ok],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
    )


# ---------------------------------------------------------------------------
# Tests Q1–Q12
# ---------------------------------------------------------------------------

def q1_quality_block_appears():
    """Q1: Mocked measurement -> MOOEvaluationResult.to_dict() -> quality block appears."""
    tid, name = "Q1", "quality block appears in MOOEvaluationResult.to_dict()"
    try:
        m_base = _make_measurement_dict(median_s=0.030, cv=0.02, timing_is_reliable=True)
        m_cand = _make_measurement_dict(median_s=0.020, cv=0.03, timing_is_reliable=True)

        res = _make_eval_result(m_base, [("-O2", 0, m_cand)])
        d = res.to_dict()

        has_key = "measurement_quality" in d
        mq = d.get("measurement_quality", {})
        schema_ok = mq.get("schema_version") == 1
        status_ok = mq.get("status") in ("reliable", "unreliable", "unknown")
        has_base = "baseline" in mq and isinstance(mq["baseline"], dict)
        has_cands = "candidates" in mq and isinstance(mq["candidates"], list)
        has_counts = "n_reliable" in mq and "n_unreliable" in mq and "n_unknown" in mq
        has_warnings = "warnings" in mq and isinstance(mq["warnings"], list)

        ok = has_key and schema_ok and status_ok and has_base and has_cands and has_counts and has_warnings
        report(tid, name, ok, f"schema_version={mq.get('schema_version')} status={mq.get('status')}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q2_cv_serialized_exactly():
    """Q2: Verify CV is serialized exactly without alteration."""
    tid, name = "Q2", "CV serialized exactly in quality assessment"
    try:
        exact_cv = 0.04251789
        m_cand = _make_measurement_dict(cv=exact_cv, timing_is_reliable=True)
        assessed = assess_measurement(m_cand)

        cv_val = assessed.get("cv")
        ok = cv_val is not None and abs(cv_val - exact_cv) < 1e-12
        report(tid, name, ok, f"expected={exact_cv} got={cv_val}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q3_timeout_and_error_counts():
    """Q3: Verify timeout/error counts serialized and timeout NOT counted as error."""
    tid, name = "Q3", "timeout and error counts serialized correctly"
    try:
        m = _make_measurement_dict(
            n_timeouts=3,
            n_errors=1,
            timing_is_reliable=False,
        )
        assessed = assess_measurement(m)

        to_ok = assessed.get("n_timeouts") == 3
        err_ok = assessed.get("n_errors") == 1
        ok = to_ok and err_ok
        report(tid, name, ok, f"n_timeouts={assessed.get('n_timeouts')} n_errors={assessed.get('n_errors')}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q4_reliable_timing_no_warnings():
    """Q4: Reliable timing produces status='reliable' and empty warnings list."""
    tid, name = "Q4", "reliable timing -> status='reliable' and no warnings"
    try:
        m_base = _make_measurement_dict(cv=0.01, n_timeouts=0, n_errors=0, timing_is_reliable=True)
        m_cand = _make_measurement_dict(cv=0.02, n_timeouts=0, n_errors=0, timing_is_reliable=True)

        mq = build_measurement_quality(m_base, [{"strategy_name": "-O2", "strategy_index": 0, "measurement": m_cand}])

        status_reliable = mq.get("status") == "reliable"
        base_status_reliable = mq.get("baseline", {}).get("status") == "reliable"
        cand_status_reliable = mq.get("candidates", [])[0].get("status") == "reliable"
        base_no_warnings = mq.get("baseline", {}).get("warnings") == []
        cand_no_warnings = mq.get("candidates", [])[0].get("warnings") == []
        top_no_warnings = mq.get("warnings") == []
        counts_ok = mq.get("n_reliable") == 1 and mq.get("n_unreliable") == 0 and mq.get("n_unknown") == 0

        ok = (
            status_reliable
            and base_status_reliable
            and cand_status_reliable
            and base_no_warnings
            and cand_no_warnings
            and top_no_warnings
            and counts_ok
        )
        report(tid, name, ok, f"overall_status={mq.get('status')} warnings={mq.get('warnings')}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q5_unreliable_timing_readable_warnings():
    """Q5: Unreliable timing produces 'unreliable' with readable warnings citing facts."""
    tid, name = "Q5", "unreliable timing -> status='unreliable' and readable warnings"
    try:
        # Case A: noisy CV (25.0%)
        m_noisy = _make_measurement_dict(cv=0.25, n_samples=10, n_timeouts=0, n_errors=0, timing_is_reliable=False)
        a_noisy = assess_measurement(m_noisy)
        ok_a = (
            a_noisy["status"] == "unreliable"
            and len(a_noisy["warnings"]) >= 2
            and "UNRELIABLE" in a_noisy["warnings"][0]
            and "25.0%" in a_noisy["warnings"][0]
            and "10 samples" in a_noisy["warnings"][0]
        )

        # Case B: timeout present
        m_to = _make_measurement_dict(cv=0.01, n_samples=5, n_timeouts=1, n_errors=0, timing_is_reliable=False)
        a_to = assess_measurement(m_to)
        ok_b = (
            a_to["status"] == "unreliable"
            and "1 timeouts" in a_to["warnings"][0]
        )

        # Case C: error present
        m_err = _make_measurement_dict(cv=0.01, n_samples=5, n_timeouts=0, n_errors=1, timing_is_reliable=False)
        a_err = assess_measurement(m_err)
        ok_c = (
            a_err["status"] == "unreliable"
            and "1 errors" in a_err["warnings"][0]
        )

        # Case D: too few samples (4 samples)
        m_few = _make_measurement_dict(cv=0.0, n_samples=4, n_timeouts=0, n_errors=0, timing_is_reliable=False)
        a_few = assess_measurement(m_few)
        ok_d = (
            a_few["status"] == "unreliable"
            and "4 samples" in a_few["warnings"][0]
        )

        ok = ok_a and ok_b and ok_c and ok_d
        report(tid, name, ok, f"sample_warning={a_noisy['warnings'][0]!r}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q6_legacy_reports_handled():
    """Q6: Legacy/pre-Week-5 measurement dicts produce 'unknown', legacy_missing, None."""
    tid, name = "Q6", "legacy reports -> unknown, legacy_missing, None counts/CV"
    try:
        # Pre-Week-5 measurement payload: timing has median_s and n_samples,
        # but no cv, no n_timeouts, no n_errors, no timing_is_reliable key.
        legacy_m = {
            "strategy": "-O0",
            "exe_path": "/fake/legacy.exe",
            "warmup_runs": 3,
            "measure_runs": 10,
            "raw_samples_ns": [10_000_000] * 10,
            "timing": {
                "n_samples": 10,
                "median_ns": 10_000_000.0,
                "min_ns": 9_000_000.0,
                "max_ns": 11_000_000.0,
                "mean_ns": 10_000_000.0,
                "stdev_ns": 500_000.0,
                "median_s": 0.010,
                "mean_s": 0.010,
            },
            "last_return_code": 0,
            "last_stdout": "",
            "last_stderr": "",
            "all_return_codes": [0] * 10,
            "code_size": {"primary_value": 60000},
            "energy": {"energy_joules": 0.5},
            "carbon": {"carbon_grams": 0.00006},
            "measurement_error": None,
        }

        assessed = assess_measurement(legacy_m)

        status_unknown = assessed["status"] == "unknown"
        source_legacy = assessed["status_source"] == "legacy_missing"
        cv_none = assessed["cv"] is None
        to_none = assessed["n_timeouts"] is None
        err_none = assessed["n_errors"] is None
        rel_none = assessed["timing_is_reliable"] is None
        median_preserved = assessed["median_s"] == 0.010
        samples_preserved = assessed["n_samples"] == 10
        has_legacy_warn = any("legacy" in w.lower() for w in assessed["warnings"])

        ok = (
            status_unknown
            and source_legacy
            and cv_none
            and to_none
            and err_none
            and rel_none
            and median_preserved
            and samples_preserved
            and has_legacy_warn
        )
        report(tid, name, ok, f"status={assessed['status']} status_source={assessed['status_source']}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q7_malformed_dicts_never_raise():
    """Q7: Partial/malformed measurement dictionaries never raise."""
    tid, name = "Q7", "partial/malformed measurement dicts never raise"
    try:
        test_cases = [
            {},
            {"timing": "not_a_dict"},
            {"timing": {"median_s": "not_a_number", "n_samples": "ten"}},
            {"timing_is_reliable": "invalid_type", "n_timeouts": "three"},
            {"timing": None, "timing_is_reliable": None},
            12345,
            "string_payload",
            [1, 2, 3],
        ]

        all_ok = True
        for tc in test_cases:
            res = assess_measurement(tc)
            if not isinstance(res, dict) or res.get("status") != "unknown":
                all_ok = False
                break

        report(tid, name, all_ok, f"tested {len(test_cases)} malformed inputs safely")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q8_overall_status_precedence():
    """Q8: Verify overall status precedence: unreliable > unknown > reliable."""
    tid, name = "Q8", "precedence: unreliable > unknown > reliable"
    try:
        m_rel = _make_measurement_dict(timing_is_reliable=True)
        m_unrel = _make_measurement_dict(timing_is_reliable=False)
        m_unk = {"timing": {"median_s": 0.01, "n_samples": 5}}  # legacy -> unknown

        # 1. unreliable + reliable -> unreliable
        q1 = build_measurement_quality(m_rel, [{"strategy_name": "-O2", "measurement": m_unrel}])
        ok1 = q1["status"] == "unreliable"

        # 2. baseline unreliable + reliable candidate -> unreliable
        q2 = build_measurement_quality(m_unrel, [{"strategy_name": "-O2", "measurement": m_rel}])
        ok2 = q2["status"] == "unreliable"

        # 3. unknown + reliable -> unknown
        q3 = build_measurement_quality(m_rel, [{"strategy_name": "-O2", "measurement": m_unk}])
        ok3 = q3["status"] == "unknown"

        # 4. unreliable + unknown -> unreliable (unreliable beats unknown)
        q4 = build_measurement_quality(m_unrel, [{"strategy_name": "-O2", "measurement": m_unk}])
        ok4 = q4["status"] == "unreliable"

        # 5. baseline unknown + unreliable candidate -> unreliable
        q5 = build_measurement_quality(m_unk, [{"strategy_name": "-O2", "measurement": m_unrel}])
        ok5 = q5["status"] == "unreliable"

        # 6. all reliable -> reliable
        q6 = build_measurement_quality(m_rel, [{"strategy_name": "-O2", "measurement": m_rel}])
        ok6 = q6["status"] == "reliable"

        ok = ok1 and ok2 and ok3 and ok4 and ok5 and ok6
        report(tid, name, ok, f"q1={q1['status']} q3={q3['status']} q4={q4['status']} q6={q6['status']}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q9_none_and_empty_handled():
    """Q9: None measurement, missing baseline, and empty candidates handled safely."""
    tid, name = "Q9", "None measurement, missing baseline, empty candidates"
    try:
        # None measurement
        a_none = assess_measurement(None)
        ok_a = a_none["status"] == "unknown" and a_none["timing_is_reliable"] is None

        # Missing baseline and empty candidates
        q_empty = build_measurement_quality(None, [])
        ok_b = (
            q_empty["status"] == "unknown"
            and q_empty["candidates"] == []
            and q_empty["n_reliable"] == 0
            and q_empty["n_unreliable"] == 0
            and q_empty["n_unknown"] == 0
        )

        # Candidate with measurement=None is not assessed into candidates list
        # and does not count as reliable
        c_failed = CandidateResult(strategy_name="fail_strat", strategy_index=0, strategy_kind="clang_flag", measurement=None)
        q_failed = build_measurement_quality(None, [c_failed])
        ok_c = (
            len(q_failed["candidates"]) == 0
            and q_failed["n_reliable"] == 0
        )

        ok = ok_a and ok_b and ok_c
        report(tid, name, ok, f"a_none={a_none['status']} q_empty={q_empty['status']}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q10_pareto_unchanged_and_legacy_keys():
    """Q10: Pareto behavior completely unchanged; legacy keys preserved."""
    tid, name = "Q10", "Pareto unchanged & legacy JSON key preservation"
    try:
        from moo.pareto import dominates

        # Candidates with identical objective values
        # Run 1: with reliable metadata
        m_fast_rel = _make_measurement_dict(median_s=0.010, timing_is_reliable=True)
        m_small_rel = _make_measurement_dict(median_s=0.020, code_size_bytes=40000, timing_is_reliable=True)

        # Run 2: with unreliable metadata and timeouts
        m_fast_unrel = _make_measurement_dict(median_s=0.010, timing_is_reliable=False, n_timeouts=2)
        m_small_unrel = _make_measurement_dict(median_s=0.020, code_size_bytes=40000, timing_is_reliable=False, n_timeouts=2)

        # Build candidate results
        res1 = _make_eval_result(m_fast_rel, [("-O3", 0, m_fast_rel), ("-Oz", 1, m_small_rel)])
        res2 = _make_eval_result(m_fast_unrel, [("-O3", 0, m_fast_unrel), ("-Oz", 1, m_small_unrel)])

        d1 = res1.to_dict()
        d2 = res2.to_dict()

        # Both frontiers must match
        frontier_match = d1["pareto_frontier"] == d2["pareto_frontier"]

        # Legacy key set verification
        legacy_expected_keys = {
            "source_file",
            "source_path",
            "timestamp",
            "toolchain_ok",
            "toolchain_notes",
            "baseline",
            "candidates",
            "pareto_frontier",
            "pareto_dominated",
            "pareto_invalid",
            "objectives_used",
            "pipeline_error",
            "summary",
        }

        # Removing measurement_quality must leave the exact legacy keys
        keys_with_mq = set(d1.keys())
        has_new_key = "measurement_quality" in keys_with_mq
        keys_with_mq.remove("measurement_quality")
        legacy_keys_identical = (keys_with_mq == legacy_expected_keys)

        ok = frontier_match and has_new_key and legacy_keys_identical
        report(tid, name, ok, f"frontier_match={frontier_match} legacy_keys_ok={legacy_keys_identical}")
    except Exception as exc:
        report(tid, name, False, str(exc))


def q11_cli_summary_quality_display():
    """Q11: print_moo_summary displays warnings for unreliable/unknown, quiet for reliable."""
    tid, name = "Q11", "print_moo_summary quality warnings and quiet reliable"
    try:
        # Case 1: Reliable timing -> quiet, no warning text
        m_rel = _make_measurement_dict(timing_is_reliable=True)
        res_rel = _make_eval_result(m_rel, [("-O2", 0, m_rel)])
        buf_rel = io.StringIO()
        print_moo_summary(res_rel, file=buf_rel)
        out_rel = buf_rel.getvalue()

        quiet_when_reliable = (
            "Quality : UNRELIABLE" not in out_rel
            and "[QUALITY WARNING]" not in out_rel
            and "Quality : UNKNOWN" not in out_rel
        )

        # Case 2: Unreliable timing -> displays exact headline and detailed warning
        m_unrel = _make_measurement_dict(timing_is_reliable=False, cv=0.30)
        res_unrel = _make_eval_result(m_unrel, [("-O2", 0, m_unrel)])
        buf_unrel = io.StringIO()
        print_moo_summary(res_unrel, file=buf_unrel)
        out_unrel = buf_unrel.getvalue()

        warns_when_unreliable = (
            "Quality : UNRELIABLE (timing did not meet reliability criteria)" in out_unrel
            and "Timing: UNRELIABLE" in out_unrel
        )

        # Case 3: Unknown timing -> displays notice/warnings
        m_unk = {"timing": {"median_s": 0.01, "n_samples": 5}}  # legacy
        res_unk = _make_eval_result(m_unk, [("-O2", 0, m_unk)])
        buf_unk = io.StringIO()
        print_moo_summary(res_unk, file=buf_unk)
        out_unk = buf_unk.getvalue()

        notice_when_unknown = "Quality : UNKNOWN" in out_unk

        # Case 4: Baseline-only unreliable case
        # Baseline unreliable, but candidate is reliable
        res_base_only = _make_eval_result(m_unrel, [("-O2", 0, m_rel)])
        buf_base = io.StringIO()
        print_moo_summary(res_base_only, file=buf_base)
        out_base = buf_base.getvalue()

        base_only_ok = (
            "Quality : UNRELIABLE" in out_base
            and "0 candidate(s) flagged" not in out_base
        )

        # Case 5: Recorded-unknown candidate displays quality warning on candidate row
        m_recorded_unknown = _make_measurement_dict(
            timing_is_reliable=None,
            n_samples=0,
        )
        m_recorded_unknown["timing"] = None
        m_recorded_unknown["timing_is_reliable"] = None
        res_rec_unk = _make_eval_result(m_rel, [("-O2", 0, m_recorded_unknown)])
        buf_rec = io.StringIO()
        print_moo_summary(res_rec_unk, file=buf_rec)
        out_rec = buf_rec.getvalue()

        rec_unk_row_warn = "[QUALITY WARNING]" in out_rec

        # Legacy missing candidate should stay quiet at individual row level
        res_legacy_cand = _make_eval_result(m_rel, [("-O2", 0, m_unk)])
        buf_leg = io.StringIO()
        print_moo_summary(res_legacy_cand, file=buf_leg)
        out_leg = buf_leg.getvalue()
        legacy_row_quiet = "[QUALITY WARNING]" not in out_leg

        ok = (
            quiet_when_reliable
            and warns_when_unreliable
            and notice_when_unknown
            and base_only_ok
            and rec_unk_row_warn
            and legacy_row_quiet
        )
        report(
            tid,
            name,
            ok,
            f"quiet={quiet_when_reliable} warns={warns_when_unreliable} base_only={base_only_ok} rec_unk={rec_unk_row_warn}",
        )
    except Exception as exc:
        report(tid, name, False, str(exc))


def q12_selector_bridge_compatibility():
    """Q12: selector_bridge can still load a report containing measurement_quality."""
    tid, name = "Q12", "selector_bridge loads report with measurement_quality"
    try:
        m_rel = _make_measurement_dict(timing_is_reliable=True)
        res = _make_eval_result(m_rel, [("-O3", 0, m_rel)])
        d = res.to_dict()

        # Save to a temporary report directory
        with tempfile.TemporaryDirectory(prefix="toacd_stage5_q12_") as tmpdir:
            json_name = "moo_test_program_c_2026-10-01_17-00-00.json"
            json_path = os.path.join(tmpdir, json_name)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(d, f)

            # Test 1: _load_moo_report parses report with measurement_quality
            loaded = selector_bridge._load_moo_report(json_path)
            loaded_ok = loaded is not None and "measurement_quality" in loaded

            # Test 2: get_pareto_frontier_for loads frontier properly
            frontier = selector_bridge.get_pareto_frontier_for("test_program.c", report_dir=tmpdir)
            frontier_ok = frontier == ["-O3"]

        ok = loaded_ok and frontier_ok
        report(tid, name, ok, f"loaded_ok={loaded_ok} frontier={frontier}")
    except Exception as exc:
        report(tid, name, False, str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 65)
    print("TOACD MOO Stage 5 — Measurement Quality Observability Tests")
    print("=" * 65)

    q1_quality_block_appears()
    q2_cv_serialized_exactly()
    q3_timeout_and_error_counts()
    q4_reliable_timing_no_warnings()
    q5_unreliable_timing_readable_warnings()
    q6_legacy_reports_handled()
    q7_malformed_dicts_never_raise()
    q8_overall_status_precedence()
    q9_none_and_empty_handled()
    q10_pareto_unchanged_and_legacy_keys()
    q11_cli_summary_quality_display()
    q12_selector_bridge_compatibility()

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
