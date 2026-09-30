"""
moo/strategy_diagnostic.py — Core diagnostic engine.

For each source file and each of the 9 existing optimization strategies:
  1.  Generates a clean baseline (unoptimized) LLVM IR.
  2.  Runs all 9 strategies in isolated temporary directories.
  3.  Captures exact commands, return codes, stdout, stderr, IR hashes.
  4.  Compiles each successful IR to an executable and runs it.
  5.  Compares output against the reference run for correctness.
  6.  Records IR hash deduplication (strategies producing identical IR).
  7.  Saves a JSON report.
  8.  Prints a readable terminal table.

This module does NOT modify any existing project files.
Uses the VERIFIED opt.exe mechanism:
    opt.exe -passes=<pipeline> input.ll -S -o output.ll
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Optional

from .config import ACTIONS, CLANG_PATH, OPT_PATH, REPORT_DIR, TEST_FILES
from .models import (
    BaselineInfo,
    CorrectnessResult,
    FileReport,
    StrategyResult,
    ToolInfo,
)
from .toolchain import verify_toolchain


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _sha256(path: str) -> str:
    """Return the SHA-256 hex digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _cmd_str(cmd: list[str]) -> str:
    """Return a shell-quoted string representation of a command list."""
    return " ".join(shlex.quote(str(c)) for c in cmd)


def _run(cmd: list[str], cwd: str = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run *cmd* and return the CompletedProcess.  Never raises on non-zero exit."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Baseline generation
# ---------------------------------------------------------------------------

def _generate_baseline(
    source_path: str,
    workdir: str,
    clang_path: str,
) -> BaselineInfo:
    """
    Compile *source_path* to unoptimized LLVM IR with -O0 -disable-O0-optnone
    (the same mechanism used by the existing optimization_selector.py).
    Also compile the IR to an executable and do a reference run.

    Returns a BaselineInfo.
    """
    ir_path = os.path.join(workdir, "baseline.ll")
    exe_path = os.path.join(workdir, "baseline.exe")

    # Step 1: generate IR
    ir_cmd = [
        clang_path,
        "-O0",
        "-Xclang", "-disable-O0-optnone",
        "-S", "-emit-llvm",
        source_path,
        "-o", ir_path,
    ]
    ir_res = _run(ir_cmd)

    info = BaselineInfo(
        ir_path=ir_path if ir_res.returncode == 0 and os.path.isfile(ir_path) else None,
        ir_hash=None,
        ir_command=_cmd_str(ir_cmd),
        ir_returncode=ir_res.returncode,
        ir_stdout=ir_res.stdout,
        ir_stderr=ir_res.stderr,
        ir_ok=ir_res.returncode == 0 and os.path.isfile(ir_path),
    )

    if info.ir_ok:
        info.ir_hash = _sha256(ir_path)

        # Step 2: compile IR → executable
        exe_cmd = [clang_path, ir_path, "-o", exe_path]
        exe_res = _run(exe_cmd)
        info.exe_path = exe_path if exe_res.returncode == 0 and os.path.isfile(exe_path) else None
        info.exe_command = _cmd_str(exe_cmd)
        info.exe_returncode = exe_res.returncode
        info.exe_stdout = exe_res.stdout
        info.exe_stderr = exe_res.stderr
        info.exe_ok = exe_res.returncode == 0 and os.path.isfile(exe_path)

        if info.exe_ok:
            # Step 3: reference run
            try:
                run_res = _run([exe_path], timeout=30)
                info.run_returncode = run_res.returncode
                info.run_stdout = run_res.stdout
                info.run_stderr = run_res.stderr
                info.run_ok = True
            except subprocess.TimeoutExpired:
                info.run_returncode = None
                info.run_stdout = ""
                info.run_stderr = "<timeout after 30s>"
                info.run_ok = False

    return info


# ---------------------------------------------------------------------------
# Strategy execution
# ---------------------------------------------------------------------------

def _classify_action(action: str) -> str:
    """Return 'clang_flag' for -Ox actions, 'opt_passes' for custom pipelines."""
    return "clang_flag" if action.startswith("-O") else "opt_passes"


def _run_clang_flag_strategy(
    action: str,
    source_path: str,
    workdir: str,
    clang_path: str,
) -> tuple[Optional[str], subprocess.CompletedProcess, list[str]]:
    """
    Apply a -O0/-O1/-O2/-O3 strategy by compiling directly with clang.
    Returns (ir_path_or_None, completed_process).
    """
    ir_path = os.path.join(workdir, "optimized.ll")
    cmd = [
        clang_path,
        action,
        "-S", "-emit-llvm",
        source_path,
        "-o", ir_path,
    ]
    res = _run(cmd)
    actual_path = ir_path if res.returncode == 0 and os.path.isfile(ir_path) else None
    return actual_path, res, cmd


def _run_opt_passes_strategy(
    action: str,
    source_path: str,
    workdir: str,
    clang_path: str,
    opt_path: str,
) -> tuple[Optional[str], list[subprocess.CompletedProcess], list[list[str]]]:
    """
    Apply a custom LLVM pass pipeline strategy using the VERIFIED mechanism:
        1. clang -O0 -Xclang -disable-O0-optnone -S -emit-llvm → unopt.ll
        2. opt -passes=<pipeline> unopt.ll -S -o optimized.ll

    Returns (ir_path_or_None, [res1, res2], [cmd1, cmd2]).
    """
    unopt_path = os.path.join(workdir, "unopt.ll")
    opt_ir_path = os.path.join(workdir, "optimized.ll")

    # Step 1: generate unoptimized IR (same as optimization_selector.py)
    cmd1 = [
        clang_path,
        "-O0",
        "-Xclang", "-disable-O0-optnone",
        "-S", "-emit-llvm",
        source_path,
        "-o", unopt_path,
    ]
    res1 = _run(cmd1)
    results = [res1]
    cmds = [cmd1]

    if res1.returncode != 0 or not os.path.isfile(unopt_path):
        return None, results, cmds

    # Step 2: run opt with the pass pipeline (VERIFIED mechanism)
    cmd2 = [
        opt_path,
        f"-passes={action}",
        unopt_path,
        "-S",
        "-o", opt_ir_path,
    ]
    res2 = _run(cmd2)
    results.append(res2)
    cmds.append(cmd2)

    actual_path = opt_ir_path if res2.returncode == 0 and os.path.isfile(opt_ir_path) else None
    return actual_path, results, cmds


def _build_executable(
    ir_path: str,
    workdir: str,
    clang_path: str,
) -> tuple[Optional[str], subprocess.CompletedProcess, list[str]]:
    """Compile *ir_path* to an executable.  Returns (exe_path_or_None, result, cmd)."""
    exe_path = os.path.join(workdir, "optimized.exe")
    cmd = [clang_path, ir_path, "-o", exe_path]
    res = _run(cmd)
    actual = exe_path if res.returncode == 0 and os.path.isfile(exe_path) else None
    return actual, res, cmd


def _check_correctness(
    exe_path: str,
    baseline: BaselineInfo,
) -> CorrectnessResult:
    """
    Run *exe_path* and compare its output to the reference baseline run.
    A non-zero exit code is NOT automatically a failure — correctness is
    based on matching the reference behaviour.
    """
    if not baseline.run_ok:
        return CorrectnessResult(
            checked=False,
            correct=False,
            ref_exit_code=baseline.run_returncode,
            opt_exit_code=None,
            note="Reference run was not successful; cannot compare.",
        )

    try:
        run_res = _run([exe_path], timeout=30)
    except subprocess.TimeoutExpired:
        return CorrectnessResult(
            checked=True,
            correct=False,
            ref_exit_code=baseline.run_returncode,
            opt_exit_code=None,
            note="Optimized executable timed out after 30 s.",
        )

    stdout_match = run_res.stdout == baseline.run_stdout
    stderr_match = run_res.stderr == baseline.run_stderr
    exit_match = run_res.returncode == baseline.run_returncode

    correct = stdout_match and exit_match  # stderr match is informational only

    note = ""
    if not correct:
        parts = []
        if not exit_match:
            parts.append(
                f"exit code mismatch: expected {baseline.run_returncode}, "
                f"got {run_res.returncode}"
            )
        if not stdout_match:
            parts.append("stdout differs from reference")
        note = "; ".join(parts)

    return CorrectnessResult(
        checked=True,
        correct=correct,
        ref_exit_code=baseline.run_returncode,
        opt_exit_code=run_res.returncode,
        ref_stdout=baseline.run_stdout,
        opt_stdout=run_res.stdout,
        ref_stderr=baseline.run_stderr,
        opt_stderr=run_res.stderr,
        stdout_match=stdout_match,
        stderr_match=stderr_match,
        exit_code_match=exit_match,
        note=note,
    )


# ---------------------------------------------------------------------------
# Per-file diagnostic orchestrator
# ---------------------------------------------------------------------------

def diagnose_file(
    source_name: str,
    source_path: str,
    clang_info: ToolInfo,
    opt_info: ToolInfo,
    incompatibilities: list,
    timestamp: str,
) -> FileReport:
    """
    Run the full diagnostic on a single source file.
    Returns a populated FileReport.
    """
    report = FileReport(
        source_file=source_name,
        source_path=source_path,
        timestamp=timestamp,
        clang_info=clang_info,
        opt_info=opt_info,
        incompatibilities=incompatibilities,
    )

    if not source_path or not os.path.isfile(source_path):
        # Cannot proceed without a source file
        _sr = StrategyResult(
            strategy_index=-1,
            strategy_name="(all)",
            strategy_kind="N/A",
            status="ERROR",
            failure_reason=f"Source file not found: {source_name!r}",
        )
        report.strategy_results.append(_sr)
        return report

    clang_path = clang_info.path
    opt_path = opt_info.path

    if not clang_path:
        _sr = StrategyResult(
            strategy_index=-1,
            strategy_name="(all)",
            strategy_kind="N/A",
            status="ERROR",
            failure_reason="clang not found; cannot run any strategy.",
        )
        report.strategy_results.append(_sr)
        return report

    # -----------------------------------------------------------------------
    # Create a top-level temporary workspace for this file
    # -----------------------------------------------------------------------
    tmproot = tempfile.mkdtemp(prefix=f"toacd_diag_{source_name.replace('.', '_')}_")

    try:
        # -------------------------------------------------------------------
        # Baseline
        # -------------------------------------------------------------------
        baseline_dir = os.path.join(tmproot, "baseline")
        os.makedirs(baseline_dir, exist_ok=True)
        baseline = _generate_baseline(source_path, baseline_dir, clang_path)
        report.baseline = baseline

        # -------------------------------------------------------------------
        # Strategy results
        # -------------------------------------------------------------------
        # Track IR hashes to detect duplicates
        seen_hashes: dict[str, int] = {}  # hash → strategy_index
        if baseline.ir_hash:
            seen_hashes[baseline.ir_hash] = -1  # -1 = baseline

        strategy_results: list[StrategyResult] = []

        for idx, action in enumerate(ACTIONS):
            kind = _classify_action(action)

            # Each strategy gets its own isolated directory
            strat_dir = os.path.join(tmproot, f"strategy_{idx:02d}_{kind}")
            os.makedirs(strat_dir, exist_ok=True)

            sr = StrategyResult(
                strategy_index=idx,
                strategy_name=action,
                strategy_kind=kind,
            )

            # ---------------------------------------------------------------
            # Execute strategy — generate IR
            # ---------------------------------------------------------------
            if kind == "clang_flag":
                ir_path, res, cmd = _run_clang_flag_strategy(
                    action, source_path, strat_dir, clang_path
                )
                sr.ir_command = _cmd_str(cmd)
                sr.ir_returncode = res.returncode
                sr.ir_stdout = res.stdout
                sr.ir_stderr = res.stderr
                sr.ir_path = ir_path
                sr.ir_ok = ir_path is not None

                if not sr.ir_ok:
                    sr.status = "FAIL"
                    sr.failure_reason = (
                        f"clang returned {res.returncode}. "
                        f"stderr: {res.stderr.strip()[:300]}"
                    )

            else:  # opt_passes
                if not opt_path:
                    sr.status = "ERROR"
                    sr.failure_reason = (
                        "opt not found; cannot run custom-pass strategy. "
                        "Set TOACD_OPT_PATH to the path of opt.exe."
                    )
                    strategy_results.append(sr)
                    continue

                ir_path, results, cmds = _run_opt_passes_strategy(
                    action, source_path, strat_dir, clang_path, opt_path
                )

                # Record all sub-commands as a JSON array in ir_command
                sr.ir_command = json.dumps([_cmd_str(c) for c in cmds])
                # Last result governs the IR step
                last_res = results[-1]
                sr.ir_returncode = last_res.returncode
                sr.ir_stdout = "\n".join(r.stdout for r in results)
                sr.ir_stderr = "\n".join(r.stderr for r in results)
                sr.ir_path = ir_path
                sr.ir_ok = ir_path is not None

                if not sr.ir_ok:
                    sr.status = "FAIL"
                    # Report the real reason (which step failed)
                    for i, r in enumerate(results):
                        if r.returncode != 0:
                            step = "IR generation" if i == 0 else "opt pass"
                            sr.failure_reason = (
                                f"Step {i+1} ({step}) failed with returncode "
                                f"{r.returncode}. "
                                f"stderr: {r.stderr.strip()[:400]}"
                            )
                            break
                    else:
                        sr.failure_reason = "IR file not produced (unknown reason)."

            # ---------------------------------------------------------------
            # IR hash & duplication check
            # ---------------------------------------------------------------
            if sr.ir_ok and sr.ir_path:
                sr.ir_hash = _sha256(sr.ir_path)
                sr.ir_changed = (sr.ir_hash != baseline.ir_hash)

                if sr.ir_hash in seen_hashes:
                    sr.ir_hash_duplicate_of = seen_hashes[sr.ir_hash]
                else:
                    seen_hashes[sr.ir_hash] = idx

            # ---------------------------------------------------------------
            # Build executable & check correctness
            # ---------------------------------------------------------------
            if sr.ir_ok and sr.ir_path:
                exe_path, exe_res, exe_cmd = _build_executable(
                    sr.ir_path, strat_dir, clang_path
                )
                sr.exe_command = _cmd_str(exe_cmd)
                sr.exe_returncode = exe_res.returncode
                sr.exe_stdout = exe_res.stdout
                sr.exe_stderr = exe_res.stderr
                sr.exe_path = exe_path
                sr.exe_ok = exe_path is not None

                if sr.exe_ok:
                    sr.correctness = _check_correctness(exe_path, baseline)
                else:
                    sr.correctness = CorrectnessResult(
                        checked=False,
                        correct=False,
                        ref_exit_code=baseline.run_returncode,
                        opt_exit_code=None,
                        note=(
                            f"Executable build failed (rc={exe_res.returncode}). "
                            f"stderr: {exe_res.stderr.strip()[:300]}"
                        ),
                    )

            # ---------------------------------------------------------------
            # Overall status
            # ---------------------------------------------------------------
            if sr.status == "UNKNOWN":
                if not sr.ir_ok:
                    sr.status = "FAIL"
                elif sr.correctness is not None and not sr.correctness.correct:
                    sr.status = "FAIL"
                    if not sr.failure_reason:
                        sr.failure_reason = sr.correctness.note
                else:
                    sr.status = "PASS"

            strategy_results.append(sr)

        report.strategy_results = strategy_results

    finally:
        # Temporary directories are cleaned up; the JSON report is saved separately.
        try:
            shutil.rmtree(tmproot, ignore_errors=True)
        except Exception:
            pass

    return report


# ---------------------------------------------------------------------------
# Terminal table renderer
# ---------------------------------------------------------------------------

_COL_W = {
    "idx": 3,
    "strategy": 45,
    "status": 7,
    "rc": 4,
    "correct": 9,
    "ir_changed": 10,
    "hash": 16,
    "error": 50,
}


def _trunc(s: str, w: int) -> str:
    s = str(s) if s is not None else "-"
    return s[:w] if len(s) <= w else s[: w - 1] + "…"


def print_table(source_name: str, report: FileReport) -> None:
    """Print a human-readable table for *report* to stdout."""
    sep = "─" * (sum(_COL_W.values()) + len(_COL_W) * 3 + 1)

    print(f"\n{'═'*len(sep)}")
    print(f"  Source: {source_name}")
    if report.clang_info:
        print(f"  clang : {report.clang_info.path} — {report.clang_info.version_string.splitlines()[0]}")
    if report.opt_info and report.opt_info.found:
        print(f"  opt   : {report.opt_info.path} — {report.opt_info.version_string.splitlines()[0]}")
    else:
        print(f"  opt   : NOT FOUND")
    if report.incompatibilities:
        for ic in report.incompatibilities:
            print(f"  ⚠ INCOMPATIBILITY [{ic.kind}]: {ic.detail}")
    if report.baseline:
        b = report.baseline
        bline = (
            f"  Baseline IR OK={b.ir_ok}  hash={b.ir_hash[:16] if b.ir_hash else 'N/A'}  "
            f"ref_run_rc={b.run_returncode}"
        )
        print(bline)
    print(f"{'═'*len(sep)}\n")

    # Header
    hdr = (
        f"{'#':>{_COL_W['idx']}} │ "
        f"{'Strategy':<{_COL_W['strategy']}} │ "
        f"{'Status':<{_COL_W['status']}} │ "
        f"{'RC':>{_COL_W['rc']}} │ "
        f"{'Correct':<{_COL_W['correct']}} │ "
        f"{'IR Changed':<{_COL_W['ir_changed']}} │ "
        f"{'IR Hash (16)':<{_COL_W['hash']}} │ "
        f"{'Error/Note':<{_COL_W['error']}}"
    )
    print(hdr)
    print(sep)

    for sr in report.strategy_results:
        if sr.strategy_index < 0:
            # File-level error row
            print(
                f"{'!':>{_COL_W['idx']}} │ "
                f"{_trunc(sr.strategy_name, _COL_W['strategy']):<{_COL_W['strategy']}} │ "
                f"{'ERROR':<{_COL_W['status']}} │ "
                f"{'-':>{_COL_W['rc']}} │ "
                f"{'-':<{_COL_W['correct']}} │ "
                f"{'-':<{_COL_W['ir_changed']}} │ "
                f"{'-':<{_COL_W['hash']}} │ "
                f"{_trunc(sr.failure_reason, _COL_W['error']):<{_COL_W['error']}}"
            )
            continue

        correct_str = "-"
        if sr.correctness is not None:
            if sr.correctness.checked:
                correct_str = "YES" if sr.correctness.correct else "NO"
            else:
                correct_str = "UNCHECK"

        ir_changed_str = "-"
        if sr.ir_changed is not None:
            ir_changed_str = "YES" if sr.ir_changed else "NO (same)"

        ir_hash_str = sr.ir_hash[:16] if sr.ir_hash else "-"

        dup_note = ""
        if sr.ir_hash_duplicate_of is not None:
            dup_of = sr.ir_hash_duplicate_of
            dup_label = "baseline" if dup_of == -1 else f"#{dup_of}"
            dup_note = f"dup of {dup_label}"

        error_str = sr.failure_reason or dup_note or (
            sr.correctness.note if sr.correctness and sr.correctness.note else ""
        )

        print(
            f"{sr.strategy_index:>{_COL_W['idx']}} │ "
            f"{_trunc(sr.strategy_name, _COL_W['strategy']):<{_COL_W['strategy']}} │ "
            f"{sr.status:<{_COL_W['status']}} │ "
            f"{str(sr.ir_returncode) if sr.ir_returncode is not None else '-':>{_COL_W['rc']}} │ "
            f"{correct_str:<{_COL_W['correct']}} │ "
            f"{ir_changed_str:<{_COL_W['ir_changed']}} │ "
            f"{ir_hash_str:<{_COL_W['hash']}} │ "
            f"{_trunc(error_str, _COL_W['error']):<{_COL_W['error']}}"
        )

    print(sep)
    print()


# ---------------------------------------------------------------------------
# JSON report saver
# ---------------------------------------------------------------------------

def save_report(report: FileReport, report_dir: str) -> str:
    """
    Serialize *report* to a JSON file in *report_dir*.
    Returns the absolute path of the saved file.
    """
    os.makedirs(report_dir, exist_ok=True)
    safe_name = report.source_file.replace(".", "_").replace(" ", "_")
    ts = report.timestamp.replace(":", "-").replace("T", "_")
    filename = f"diag_{safe_name}_{ts}.json"
    filepath = os.path.join(report_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, default=str)

    return filepath


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_diagnostic(
    extra_test_files: list[dict] | None = None,
    report_dir: str | None = None,
) -> int:
    """
    Run the full diagnostic for all configured test files.
    Returns 0 on complete success, 1 if any strategy failed.
    """
    if report_dir is None:
        report_dir = REPORT_DIR

    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    # -----------------------------------------------------------------------
    # 1. Verify toolchain
    # -----------------------------------------------------------------------
    print("=" * 70)
    print("TOACD MOO Diagnostic — Stage 1: Strategy Verification")
    print(f"Timestamp: {timestamp}")
    print("=" * 70)

    clang_info, opt_info, incompat = verify_toolchain()

    print(f"\n[Toolchain]")
    print(f"  clang : {'FOUND' if clang_info.found else 'NOT FOUND'}")
    if clang_info.found:
        print(f"    path   : {clang_info.path}")
        print(f"    version: {clang_info.version_string.splitlines()[0]}")
    print(f"  opt   : {'FOUND' if opt_info.found else 'NOT FOUND'}")
    if opt_info.found:
        print(f"    path   : {opt_info.path}")
        print(f"    version: {opt_info.version_string.splitlines()[0]}")
    if incompat:
        print(f"\n  ⚠ Incompatibilities detected:")
        for ic in incompat:
            print(f"    [{ic.kind}] {ic.detail}")
    else:
        print("  ✓ No toolchain incompatibilities detected.")

    if not clang_info.found:
        print("\nFATAL: clang not found. Cannot run diagnostic.")
        return 1

    # -----------------------------------------------------------------------
    # 2. Determine test files
    # -----------------------------------------------------------------------
    test_files = extra_test_files if extra_test_files is not None else TEST_FILES

    print(f"\n[ACTIONS to test ({len(ACTIONS)} strategies)]")
    for i, a in enumerate(ACTIONS):
        print(f"  [{i}] {a}")

    print(f"\n[Test files ({len(test_files)})]")
    for tf in test_files:
        status = "FOUND" if tf.get("path") and os.path.isfile(tf["path"]) else "MISSING"
        print(f"  {tf['name']} — {status}")
        if tf.get("path"):
            print(f"    {tf['path']}")

    # -----------------------------------------------------------------------
    # 3. Run diagnostic per file
    # -----------------------------------------------------------------------
    all_reports: list[FileReport] = []
    overall_pass = True

    for tf in test_files:
        src_name = tf["name"]
        src_path = tf.get("path")

        print(f"\n{'━'*70}")
        print(f"Running diagnostic for: {src_name}")
        print(f"{'━'*70}")

        file_report = diagnose_file(
            source_name=src_name,
            source_path=src_path,
            clang_info=clang_info,
            opt_info=opt_info,
            incompatibilities=incompat,
            timestamp=timestamp,
        )
        all_reports.append(file_report)

        # Print table
        print_table(src_name, file_report)

        # Save JSON
        json_path = save_report(file_report, report_dir)
        print(f"  JSON report saved: {json_path}\n")

        # Check overall pass/fail
        for sr in file_report.strategy_results:
            if sr.status in ("FAIL", "ERROR"):
                overall_pass = False

    # -----------------------------------------------------------------------
    # 4. Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)
    for rep in all_reports:
        passes = sum(1 for r in rep.strategy_results if r.status == "PASS")
        fails  = sum(1 for r in rep.strategy_results if r.status == "FAIL")
        errors = sum(1 for r in rep.strategy_results if r.status == "ERROR")
        total  = len(rep.strategy_results)
        print(f"\n  {rep.source_file}")
        print(f"    Strategies: {total}  |  PASS: {passes}  FAIL: {fails}  ERROR: {errors}")

        for sr in rep.strategy_results:
            if sr.status in ("FAIL", "ERROR"):
                print(f"    ✗ [{sr.strategy_index}] {sr.strategy_name}: {sr.failure_reason[:120]}")

    print()
    print(f"Report directory: {report_dir}")
    print()

    return 0 if overall_pass else 1
