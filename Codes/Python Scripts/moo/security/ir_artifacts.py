"""
moo.security.ir_artifacts — Deterministic generation of baseline and candidate LLVM IR artifacts.

Reuses toolchain probes and compiler invocation patterns without rewriting existing security modules.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

from ..toolchain import CLANG_PATH, OPT_PATH
from ..strategy_diagnostic import _run_clang_flag_strategy, _run_opt_passes_strategy, _classify_action


def get_clang_path() -> Optional[str]:
    """Retrieve verified CLANG_PATH or find in environment."""
    return CLANG_PATH if CLANG_PATH and os.path.isfile(CLANG_PATH) else None


def get_opt_path() -> Optional[str]:
    """Retrieve verified OPT_PATH or find in environment."""
    return OPT_PATH if OPT_PATH and os.path.isfile(OPT_PATH) else None


def emit_baseline_ir(
    source_path: str,
    workdir: str,
    clang_path: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Compile source_path into unoptimized baseline LLVM IR (-O0 -disable-O0-optnone).
    Returns (ir_path, error_message).
    """
    clang = clang_path or get_clang_path()
    if not clang:
        return None, "clang compiler not found in environment"

    ir_path = os.path.join(workdir, "baseline.ll")
    cmd = [
        clang,
        "-O0",
        "-Xclang", "-disable-O0-optnone",
        "-S", "-emit-llvm",
        source_path,
        "-o", ir_path,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and os.path.isfile(ir_path):
            return ir_path, None
        return None, f"Clang failed (exit {res.returncode}): {res.stderr[:256]}"
    except Exception as exc:
        return None, f"Baseline IR emission error: {exc}"


def emit_candidate_ir(
    strategy: str,
    source_path: str,
    workdir: str,
    clang_path: Optional[str] = None,
    opt_path: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Compile source_path into candidate optimized LLVM IR for the specified strategy.
    Returns (candidate_ir_path, error_message).
    """
    clang = clang_path or get_clang_path()
    if not clang:
        return None, "clang compiler not found in environment"

    action_type = _classify_action(strategy)
    try:
        if action_type == "clang_flag":
            cand_path, res, _ = _run_clang_flag_strategy(strategy, source_path, workdir, clang)
            if cand_path and os.path.isfile(cand_path):
                return cand_path, None
            return None, f"Clang flag compilation failed (exit {res.returncode}): {res.stderr[:256]}"
        else:
            opt = opt_path or get_opt_path()
            if not opt:
                return None, "llvm opt tool not found in environment"
            cand_path, results, _ = _run_opt_passes_strategy(strategy, source_path, workdir, clang, opt)
            if cand_path and os.path.isfile(cand_path):
                return cand_path, None
            last_err = results[-1].stderr if results else "Unknown error"
            return None, f"Opt pass compilation failed: {last_err[:256]}"
    except Exception as exc:
        return None, f"Candidate IR emission error: {exc}"
