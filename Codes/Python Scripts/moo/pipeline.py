"""
moo/pipeline.py — Stage 3 MOO evaluation pipeline.

Given a C source file, this module:
  1.  Compiles a reference (baseline, -O0) executable and measures it.
  2.  For each of the 9 existing optimization strategies:
        a. Generates optimized IR/code using the EXISTING mechanism from
           strategy_diagnostic.py (clang -Ox or clang+opt pass pipeline).
        b. Compiles the optimized IR to an executable.
        c. Checks correctness against the reference behavior (exit code +
           stdout).  Non-zero exit codes are NOT automatically incorrect.
        d. If correct, measures: execution time, energy, code size, carbon.
  3.  Normalizes every valid candidate's measurements against the baseline
      using Stage 2 baseline-relative normalization.
  4.  Extracts the Pareto frontier from valid candidates.
  5.  Returns a structured MOOEvaluationResult.

Design constraints
------------------
* Uses ONLY the existing strategy_diagnostic mechanisms — no new IR
  generation or compilation logic.
* Uses ONLY measurement.py, objectives.py, pareto.py — no new timing or
  size logic.
* Does NOT modify any existing project files.
* Isolates every strategy in its own unique temporary directory.
* Cleans up temporary artifacts after each run.
* Records failures explicitly; does NOT silently convert them to zeros.
* Does NOT select or label a single "best" strategy.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional

from .config import (
    ACTIONS,
    CLANG_PATH,
    OPT_PATH,
    WARMUP_RUNS,
    MEASURE_RUNS,
    RUN_TIMEOUT_S,
)
from .measurement import measure_all, MeasurementResult
from .objectives import (
    ALL_OBJECTIVES,
    RawObjectives,
    normalize,
    NormalizedObjectiveVector,
)
from .pareto import extract_pareto_frontier, pareto_from_raw
from .moo_result import (
    BaselineMeasurement,
    CandidateResult,
    MOOEvaluationResult,
)
from .toolchain import verify_toolchain

# Re-use the IR/build/run helpers from the existing diagnostic engine.
# These are already verified to work correctly.
from .strategy_diagnostic import (
    _run,
    _cmd_str,
    _generate_baseline,
    _run_clang_flag_strategy,
    _run_opt_passes_strategy,
    _build_executable,
    _classify_action,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_from_measurement(strategy: str, mres: MeasurementResult) -> Optional[RawObjectives]:
    """
    Extract a RawObjectives from a MeasurementResult.
    Returns None if the measurement has no valid timing data.
    """
    if mres.timing is None:
        return None
    return RawObjectives.from_measurement_result(strategy, mres)


def _build_and_run_reference(
    source_path: str,
    workdir: str,
    clang_path: str,
    warmup_runs: int,
    measure_runs: int,
    timeout_s: int,
) -> tuple[Optional[str], Optional[int], str, str, Optional[str]]:
    """
    Compile a reference (-O0) executable and do ONE reference run to capture
    exit code + stdout for correctness comparison.

    Returns (exe_path, ref_exit_code, ref_stdout, ref_stderr, error_str).
    error_str is None on success.
    """
    exe_path = os.path.join(workdir, "ref.exe")
    cmd = [clang_path, "-O0", source_path, "-o", exe_path]
    res = _run(cmd, timeout=60)

    if res.returncode != 0 or not os.path.isfile(exe_path):
        return None, None, "", "", (
            f"Reference build failed (rc={res.returncode}): {res.stderr.strip()[:400]}"
        )

    # Run once to capture reference behavior
    try:
        run_res = subprocess.run(
            [exe_path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return exe_path, run_res.returncode, run_res.stdout, run_res.stderr, None
    except subprocess.TimeoutExpired:
        return exe_path, None, "", "", f"Reference run timed out after {timeout_s}s"
    except Exception as exc:
        return exe_path, None, "", "", str(exc)


def _check_correctness_simple(
    candidate_exe: str,
    ref_exit_code: Optional[int],
    ref_stdout: str,
    timeout_s: int,
) -> tuple[bool, int | None, str, str]:
    """
    Run candidate_exe once and compare to reference behavior.

    A non-zero ref_exit_code is acceptable — correctness is defined as
    the candidate matching the reference, not as exit code == 0.

    Returns (correct, candidate_rc, details, candidate_stdout).
    """
    try:
        res = subprocess.run(
            [candidate_exe],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"Timed out after {timeout_s}s", ""
    except Exception as exc:
        return False, None, str(exc), ""

    rc_match = (res.returncode == ref_exit_code)
    stdout_match = (res.stdout == ref_stdout)
    correct = rc_match and stdout_match

    if correct:
        note = "CORRECT"
        if ref_exit_code != 0:
            note += f" (reference exit code {ref_exit_code} is non-zero but intentional)"
    else:
        parts = []
        if not rc_match:
            parts.append(f"exit code: expected {ref_exit_code}, got {res.returncode}")
        if not stdout_match:
            parts.append("stdout differs from reference")
        note = "INCORRECT: " + "; ".join(parts)

    return correct, res.returncode, note, res.stdout


# ---------------------------------------------------------------------------
# Per-strategy evaluator
# ---------------------------------------------------------------------------

def _evaluate_strategy(
    idx: int,
    action: str,
    source_path: str,
    tmproot: str,
    clang_path: str,
    opt_path: Optional[str],
    ref_exit_code: Optional[int],
    ref_stdout: str,
    warmup_runs: int,
    measure_runs: int,
    timeout_s: int,
) -> CandidateResult:
    """
    Evaluate one optimization strategy:
      1. Generate optimized IR using the EXISTING mechanism.
      2. Build executable.
      3. Check correctness.
      4. Measure (if correct).

    Returns a CandidateResult.  Never raises — failures are recorded.
    """
    kind = _classify_action(action)
    strat_dir = os.path.join(tmproot, f"s{idx:02d}_{kind}")
    os.makedirs(strat_dir, exist_ok=True)

    candidate = CandidateResult(
        strategy_name=action,
        strategy_index=idx,
        strategy_kind=kind,
    )

    # ----------------------------------------------------------------
    # Step 1: Generate optimized IR using existing mechanism
    # ----------------------------------------------------------------
    ir_path: Optional[str] = None

    if kind == "clang_flag":
        ir_path, ir_res, ir_cmd = _run_clang_flag_strategy(
            action, source_path, strat_dir, clang_path
        )
        if ir_path is None:
            candidate.build_ok = False
            candidate.build_error = (
                f"IR generation failed (rc={ir_res.returncode}): "
                f"{ir_res.stderr.strip()[:400]}"
            )
            return candidate

    else:  # opt_passes
        if not opt_path:
            candidate.build_ok = False
            candidate.build_error = (
                "opt not found; cannot run custom-pass strategy. "
                "Set TOACD_OPT_PATH to the opt.exe path."
            )
            return candidate

        ir_path, results, cmds = _run_opt_passes_strategy(
            action, source_path, strat_dir, clang_path, opt_path
        )
        if ir_path is None:
            # Find the first failing step
            for i, r in enumerate(results):
                if r.returncode != 0:
                    step = "IR generation" if i == 0 else "opt pass"
                    candidate.build_error = (
                        f"Step {i+1} ({step}) failed (rc={r.returncode}): "
                        f"{r.stderr.strip()[:400]}"
                    )
                    break
            else:
                candidate.build_error = "IR not produced (unknown reason)"
            candidate.build_ok = False
            return candidate

    # ----------------------------------------------------------------
    # Step 2: Build executable from optimized IR
    # ----------------------------------------------------------------
    exe_path, exe_res, exe_cmd = _build_executable(ir_path, strat_dir, clang_path)

    if exe_path is None:
        candidate.build_ok = False
        candidate.build_error = (
            f"Executable build failed (rc={exe_res.returncode}): "
            f"{exe_res.stderr.strip()[:400]}"
        )
        return candidate

    candidate.build_ok = True
    candidate.exe_path = exe_path

    # ----------------------------------------------------------------
    # Step 3: Correctness check
    # ----------------------------------------------------------------
    correct, cand_rc, details, _ = _check_correctness_simple(
        exe_path, ref_exit_code, ref_stdout, timeout_s
    )
    candidate.correctness_checked = True
    candidate.correct = correct
    candidate.correctness_details = details
    candidate.reference_exit_code = ref_exit_code
    candidate.candidate_exit_code = cand_rc

    if not correct:
        # Do NOT measure incorrect candidates
        return candidate

    # ----------------------------------------------------------------
    # Step 4: Measure (execution time + code size + energy + carbon)
    # ----------------------------------------------------------------
    mres = measure_all(
        exe_path=exe_path,
        strategy=action,
        warmup_runs=warmup_runs,
        measure_runs=measure_runs,
        timeout_s=timeout_s,
    )
    candidate.measurement = mres.to_dict()

    return candidate


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def evaluate_program(
    source_path: str,
    source_name: Optional[str] = None,
    warmup_runs: int = WARMUP_RUNS,
    measure_runs: int = MEASURE_RUNS,
    timeout_s: int = RUN_TIMEOUT_S,
    actions: Optional[list[str]] = None,
    keep_temps: bool = False,
) -> MOOEvaluationResult:
    """
    Run the complete Stage 3 MOO evaluation for one C source file.

    Parameters
    ----------
    source_path  : absolute path to the C source file
    source_name  : display name (defaults to basename of source_path)
    warmup_runs  : warmup executions before timing (from config default)
    measure_runs : number of timed executions per candidate
    timeout_s    : per-run wall-clock timeout in seconds
    actions      : override the strategy list (defaults to config.ACTIONS)
    keep_temps   : if True, temporary build directories are NOT cleaned up
                   (useful for debugging)

    Returns
    -------
    MOOEvaluationResult — fully structured, JSON-serializable.
    """
    if source_name is None:
        source_name = os.path.basename(source_path) if source_path else "<unknown>"

    if actions is None:
        actions = ACTIONS

    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    result = MOOEvaluationResult(
        source_file=source_name,
        source_path=source_path,
        timestamp=timestamp,
    )

    # ----------------------------------------------------------------
    # Validate inputs
    # ----------------------------------------------------------------
    if not source_path or not os.path.isfile(source_path):
        result.pipeline_error = f"Source file not found: {source_path!r}"
        return result

    clang_path = CLANG_PATH
    opt_path = OPT_PATH

    if not clang_path:
        result.pipeline_error = "clang not found; cannot run pipeline."
        return result

    result.toolchain_ok = True

    # Record toolchain notes (version mismatches etc.)
    try:
        _, _, incompat = verify_toolchain()
        result.toolchain_notes = [f"[{i.kind}] {i.detail}" for i in incompat]
    except Exception as exc:
        result.toolchain_notes = [f"toolchain probe error: {exc}"]

    # ----------------------------------------------------------------
    # Top-level temporary workspace (unique per call)
    # ----------------------------------------------------------------
    safe_name = source_name.replace(".", "_").replace(" ", "_")
    tmproot = tempfile.mkdtemp(prefix=f"toacd_moo_{safe_name}_")

    try:
        # ------------------------------------------------------------
        # 1. Build reference executable + capture reference behavior
        # ------------------------------------------------------------
        ref_dir = os.path.join(tmproot, "reference")
        os.makedirs(ref_dir, exist_ok=True)

        ref_exe, ref_rc, ref_stdout, ref_stderr, ref_err = _build_and_run_reference(
            source_path, ref_dir, clang_path,
            warmup_runs, measure_runs, timeout_s,
        )

        if ref_err:
            result.pipeline_error = f"Reference build/run failed: {ref_err}"
            return result

        # ------------------------------------------------------------
        # 2. Measure baseline
        # ------------------------------------------------------------
        if ref_exe and os.path.isfile(ref_exe):
            base_mres = measure_all(
                exe_path=ref_exe,
                strategy="baseline (-O0)",
                warmup_runs=warmup_runs,
                measure_runs=measure_runs,
                timeout_s=timeout_s,
            )
            result.baseline = BaselineMeasurement(
                strategy_name="baseline (-O0)",
                exe_path=ref_exe,
                build_ok=True,
                build_error=None,
                reference_exit_code=ref_rc,
                reference_stdout=ref_stdout,
                measurement=base_mres.to_dict(),
            )
            base_raw = _raw_from_measurement("baseline (-O0)", base_mres)
        else:
            result.baseline = BaselineMeasurement(
                strategy_name="baseline (-O0)",
                exe_path=None,
                build_ok=False,
                build_error=ref_err,
                reference_exit_code=ref_rc,
                reference_stdout=ref_stdout,
                measurement=None,
            )
            base_raw = None

        # ------------------------------------------------------------
        # 3. Evaluate each strategy
        # ------------------------------------------------------------
        candidates: list[CandidateResult] = []

        for idx, action in enumerate(actions):
            try:
                cand = _evaluate_strategy(
                    idx=idx,
                    action=action,
                    source_path=source_path,
                    tmproot=tmproot,
                    clang_path=clang_path,
                    opt_path=opt_path,
                    ref_exit_code=ref_rc,
                    ref_stdout=ref_stdout,
                    warmup_runs=warmup_runs,
                    measure_runs=measure_runs,
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                # Any unhandled exception in a single strategy is isolated
                cand = CandidateResult(
                    strategy_name=action,
                    strategy_index=idx,
                    strategy_kind=_classify_action(action),
                    build_ok=False,
                    build_error=f"Unhandled pipeline error: {exc}",
                )
            candidates.append(cand)

        result.candidates = candidates

        # ------------------------------------------------------------
        # 4. Normalize valid candidates against baseline
        # ------------------------------------------------------------
        if base_raw is None:
            # Cannot normalize without a valid baseline measurement
            result.pipeline_error = (
                (result.pipeline_error or "") +
                "; Cannot normalize: baseline measurement unavailable."
            ).lstrip("; ")
            # Still classify all as INVALID
            for c in candidates:
                c.pareto_status = "INVALID"
            result.pareto_invalid = [c.strategy_name for c in candidates]
            return result

        valid_candidates: list[CandidateResult] = []
        invalid_candidates: list[CandidateResult] = []
        valid_vectors: list[NormalizedObjectiveVector] = []

        for cand in candidates:
            if not cand.is_valid():
                cand.pareto_status = "INVALID"
                invalid_candidates.append(cand)
                continue

            # Build RawObjectives from the stored measurement dict
            # (re-parse from dict to avoid storing MeasurementResult objects)
            m = cand.measurement
            timing = m.get("timing") or {}
            code_size = m.get("code_size") or {}
            energy = m.get("energy") or {}
            carbon = m.get("carbon") or {}

            cand_raw = RawObjectives(
                strategy=cand.strategy_name,
                execution_time_s=timing.get("median_s"),
                energy_j=energy.get("energy_joules"),
                code_size_bytes=code_size.get("primary_value"),
                carbon_g=carbon.get("carbon_grams"),
            )

            vec = normalize(cand_raw, base_raw, objectives=ALL_OBJECTIVES)
            cand.normalized = vec.to_dict()
            valid_candidates.append(cand)
            valid_vectors.append(vec)

        # ------------------------------------------------------------
        # 5. Extract Pareto frontier from valid candidates
        # ------------------------------------------------------------
        objectives_used = [o.name for o in ALL_OBJECTIVES]

        if valid_vectors:
            pareto_res = extract_pareto_frontier(valid_vectors)

            frontier_set = set(pareto_res.frontier)
            dominated_set = set(pareto_res.dominated)

            for cand in valid_candidates:
                if cand.strategy_name in frontier_set:
                    cand.pareto_status = "FRONTIER"
                elif cand.strategy_name in dominated_set:
                    cand.pareto_status = "DOMINATED"
                    # Find which strategies dominate this one
                    for entry in pareto_res.all_candidates:
                        if entry.strategy == cand.strategy_name:
                            cand.dominated_by = list(entry.dominated_by)
                            break

            result.pareto_frontier = list(pareto_res.frontier)
            result.pareto_dominated = list(pareto_res.dominated)
        else:
            result.pareto_frontier = []
            result.pareto_dominated = []

        result.pareto_invalid = [c.strategy_name for c in invalid_candidates]
        result.objectives_used = objectives_used

    finally:
        if not keep_temps:
            try:
                shutil.rmtree(tmproot, ignore_errors=True)
            except Exception:
                pass

    return result
