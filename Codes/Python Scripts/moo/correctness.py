"""
moo/correctness.py — Correctness comparison for compiled executables.

Given a reference executable and a candidate executable, runs both and
compares their behaviour.

Design principles
-----------------
* A non-zero exit code is NOT automatically incorrect.
  security_checks.c intentionally returns a non-zero exit code; correctness
  is defined as the candidate matching the reference, not as exit code == 0.
* Results always include separate flags for exit_code, stdout, and stderr
  matches so callers can apply their own policy.
* The structured CorrectnessResult is backward-compatible with the existing
  moo/models.py CorrectnessResult dataclass.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from . import config


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CorrectnessResult:
    """
    Outcome of comparing a candidate executable against a reference executable.

    Fields
    ------
    correct            : True if the candidate matches the reference on all
                         checked dimensions (exit code + stdout).  stderr
                         mismatch alone does NOT make correct=False, because
                         some compilers emit extra debug output on stderr.
                         Callers may override this policy using stderr_match.
    reference_exit_code: Exit code of the reference executable.
    candidate_exit_code: Exit code of the candidate executable.
    stdout_match       : True if stdout is byte-identical.
    stderr_match       : True if stderr is byte-identical.
    exit_code_match    : True if both exit codes are equal.
    details            : Human-readable summary of any differences.
    reference_stdout   : stdout captured from the reference run.
    candidate_stdout   : stdout captured from the candidate run.
    reference_stderr   : stderr captured from the reference run.
    candidate_stderr   : stderr captured from the candidate run.
    reference_error    : subprocess-level error for the reference run (None=ok).
    candidate_error    : subprocess-level error for the candidate run (None=ok).
    checked            : False if comparison could not be performed
                         (e.g. executable missing, launch error).
    """
    correct: bool
    reference_exit_code: Optional[int]
    candidate_exit_code: Optional[int]
    stdout_match: bool
    stderr_match: bool
    exit_code_match: bool
    details: str
    reference_stdout: str = ""
    candidate_stdout: str = ""
    reference_stderr: str = ""
    candidate_stderr: str = ""
    reference_error: Optional[str] = None
    candidate_error: Optional[str] = None
    checked: bool = True

    def to_dict(self) -> dict:
        return {
            "correct": self.correct,
            "reference_exit_code": self.reference_exit_code,
            "candidate_exit_code": self.candidate_exit_code,
            "stdout_match": self.stdout_match,
            "stderr_match": self.stderr_match,
            "exit_code_match": self.exit_code_match,
            "details": self.details,
            "reference_stdout": self.reference_stdout,
            "candidate_stdout": self.candidate_stdout,
            "reference_stderr": self.reference_stderr,
            "candidate_stderr": self.candidate_stderr,
            "reference_error": self.reference_error,
            "candidate_error": self.candidate_error,
            "checked": self.checked,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_for_output(
    exe_path: str,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
) -> tuple[Optional[int], str, str, Optional[str]]:
    """
    Run *exe_path* once and return (return_code, stdout, stderr, error).

    error is None on success, or a string describing a subprocess-level
    failure (not a non-zero exit code — those are returned faithfully).
    """
    cmd = [exe_path] + (args or [])
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return r.returncode, r.stdout, r.stderr, None
    except subprocess.TimeoutExpired as exc:
        return None, exc.stdout or "", exc.stderr or "", f"TimeoutExpired after {timeout_s}s"
    except Exception as exc:
        return None, "", "", str(exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_executables(
    reference_exe: str,
    candidate_exe: str,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
    check_stderr: bool = False,
) -> CorrectnessResult:
    """
    Run *reference_exe* and *candidate_exe*, compare their behaviour.

    Parameters
    ----------
    reference_exe : path to the reference (baseline) executable
    candidate_exe : path to the candidate (optimized) executable
    timeout_s     : per-run wall-clock timeout in seconds
    args          : extra arguments passed to both executables
    check_stderr  : if True, stderr mismatch contributes to correct=False.
                    Defaults to False because compilers often add extra
                    diagnostic output to stderr that is not semantically
                    meaningful.

    Correctness policy
    ------------------
    * Exit code mismatch → correct = False (regardless of stdout).
    * stdout mismatch    → correct = False.
    * stderr mismatch    → correct = False ONLY if check_stderr=True.
    * A non-zero reference exit code is fine — the candidate must match it.
      (security_checks.c intentionally returns non-zero.)

    Returns
    -------
    CorrectnessResult — always structured; correct=False with an explanation
    when something cannot be compared.
    """
    import os

    # Guard: executables must exist
    if not os.path.isfile(reference_exe):
        return CorrectnessResult(
            correct=False,
            reference_exit_code=None,
            candidate_exit_code=None,
            stdout_match=False,
            stderr_match=False,
            exit_code_match=False,
            details=f"Reference executable not found: {reference_exe}",
            reference_error=f"File not found: {reference_exe}",
            checked=False,
        )
    if not os.path.isfile(candidate_exe):
        return CorrectnessResult(
            correct=False,
            reference_exit_code=None,
            candidate_exit_code=None,
            stdout_match=False,
            stderr_match=False,
            exit_code_match=False,
            details=f"Candidate executable not found: {candidate_exe}",
            candidate_error=f"File not found: {candidate_exe}",
            checked=False,
        )

    # Run reference
    ref_rc, ref_out, ref_err, ref_error = _run_for_output(
        reference_exe, timeout_s=timeout_s, args=args
    )
    # Run candidate
    cand_rc, cand_out, cand_err, cand_error = _run_for_output(
        candidate_exe, timeout_s=timeout_s, args=args
    )

    # If either run failed at the subprocess level, we cannot compare
    if ref_error is not None:
        return CorrectnessResult(
            correct=False,
            reference_exit_code=ref_rc,
            candidate_exit_code=cand_rc,
            stdout_match=False,
            stderr_match=False,
            exit_code_match=False,
            details=f"Reference run error: {ref_error}",
            reference_stdout=ref_out,
            candidate_stdout=cand_out,
            reference_stderr=ref_err,
            candidate_stderr=cand_err,
            reference_error=ref_error,
            candidate_error=cand_error,
            checked=False,
        )
    if cand_error is not None:
        return CorrectnessResult(
            correct=False,
            reference_exit_code=ref_rc,
            candidate_exit_code=cand_rc,
            stdout_match=False,
            stderr_match=False,
            exit_code_match=False,
            details=f"Candidate run error: {cand_error}",
            reference_stdout=ref_out,
            candidate_stdout=cand_out,
            reference_stderr=ref_err,
            candidate_stderr=cand_err,
            reference_error=ref_error,
            candidate_error=cand_error,
            checked=False,
        )

    # Compare
    exit_code_match = (ref_rc == cand_rc)
    stdout_match = (ref_out == cand_out)
    stderr_match = (ref_err == cand_err)

    # Build difference detail string
    diff_parts: list[str] = []
    if not exit_code_match:
        diff_parts.append(
            f"exit code mismatch: reference={ref_rc}, candidate={cand_rc}"
        )
    if not stdout_match:
        ref_preview = ref_out[:200].replace("\n", "\\n")
        cand_preview = cand_out[:200].replace("\n", "\\n")
        diff_parts.append(
            f"stdout mismatch (ref={ref_preview!r}, cand={cand_preview!r})"
        )
    if not stderr_match:
        diff_parts.append("stderr mismatch (not counted toward correct unless check_stderr=True)")

    # Correctness verdict
    correct = exit_code_match and stdout_match
    if check_stderr:
        correct = correct and stderr_match

    if correct:
        ref_rc_note = (
            f" (reference exit code {ref_rc} is non-zero but intentional)"
            if ref_rc != 0
            else ""
        )
        details = f"CORRECT: all checked outputs match{ref_rc_note}"
    else:
        details = "INCORRECT: " + "; ".join(diff_parts) if diff_parts else "INCORRECT"

    return CorrectnessResult(
        correct=correct,
        reference_exit_code=ref_rc,
        candidate_exit_code=cand_rc,
        stdout_match=stdout_match,
        stderr_match=stderr_match,
        exit_code_match=exit_code_match,
        details=details,
        reference_stdout=ref_out,
        candidate_stdout=cand_out,
        reference_stderr=ref_err,
        candidate_stderr=cand_err,
        reference_error=None,
        candidate_error=None,
        checked=True,
    )


def check_self_consistent(
    exe_path: str,
    n_runs: int = 2,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
) -> CorrectnessResult:
    """
    Verify that *exe_path* produces identical output across multiple runs.

    This is useful for detecting non-deterministic programs before using
    them as references.  Runs the executable *n_runs* times and compares
    each run to the first.

    Returns a CorrectnessResult where correct=True means all runs matched.
    """
    if n_runs < 2:
        raise ValueError("n_runs must be >= 2 for self-consistency check")

    runs: list[tuple] = []
    for _ in range(n_runs):
        rc, out, err, error = _run_for_output(exe_path, timeout_s=timeout_s, args=args)
        if error:
            return CorrectnessResult(
                correct=False,
                reference_exit_code=None,
                candidate_exit_code=None,
                stdout_match=False,
                stderr_match=False,
                exit_code_match=False,
                details=f"Run error during self-consistency check: {error}",
                checked=False,
            )
        runs.append((rc, out, err))

    ref_rc, ref_out, ref_err = runs[0]
    mismatches: list[str] = []
    for i, (rc, out, err) in enumerate(runs[1:], start=2):
        if rc != ref_rc:
            mismatches.append(f"run {i}: exit code {rc} != {ref_rc}")
        if out != ref_out:
            mismatches.append(f"run {i}: stdout differs")

    correct = len(mismatches) == 0
    details = (
        "Self-consistent across all runs"
        if correct
        else "Non-deterministic: " + "; ".join(mismatches)
    )
    last_rc, last_out, last_err = runs[-1]
    return CorrectnessResult(
        correct=correct,
        reference_exit_code=ref_rc,
        candidate_exit_code=last_rc,
        stdout_match=(ref_out == last_out),
        stderr_match=(ref_err == last_err),
        exit_code_match=(ref_rc == last_rc),
        details=details,
        reference_stdout=ref_out,
        candidate_stdout=last_out,
        reference_stderr=ref_err,
        candidate_stderr=last_err,
        checked=True,
    )
