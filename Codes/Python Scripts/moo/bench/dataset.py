"""
moo/bench/dataset.py — Structured dataset builder for Week 9.

Converts completed benchmark run records into structured CSV datasets
suitable for later ML/evaluation work.

Outputs
-------
candidate_rows.csv  : one row per program × strategy (valid candidates only)
program_rows.csv    : one row per program (summary)
dataset_manifest.json : schema version, checksums, column dictionary, split info

Split policy: 70% train / 15% validation / 15% test.
  - Generated programs from the same family are always kept in the same split
    (family-group assignment, to prevent leakage between train and test).
  - Existing programs are treated as individual units.
  - Splitting is deterministic: seeded with the run_id string.

Label note: No "best_strategy" label is provided.
  The MOO policy deliberately does not select a single best strategy —
  the Pareto frontier is the correct output of the pipeline.
  A label claiming one strategy is "best" would contradict this policy
  and be academically dishonest for a multi-objective problem.

Data integrity:
  - Failures are represented as None/empty (never zero-filled).
  - Normalized metric values that are None, NaN, or Inf are written as
    empty string in CSV (not 0.0).
  - Checksums (SHA-256) of both CSV files are stored in the manifest.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import math
import os
import random
from typing import Any, Optional

from .schema import (
    DATASET_SCHEMA_VERSION,
    DatasetManifest,
    ProgramRecord,
)

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

_CANDIDATE_COLUMNS = [
    "program_id",
    "strategy_name",
    "strategy_index",
    "strategy_kind",
    "origin",
    "family",
    "is_pareto_frontier",
    "is_pareto_dominated",
    "is_valid",
    "execution_time_norm",
    "energy_norm",
    "code_size_norm",
    "carbon_norm",
    "BasicBlocksCount",
    "InstructionsCount",
    "BranchCount",
    "MemInstCount",
    "MathInstCount",
    "FloatInstCount",
    "VectorInstCount",
    "CallInstCount",
    "profile_label",
    "is_trivial",
    "split",
]

_PROGRAM_COLUMNS = [
    "program_id",
    "origin",
    "family",
    "n_valid_candidates",
    "n_frontier",
    "n_dominated",
    "n_invalid",
    "baseline_exec_time_s",
    "baseline_energy_j",
    "baseline_code_size_bytes",
    "baseline_carbon_g",
    "BasicBlocksCount",
    "InstructionsCount",
    "BranchCount",
    "MemInstCount",
    "MathInstCount",
    "FloatInstCount",
    "VectorInstCount",
    "CallInstCount",
    "profile_label",
    "is_trivial",
    "split",
]

_COLUMN_DICT_CANDIDATE = {
    "program_id":          "Unique program identifier",
    "strategy_name":       "Optimization strategy name (e.g. '-O2')",
    "strategy_index":      "0-based index in ACTIONS list",
    "strategy_kind":       "'clang_flag' or 'opt_passes'",
    "origin":              "'existing' or 'generated'",
    "family":              "Generator family (None for existing programs)",
    "is_pareto_frontier":  "1 if this candidate is on the Pareto frontier",
    "is_pareto_dominated": "1 if this candidate is dominated",
    "is_valid":            "1 if candidate built, ran correctly, and was measured",
    "execution_time_norm": "Execution time normalized against O0 baseline (< 1 = faster)",
    "energy_norm":         "Estimated energy normalized against O0 baseline",
    "code_size_norm":      "Code size normalized against O0 baseline",
    "carbon_norm":         "Estimated carbon normalized against O0 baseline",
    "BasicBlocksCount":    "IR feature: number of basic blocks (O0 baseline IR)",
    "InstructionsCount":   "IR feature: total instruction count",
    "BranchCount":         "IR feature: branch/switch instruction count",
    "MemInstCount":        "IR feature: memory instruction count",
    "MathInstCount":       "IR feature: integer arithmetic instruction count",
    "FloatInstCount":      "IR feature: floating-point instruction count",
    "VectorInstCount":     "IR feature: vector instruction count",
    "CallInstCount":       "IR feature: function call instruction count",
    "profile_label":       "IR-derived program profile label",
    "is_trivial":          "1 if program is below trivial threshold",
    "split":               "Dataset split assignment: train/val/test",
}

_COLUMN_DICT_PROGRAM = {
    "program_id":              "Unique program identifier",
    "origin":                  "'existing' or 'generated'",
    "family":                  "Generator family (None for existing programs)",
    "n_valid_candidates":      "Number of valid (measured) candidates",
    "n_frontier":              "Number of Pareto-frontier candidates",
    "n_dominated":             "Number of dominated candidates",
    "n_invalid":               "Number of invalid (failed) candidates",
    "baseline_exec_time_s":    "O0 baseline median execution time in seconds",
    "baseline_energy_j":       "O0 baseline estimated energy in joules",
    "baseline_code_size_bytes":"O0 baseline code size in bytes",
    "baseline_carbon_g":       "O0 baseline estimated carbon in grams",
    "BasicBlocksCount":        "IR feature: number of basic blocks",
    "InstructionsCount":       "IR feature: total instruction count",
    "BranchCount":             "IR feature: branch/switch instruction count",
    "MemInstCount":            "IR feature: memory instruction count",
    "MathInstCount":           "IR feature: integer arithmetic instruction count",
    "FloatInstCount":          "IR feature: floating-point instruction count",
    "VectorInstCount":         "IR feature: vector instruction count",
    "CallInstCount":           "IR feature: function call instruction count",
    "profile_label":           "IR-derived program profile label",
    "is_trivial":              "1 if program is below trivial threshold",
    "split":                   "Dataset split assignment: train/val/test",
}

_LABEL_NOTE = (
    "No 'best_strategy' label is provided. The existing MOO pipeline "
    "deliberately does not select a single best strategy — the Pareto "
    "frontier is the correct output for a multi-objective problem. "
    "Providing a single-best label would contradict the MOO policy and "
    "be academically dishonest. Use pareto_frontier information instead."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IR_FEATURE_NAMES = [
    "BasicBlocksCount", "InstructionsCount", "BranchCount", "MemInstCount",
    "MathInstCount", "FloatInstCount", "VectorInstCount", "CallInstCount",
]


def _safe_float(v: Any) -> str:
    """Return float as string, or '' if None/NaN/Inf."""
    if v is None:
        return ""
    try:
        f = float(v)
        if not math.isfinite(f):
            return ""
        return str(f)
    except (TypeError, ValueError):
        return ""


def _safe_int(v: Any) -> str:
    """Return int as string, or '' if None."""
    if v is None:
        return ""
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return ""


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_normalized_value(normalized: Optional[dict], key: str) -> str:
    """Extract a normalized objective value by objective name."""
    if not normalized:
        return ""
    # normalized is a NormalizedObjectiveVector.to_dict()
    # It has "objectives" (list of obj specs) and "normalized_values"
    objectives = normalized.get("objectives", [])
    values = normalized.get("normalized_values", [])
    for i, obj in enumerate(objectives):
        obj_name = obj.get("name", "") if isinstance(obj, dict) else str(obj)
        if obj_name == key and i < len(values):
            return _safe_float(values[i])
    return ""


# ---------------------------------------------------------------------------
# Split assignment
# ---------------------------------------------------------------------------

def _assign_splits(
    records: list[ProgramRecord],
    run_id: str,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> dict[str, str]:
    """
    Assign each program_id to 'train', 'val', or 'test'.

    Strategy:
    - Group generated programs by family (to prevent leakage).
    - Treat each existing program as an individual unit.
    - Shuffle units deterministically (seeded from run_id).
    - Assign 70/15/15 at the UNIT level (not individual program level),
      so all programs in a family group are always in the same split.

    Returns dict mapping program_id -> split label.
    """
    rng = random.Random(run_id)  # deterministic: seeded from run_id

    # Separate groups
    existing_pids: list[str] = []
    family_groups: dict[str, list[str]] = {}

    for rec in records:
        pid = rec.program_id
        ce = rec.corpus_entry
        origin = ce.get("origin", "existing")
        family = ce.get("family")

        if origin == "generated" and family:
            if family not in family_groups:
                family_groups[family] = []
            family_groups[family].append(pid)
        else:
            existing_pids.append(pid)

    # Build units list (each unit is a list of program_ids kept together)
    units: list[list[str]] = []
    for pid in sorted(existing_pids):
        units.append([pid])
    for fam in sorted(family_groups.keys()):
        units.append(sorted(family_groups[fam]))

    # Shuffle units deterministically
    rng.shuffle(units)

    # Assign splits at UNIT level: determine label from count BEFORE iterating
    # each unit's programs, then assign ALL programs in the unit that label.
    # This guarantees no family group is ever split across boundaries.
    n_units = len(units)
    n_train_units = max(1, round(n_units * train_frac))
    n_val_units = max(0, round(n_units * val_frac))

    splits: dict[str, str] = {}
    for i, unit in enumerate(units):
        if i < n_train_units:
            label = "train"
        elif i < n_train_units + n_val_units:
            label = "val"
        else:
            label = "test"
        for pid in unit:
            splits[pid] = label

    return splits


# ---------------------------------------------------------------------------
# DatasetBuilder
# ---------------------------------------------------------------------------

class DatasetBuilder:
    """
    Converts benchmark run records into structured CSV datasets.

    Usage
    -----
    builder = DatasetBuilder(output_dir="Codes/Datasets/week9")
    manifest = builder.build(records, run_id="...")
    """

    def __init__(self, output_dir: str):
        self.output_dir = os.path.abspath(output_dir)

    def build(
        self,
        records: list[ProgramRecord],
        run_id: str,
        verbose: bool = True,
    ) -> DatasetManifest:
        """
        Build candidate_rows.csv, program_rows.csv, and dataset_manifest.json.

        Parameters
        ----------
        records : list of ProgramRecord from the benchmark run
        run_id  : run_id from the RunManifest (used as split seed)

        Returns
        -------
        DatasetManifest
        """
        os.makedirs(self.output_dir, exist_ok=True)

        # Filter to records that are useful (ok or no_valid_candidates)
        usable = [r for r in records if r.status in ("ok", "no_valid_candidates")]
        exclusions: list[str] = [
            f"{r.program_id}: {r.status} — {r.pipeline_error or 'no error detail'}"
            for r in records
            if r.status not in ("ok", "no_valid_candidates")
        ]

        # Assign splits
        splits = _assign_splits(usable, run_id)

        candidate_path = os.path.join(self.output_dir, "candidate_rows.csv")
        program_path = os.path.join(self.output_dir, "program_rows.csv")
        manifest_path = os.path.join(self.output_dir, "dataset_manifest.json")

        n_candidate_rows = 0
        n_program_rows = 0

        with open(candidate_path, "w", newline="", encoding="utf-8") as cf, \
             open(program_path, "w", newline="", encoding="utf-8") as pf:

            cwriter = csv.DictWriter(cf, fieldnames=_CANDIDATE_COLUMNS)
            pwriter = csv.DictWriter(pf, fieldnames=_PROGRAM_COLUMNS)
            cwriter.writeheader()
            pwriter.writeheader()

            for rec in usable:
                pid = rec.program_id
                ce = rec.corpus_entry
                origin = ce.get("origin", "existing")
                family = ce.get("family", "")
                split = splits.get(pid, "train")
                profile = rec.program_profile or {}
                features = rec.features or {}

                # Pareto sets for quick lookup
                frontier_set = set(rec.pareto_frontier or [])
                dominated_set = set(rec.pareto_dominated or [])
                invalid_set = set(rec.pareto_invalid or [])

                # --- Program row ---
                n_valid = 0
                n_frontier_c = len(frontier_set)
                n_dominated_c = len(dominated_set)
                n_invalid_c = len(invalid_set)

                # Baseline values
                baseline = rec.baseline or {}
                base_timing = (baseline.get("measurement") or {}).get("timing") or {}
                base_energy = (baseline.get("measurement") or {}).get("energy") or {}
                base_size   = (baseline.get("measurement") or {}).get("code_size") or {}
                base_carbon = (baseline.get("measurement") or {}).get("carbon") or {}

                prog_row = {
                    "program_id":              pid,
                    "origin":                  origin,
                    "family":                  family or "",
                    "n_valid_candidates":      "",  # filled below
                    "n_frontier":              str(n_frontier_c),
                    "n_dominated":             str(n_dominated_c),
                    "n_invalid":               str(n_invalid_c),
                    "baseline_exec_time_s":    _safe_float(base_timing.get("median_s")),
                    "baseline_energy_j":       _safe_float(base_energy.get("energy_joules")),
                    "baseline_code_size_bytes":_safe_int(base_size.get("primary_value")),
                    "baseline_carbon_g":       _safe_float(base_carbon.get("carbon_grams")),
                    "BasicBlocksCount":        _safe_float(features.get("BasicBlocksCount")),
                    "InstructionsCount":       _safe_float(features.get("InstructionsCount")),
                    "BranchCount":             _safe_float(features.get("BranchCount")),
                    "MemInstCount":            _safe_float(features.get("MemInstCount")),
                    "MathInstCount":           _safe_float(features.get("MathInstCount")),
                    "FloatInstCount":          _safe_float(features.get("FloatInstCount")),
                    "VectorInstCount":         _safe_float(features.get("VectorInstCount")),
                    "CallInstCount":           _safe_float(features.get("CallInstCount")),
                    "profile_label":           profile.get("label", ""),
                    "is_trivial":              "1" if profile.get("is_trivial") else "0",
                    "split":                   split,
                }

                # --- Candidate rows ---
                candidates = rec.candidates or []
                n_valid_prog = 0

                for cand in candidates:
                    strat = cand.get("strategy_name", "")
                    valid = bool(
                        cand.get("build_ok") and
                        cand.get("correct") and
                        cand.get("measurement") is not None
                    )
                    if valid:
                        n_valid_prog += 1

                    norm = cand.get("normalized") or {}

                    crow = {
                        "program_id":          pid,
                        "strategy_name":       strat,
                        "strategy_index":      _safe_int(cand.get("strategy_index")),
                        "strategy_kind":       cand.get("strategy_kind", ""),
                        "origin":              origin,
                        "family":              family or "",
                        "is_pareto_frontier":  "1" if strat in frontier_set else "0",
                        "is_pareto_dominated": "1" if strat in dominated_set else "0",
                        "is_valid":            "1" if valid else "0",
                        "execution_time_norm": _get_normalized_value(norm, "execution_time"),
                        "energy_norm":         _get_normalized_value(norm, "energy"),
                        "code_size_norm":      _get_normalized_value(norm, "code_size"),
                        "carbon_norm":         _get_normalized_value(norm, "carbon"),
                        "BasicBlocksCount":    _safe_float(features.get("BasicBlocksCount")),
                        "InstructionsCount":   _safe_float(features.get("InstructionsCount")),
                        "BranchCount":         _safe_float(features.get("BranchCount")),
                        "MemInstCount":        _safe_float(features.get("MemInstCount")),
                        "MathInstCount":       _safe_float(features.get("MathInstCount")),
                        "FloatInstCount":      _safe_float(features.get("FloatInstCount")),
                        "VectorInstCount":     _safe_float(features.get("VectorInstCount")),
                        "CallInstCount":       _safe_float(features.get("CallInstCount")),
                        "profile_label":       profile.get("label", ""),
                        "is_trivial":          "1" if profile.get("is_trivial") else "0",
                        "split":               split,
                    }
                    cwriter.writerow(crow)
                    n_candidate_rows += 1

                # Update program row n_valid_candidates
                prog_row["n_valid_candidates"] = str(n_valid_prog)
                n_valid = n_valid_prog

                pwriter.writerow(prog_row)
                n_program_rows += 1

        # Compute checksums
        checksums = {
            "candidate_rows_sha256": _sha256_file(candidate_path),
            "program_rows_sha256": _sha256_file(program_path),
        }

        split_policy = {
            "train_fraction": 0.70,
            "val_fraction": 0.15,
            "test_fraction": 0.15,
            "method": "family_group_split",
            "description": (
                "Generated programs from the same family are kept in the same split "
                "to prevent feature leakage. Existing programs are split individually. "
                "Splitting is deterministic, seeded from run_id."
            ),
            "seed": run_id,
        }

        manifest = DatasetManifest(
            schema_version=DATASET_SCHEMA_VERSION,
            source_run_id=run_id,
            created_at=datetime.datetime.now().isoformat(timespec="seconds"),
            n_candidate_rows=n_candidate_rows,
            n_program_rows=n_program_rows,
            split_policy=split_policy,
            column_dict_candidate=_COLUMN_DICT_CANDIDATE,
            column_dict_program=_COLUMN_DICT_PROGRAM,
            exclusions=exclusions,
            label_note=_LABEL_NOTE,
            checksums=checksums,
            candidate_csv_path=candidate_path,
            program_csv_path=program_path,
        )

        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2)

        if verbose:
            print(
                f"[dataset] Built: {n_candidate_rows} candidate rows, "
                f"{n_program_rows} program rows"
            )
            print(f"[dataset] Output: {self.output_dir}")

        return manifest
