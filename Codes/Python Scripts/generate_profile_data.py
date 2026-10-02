"""
generate_profile_data.py — Deterministic threshold generator for TOACD program profiling.

Part of Week 7 Phase 2A (Profile Data Foundation).

Inspects test programs in test_cases/, extracts the canonical 8 IR features,
determines the non-trivial program subset, computes 75th-percentile thresholds,
and writes moo/profile_data/thresholds.json.

ACADEMIC DEFICIENCY AND INTEGRITY BOUNDS:
- Does NOT train any ML model (no classifier, no clustering, no regression).
- Does NOT create .pkl, .joblib, or sklearn dependencies.
- Does NOT claim to discover semantic ground truth.
- Thresholds are derived deterministically from the non-trivial corpus subset.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Optional

# Ensure parent directory is on sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODES_DIR = os.path.dirname(_SCRIPT_DIR)
_PROJECT_DIR = os.path.dirname(_CODES_DIR)

if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from moo.xai import CANONICAL_IR_FEATURE_NAMES


# ---------------------------------------------------------------------------
# Toolchain & Path Discovery
# ---------------------------------------------------------------------------
def _find_clang() -> str:
    """Discover clang executable from config, common paths, or PATH."""
    try:
        from moo.config import CLANG_PATH
        if CLANG_PATH and os.path.isfile(CLANG_PATH):
            return CLANG_PATH
    except Exception:
        pass

    common = [
        r"C:\Program Files\LLVM\bin\clang.exe",
        r"C:\Program Files (x86)\LLVM\bin\clang.exe",
        "/usr/bin/clang",
        "/usr/local/bin/clang",
    ]
    for p in common:
        if os.path.isfile(p):
            return os.path.abspath(p)

    found = shutil.which("clang") or shutil.which("clang.exe")
    if found:
        return os.path.abspath(found)

    raise RuntimeError("clang executable not found for IR feature extraction.")


def _find_test_cases_dir() -> str:
    """Locate the test_cases directory."""
    candidates = [
        os.path.join(_CODES_DIR, "test_cases"),
        os.path.join(_SCRIPT_DIR, "test_cases"),
        os.path.join(_PROJECT_DIR, "Codes", "test_cases"),
    ]
    for d in candidates:
        if os.path.isdir(d):
            return os.path.abspath(d)
    raise FileNotFoundError("Could not locate test_cases directory.")


# ---------------------------------------------------------------------------
# Canonical 8-Feature IR Extraction (matches ml_optimizer.py CompilerEnv)
# ---------------------------------------------------------------------------
def extract_ir_features_from_file(ir_path: str) -> dict[str, float]:
    """
    Extract the canonical 8 static IR features from an unoptimized LLVM IR file.
    Identical logic to ml_optimizer.py CompilerEnv.extract_features().
    """
    features: dict[str, float] = {name: 0.0 for name in CANONICAL_IR_FEATURE_NAMES}
    if not os.path.isfile(ir_path):
        return features

    try:
        with open(ir_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.split(";")[0].strip()
                if not line:
                    continue
                if re.match(r"^[a-zA-Z0-9_.]+:$", line):
                    features["BasicBlocksCount"] += 1.0

                parts = line.split()
                if not parts:
                    continue
                op = parts[0]
                if len(parts) >= 3 and parts[1] == "=":
                    op = parts[2]

                if op in ["br", "switch"]:
                    features["BranchCount"] += 1.0
                elif op in ["alloca", "load", "store", "getelementptr"]:
                    features["MemInstCount"] += 1.0
                elif op in [
                    "add", "sub", "mul", "udiv", "sdiv", "urem", "srem",
                    "shl", "lshr", "ashr", "and", "or", "xor",
                ]:
                    features["MathInstCount"] += 1.0
                elif op in ["fadd", "fsub", "fmul", "fdiv", "frem", "fneg"]:
                    features["FloatInstCount"] += 1.0
                elif op in ["extractelement", "insertelement", "shufflevector"]:
                    features["VectorInstCount"] += 1.0
                elif op in ["call", "invoke"]:
                    features["CallInstCount"] += 1.0

                features["InstructionsCount"] += 1.0
    except Exception as exc:
        print(f"Warning: feature extraction error on {ir_path}: {exc}", file=sys.stderr)

    return features


def extract_features_for_c_file(clang_path: str, c_path: str, temp_dir: str) -> Optional[dict[str, float]]:
    """Compile C source to unoptimized LLVM IR and extract 8 features."""
    base = os.path.basename(c_path)
    ir_path = os.path.join(temp_dir, f"temp_{base}.ll")
    cmd = [
        clang_path,
        "-O0",
        "-Xclang",
        "-disable-O0-optnone",
        "-S",
        "-emit-llvm",
        c_path,
        "-o",
        ir_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            print(f"Skipping {base}: compilation failed ({r.stderr.strip()[:60]})", file=sys.stderr)
            return None
        features = extract_ir_features_from_file(ir_path)
        return features
    finally:
        if os.path.exists(ir_path):
            try:
                os.remove(ir_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Percentile Calculation (Deterministic, without numpy dependency requirement)
# ---------------------------------------------------------------------------
def calculate_percentile(values: list[float], percentile: float) -> float:
    """
    Compute the p-th percentile of a list of floats using linear interpolation.
    Matches numpy.percentile method='linear'.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    rank = (percentile / 100.0) * (n - 1)
    k = int(rank)
    d = rank - k
    if k + 1 < n:
        return sorted_vals[k] + d * (sorted_vals[k + 1] - sorted_vals[k])
    return sorted_vals[-1]


# ---------------------------------------------------------------------------
# Main Generation Routine
# ---------------------------------------------------------------------------
# Rule for identifying trivial programs:
# Straight-line programs with no branch logic, loops, or complex algorithms
# emit 22-34 instructions in clang -O0 LLVM IR (standard prologue/epilogue only).
# Real benchmark programs in this corpus have >= 35 instructions.
TRIVIAL_INSTRUCTION_THRESHOLD = 35.0

# Files to exclude from threshold analysis (infrastructure / scaffold scripts)
EXCLUDED_FILENAMES = {"test.c", "test_remove.c"}


def generate_thresholds_data(output_path: Optional[str] = None) -> dict[str, Any]:
    """
    Scan all test programs, compute percentiles on non-trivial programs,
    and save the threshold data to JSON.
    """
    clang_path = _find_clang()
    test_cases_dir = _find_test_cases_dir()

    if output_path is None:
        profile_data_dir = os.path.join(_SCRIPT_DIR, "moo", "profile_data")
        os.makedirs(profile_data_dir, exist_ok=True)
        output_path = os.path.join(profile_data_dir, "thresholds.json")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    c_files = sorted(
        [
            os.path.join(test_cases_dir, f)
            for f in os.listdir(test_cases_dir)
            if f.endswith(".c") and f not in EXCLUDED_FILENAMES
        ]
    )

    print(f"Discovered {len(c_files)} candidate C test programs in {test_cases_dir}")

    all_records: list[tuple[str, dict[str, float]]] = []
    temp_dir = _SCRIPT_DIR

    for c_path in c_files:
        name = os.path.basename(c_path)
        feats = extract_features_for_c_file(clang_path, c_path, temp_dir)
        if feats is not None:
            all_records.append((name, feats))

    print(f"Extracted features for {len(all_records)} programs.")

    # Partition into trivial and non-trivial
    non_trivial = [
        (name, f) for name, f in all_records
        if f["InstructionsCount"] >= TRIVIAL_INSTRUCTION_THRESHOLD
    ]
    trivial = [
        (name, f) for name, f in all_records
        if f["InstructionsCount"] < TRIVIAL_INSTRUCTION_THRESHOLD
    ]

    print(f"Non-trivial subset : {len(non_trivial)} programs (InstructionsCount >= {TRIVIAL_INSTRUCTION_THRESHOLD})")
    print(f"Trivial subset     : {len(trivial)} programs (InstructionsCount < {TRIVIAL_INSTRUCTION_THRESHOLD})")

    if not non_trivial:
        raise RuntimeError("No non-trivial programs found to calculate thresholds.")

    # Feature lists across non-trivial subset
    br_vals = [f["BranchCount"] for _, f in non_trivial]
    compute_vals = [f["MathInstCount"] + f["FloatInstCount"] for _, f in non_trivial]
    mem_vals = [f["MemInstCount"] for _, f in non_trivial]
    call_vals = [f["CallInstCount"] for _, f in non_trivial]

    # Calculate 75th percentiles (primary thresholds for orientation)
    p75_branch = round(calculate_percentile(br_vals, 75.0), 2)
    p75_compute = round(calculate_percentile(compute_vals, 75.0), 2)
    p75_mem = round(calculate_percentile(mem_vals, 75.0), 2)
    p75_call = round(calculate_percentile(call_vals, 75.0), 2)

    # Calculate 50th percentiles (for reference/transparency)
    p50_branch = round(calculate_percentile(br_vals, 50.0), 2)
    p50_compute = round(calculate_percentile(compute_vals, 50.0), 2)
    p50_mem = round(calculate_percentile(mem_vals, 50.0), 2)
    p50_call = round(calculate_percentile(call_vals, 50.0), 2)

    data: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source_directory": os.path.relpath(test_cases_dir, _PROJECT_DIR),
            "total_programs_scanned": len(all_records),
            "non_trivial_programs_count": len(non_trivial),
            "trivial_programs_count": len(trivial),
            "trivial_definition": (
                f"InstructionsCount < {TRIVIAL_INSTRUCTION_THRESHOLD} "
                "(straight-line prologue/epilogue without algorithmic branching)"
            ),
            "percentile_selection": "75th percentile of non-trivial program subset",
            "feature_schema": list(CANONICAL_IR_FEATURE_NAMES),
        },
        "thresholds": {
            "trivial_instructions": TRIVIAL_INSTRUCTION_THRESHOLD,
            "branch_count": p75_branch,
            "compute_count": p75_compute,
            "mem_count": p75_mem,
            "call_count": p75_call,
        },
        "summary_percentiles": {
            "p50": {
                "branch_count": p50_branch,
                "compute_count": p50_compute,
                "mem_count": p50_mem,
                "call_count": p50_call,
            },
            "p75": {
                "branch_count": p75_branch,
                "compute_count": p75_compute,
                "mem_count": p75_mem,
                "call_count": p75_call,
            },
        },
        "reference_program_counts": {
            "non_trivial_programs": [name for name, _ in non_trivial],
            "trivial_programs": [name for name, _ in trivial],
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\nSuccessfully wrote deterministic thresholds to:\n  {output_path}")
    print(f"Thresholds (75th percentile of non-trivial subset):")
    print(f"  • BranchCount  >= {p75_branch}  -> loop_oriented candidate")
    print(f"  • ComputeCount >= {p75_compute}  -> compute_oriented candidate")
    print(f"  • MemInstCount >= {p75_mem} -> memory_oriented candidate")
    print(f"  • CallInstCount>= {p75_call}  -> call_oriented candidate")
    print(f"  • InstCount    <  {TRIVIAL_INSTRUCTION_THRESHOLD} -> trivial program")

    return data


if __name__ == "__main__":
    generate_thresholds_data()
