"""
moo/bench/schema.py — Versioned data models for the Week 9 benchmark system.

All output artifacts carry an explicit schema_version field so that readers can
detect format changes.  Failures are represented as null + explicit reason;
values are never fabricated or zero-filled.

O0 baseline documentation
--------------------------
The project has three distinct O0-related conventions inherited from Week 8:

  1. O0 correctness/normalization baseline
       pipeline.evaluate_program() compiles a reference executable with
       ``clang -O0 <source> -o ref.exe`` and measures it.  All candidate
       results are normalized against this measurement.  The strategy name
       used in MOO reports is ``"baseline (-O0)"``.

  2. O0 feature/IR baseline  (-disable-O0-optnone)
       ir_feature_extractor.py generates IR with
       ``clang -O0 -disable-O0-optnone -S -emit-llvm`` so that the 8
       canonical IR features are extracted from uninhibited IR, not from the
       optnone-annotated IR that clang -O0 normally emits.

  3. O0 as a strategy inside ACTIONS
       ``"-O0"`` appears as one of the nine ACTIONS that the DQN and Pareto
       analysis evaluate.  This is a distinct role from the normalization
       baseline above — the baseline build is separate from the ACTIONS build.

Week 9 does NOT redefine any of these conventions.  Results produced by the
bench runner inherit the same O0 baseline used by pipeline.evaluate_program().
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Schema version identifiers
# ---------------------------------------------------------------------------

BENCH_SCHEMA_VERSION: str = "week9.1.0"
"""Version string embedded in every run_manifest.json produced by this package."""

DATASET_SCHEMA_VERSION: str = "week9.1.0"
"""Version string embedded in every dataset_manifest.json produced by this package."""


# ---------------------------------------------------------------------------
# Corpus entry
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class CorpusEntry:
    """
    Deterministic descriptor for one C program in the benchmark corpus.

    Fields
    ------
    program_id      : stable unique identifier, e.g. "01_hello_world" or
                      "gen_loop_seed42_0"
    source_path     : absolute path to the .c source file
    source_sha256   : SHA-256 hex digest of the source bytes
    origin          : "existing" | "generated"
    family          : for generated programs, the generator family name
                      (e.g. "loop"); None for existing programs
    generator_seed  : the random seed used (int) or None
    generator_index : per-family program index (int) or None
    excluded        : True if this program is excluded from runs
    exclusion_reason: human-readable reason (None if not excluded)
    """
    program_id: str
    source_path: str
    source_sha256: str
    origin: str                       # "existing" | "generated"
    family: Optional[str] = None
    generator_seed: Optional[int] = None
    generator_index: Optional[int] = None
    excluded: bool = False
    exclusion_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "program_id": self.program_id,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "origin": self.origin,
            "family": self.family,
            "generator_seed": self.generator_seed,
            "generator_index": self.generator_index,
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CorpusEntry":
        return cls(
            program_id=str(d.get("program_id", "")),
            source_path=str(d.get("source_path", "")),
            source_sha256=str(d.get("source_sha256", "")),
            origin=str(d.get("origin", "existing")),
            family=d.get("family"),
            generator_seed=d.get("generator_seed"),
            generator_index=d.get("generator_index"),
            excluded=bool(d.get("excluded", False)),
            exclusion_reason=d.get("exclusion_reason"),
        )


# ---------------------------------------------------------------------------
# Run manifest (written at suite start, updated at completion)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class RunManifest:
    """
    Top-level descriptor for one benchmark suite run.

    Written to ``run_manifest.json`` in the run output directory.

    Fields
    ------
    schema_version    : always BENCH_SCHEMA_VERSION
    run_id            : unique run identifier, e.g. "20261004T140722-abc1234f"
    created_at        : ISO-8601 timestamp when the run was started
    completed_at      : ISO-8601 timestamp when the run finished (None if
                        the run has not completed or was interrupted)
    git_commit        : HEAD SHA if available, else None
    suite_name        : human label for this benchmark suite
    program_ids       : ordered list of program IDs included in this run
                        (deterministic; excludes excluded programs)
    strategies        : list of strategy names evaluated per program
    warmup_runs       : number of warm-up executions per candidate
    measure_runs      : number of timed executions per candidate
    timeout_s         : per-run wall-clock timeout in seconds
    cv_threshold      : CV warn threshold from config
    toolchain         : dict with clang/opt version strings (or None)
    platform          : dict with platform information
    baseline_convention : documentation string for the O0 baseline used
    feature_convention  : documentation string for the 8 canonical IR features
    n_programs_total  : total programs in suite (including excluded)
    n_programs_run    : programs actually evaluated
    n_programs_ok     : programs with at least one valid candidate measurement
    n_programs_failed : programs where the pipeline itself failed
    status            : "running" | "completed" | "interrupted"
    """
    schema_version: str
    run_id: str
    created_at: str
    suite_name: str
    program_ids: list
    strategies: list
    warmup_runs: int
    measure_runs: int
    timeout_s: int
    cv_threshold: float
    toolchain: Optional[dict]
    platform: dict
    baseline_convention: str
    feature_convention: str
    n_programs_total: int = 0
    n_programs_run: int = 0
    n_programs_ok: int = 0
    n_programs_failed: int = 0
    completed_at: Optional[str] = None
    git_commit: Optional[str] = None
    status: str = "running"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "git_commit": self.git_commit,
            "suite_name": self.suite_name,
            "program_ids": list(self.program_ids),
            "strategies": list(self.strategies),
            "warmup_runs": self.warmup_runs,
            "measure_runs": self.measure_runs,
            "timeout_s": self.timeout_s,
            "cv_threshold": self.cv_threshold,
            "toolchain": self.toolchain,
            "platform": self.platform,
            "baseline_convention": self.baseline_convention,
            "feature_convention": self.feature_convention,
            "n_programs_total": self.n_programs_total,
            "n_programs_run": self.n_programs_run,
            "n_programs_ok": self.n_programs_ok,
            "n_programs_failed": self.n_programs_failed,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunManifest":
        return cls(
            schema_version=str(d.get("schema_version", BENCH_SCHEMA_VERSION)),
            run_id=str(d.get("run_id", "")),
            created_at=str(d.get("created_at", "")),
            suite_name=str(d.get("suite_name", "")),
            program_ids=list(d.get("program_ids", [])),
            strategies=list(d.get("strategies", [])),
            warmup_runs=int(d.get("warmup_runs", 3)),
            measure_runs=int(d.get("measure_runs", 10)),
            timeout_s=int(d.get("timeout_s", 30)),
            cv_threshold=float(d.get("cv_threshold", 0.10)),
            toolchain=d.get("toolchain"),
            platform=dict(d.get("platform", {})),
            baseline_convention=str(d.get("baseline_convention", "")),
            feature_convention=str(d.get("feature_convention", "")),
            n_programs_total=int(d.get("n_programs_total", 0)),
            n_programs_run=int(d.get("n_programs_run", 0)),
            n_programs_ok=int(d.get("n_programs_ok", 0)),
            n_programs_failed=int(d.get("n_programs_failed", 0)),
            completed_at=d.get("completed_at"),
            git_commit=d.get("git_commit"),
            status=str(d.get("status", "running")),
        )


# ---------------------------------------------------------------------------
# Per-program record
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ProgramRecord:
    """
    Benchmark result record for one C program across all evaluated strategies.

    Written to ``results/<program_id>.json`` inside the run output directory.
    Failures are represented as null + explicit reason; values are never
    fabricated or zero-filled.

    Fields
    ------
    schema_version   : always BENCH_SCHEMA_VERSION
    run_id           : matches the RunManifest run_id
    program_id       : matches the CorpusEntry program_id
    corpus_entry     : serialized CorpusEntry for this program
    status           : "ok" | "pipeline_error" | "no_valid_candidates"
    pipeline_error   : error string if the pipeline itself failed (None = ok)
    baseline         : serialized baseline measurement from MOOEvaluationResult
                       (None if pipeline failed)
    candidates       : list of serialized CandidateResult dicts
                       (None if pipeline failed)
    pareto_frontier  : list of strategy names on Pareto frontier
    pareto_dominated : list of dominated strategy names
    pareto_invalid   : list of invalid strategy names
    objectives_used  : list of objective names used
    features         : 8 canonical IR feature counts (None if unavailable)
    program_profile  : ProgramProfile dict (None if unavailable)
    toolchain_notes  : list of toolchain warning strings
    evaluated_at     : ISO-8601 timestamp for this specific program's evaluation
    """
    schema_version: str
    run_id: str
    program_id: str
    corpus_entry: dict
    status: str
    evaluated_at: str
    pipeline_error: Optional[str] = None
    baseline: Optional[dict] = None
    candidates: Optional[list] = None
    pareto_frontier: Optional[list] = None
    pareto_dominated: Optional[list] = None
    pareto_invalid: Optional[list] = None
    objectives_used: Optional[list] = None
    features: Optional[dict] = None
    program_profile: Optional[dict] = None
    toolchain_notes: Optional[list] = None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "program_id": self.program_id,
            "corpus_entry": self.corpus_entry,
            "status": self.status,
            "evaluated_at": self.evaluated_at,
            "pipeline_error": self.pipeline_error,
            "baseline": self.baseline,
            "candidates": self.candidates,
            "pareto_frontier": self.pareto_frontier,
            "pareto_dominated": self.pareto_dominated,
            "pareto_invalid": self.pareto_invalid,
            "objectives_used": self.objectives_used,
            "features": self.features,
            "program_profile": self.program_profile,
            "toolchain_notes": self.toolchain_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProgramRecord":
        return cls(
            schema_version=str(d.get("schema_version", BENCH_SCHEMA_VERSION)),
            run_id=str(d.get("run_id", "")),
            program_id=str(d.get("program_id", "")),
            corpus_entry=dict(d.get("corpus_entry", {})),
            status=str(d.get("status", "ok")),
            evaluated_at=str(d.get("evaluated_at", "")),
            pipeline_error=d.get("pipeline_error"),
            baseline=d.get("baseline"),
            candidates=d.get("candidates"),
            pareto_frontier=d.get("pareto_frontier"),
            pareto_dominated=d.get("pareto_dominated"),
            pareto_invalid=d.get("pareto_invalid"),
            objectives_used=d.get("objectives_used"),
            features=d.get("features"),
            program_profile=d.get("program_profile"),
            toolchain_notes=d.get("toolchain_notes"),
        )


# ---------------------------------------------------------------------------
# Dataset manifest
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class DatasetManifest:
    """
    Descriptor for a generated dataset (CSV files + this manifest).

    Written to ``dataset_manifest.json`` alongside the CSV files.

    Column dictionaries
    -------------------
    candidate_rows.csv columns (one row per program × strategy):
        program_id, strategy_name, origin, family, is_pareto_frontier,
        is_pareto_dominated, is_valid, execution_time_norm,
        energy_norm, code_size_norm, carbon_norm,
        BasicBlocksCount, InstructionsCount, BranchCount, MemInstCount,
        MathInstCount, FloatInstCount, VectorInstCount, CallInstCount,
        profile_label, is_trivial, split

    program_rows.csv columns (one row per program):
        program_id, origin, family, n_valid_candidates, n_frontier,
        n_dominated, n_invalid, baseline_exec_time_s, baseline_energy_j,
        baseline_code_size_bytes, baseline_carbon_g,
        BasicBlocksCount, InstructionsCount, BranchCount, MemInstCount,
        MathInstCount, FloatInstCount, VectorInstCount, CallInstCount,
        profile_label, is_trivial, split

    Split policy: 70% train / 15% validation / 15% test.
    Generated variants from the same family are kept in the same split
    to prevent data leakage.  Existing programs are split individually.
    Splitting is deterministic (seeded with the run_id string).

    Label note: No "best_strategy" label is provided, as this would
    contradict the existing MOO policy which deliberately does not select
    a single best strategy — the Pareto frontier is the correct output.
    """
    schema_version: str
    source_run_id: str
    created_at: str
    n_candidate_rows: int
    n_program_rows: int
    split_policy: dict
    column_dict_candidate: dict
    column_dict_program: dict
    exclusions: list
    label_note: str
    checksums: dict
    candidate_csv_path: str
    program_csv_path: str

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_run_id": self.source_run_id,
            "created_at": self.created_at,
            "n_candidate_rows": self.n_candidate_rows,
            "n_program_rows": self.n_program_rows,
            "split_policy": self.split_policy,
            "column_dict_candidate": self.column_dict_candidate,
            "column_dict_program": self.column_dict_program,
            "exclusions": self.exclusions,
            "label_note": self.label_note,
            "checksums": self.checksums,
            "candidate_csv_path": self.candidate_csv_path,
            "program_csv_path": self.program_csv_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetManifest":
        return cls(
            schema_version=str(d.get("schema_version", DATASET_SCHEMA_VERSION)),
            source_run_id=str(d.get("source_run_id", "")),
            created_at=str(d.get("created_at", "")),
            n_candidate_rows=int(d.get("n_candidate_rows", 0)),
            n_program_rows=int(d.get("n_program_rows", 0)),
            split_policy=dict(d.get("split_policy", {})),
            column_dict_candidate=dict(d.get("column_dict_candidate", {})),
            column_dict_program=dict(d.get("column_dict_program", {})),
            exclusions=list(d.get("exclusions", [])),
            label_note=str(d.get("label_note", "")),
            checksums=dict(d.get("checksums", {})),
            candidate_csv_path=str(d.get("candidate_csv_path", "")),
            program_csv_path=str(d.get("program_csv_path", "")),
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_valid_number(v: Any) -> bool:
    """Return True if v is a finite, non-NaN float or int (not None)."""
    if v is None:
        return False
    try:
        f = float(v)
        return math.isfinite(f)
    except (TypeError, ValueError):
        return False


def validate_no_nan_inf(d: dict, path: str = "") -> list[str]:
    """
    Recursively check a dict for NaN/Inf float values.
    Returns a list of dotted key paths where invalid floats were found.
    """
    errors: list[str] = []
    for k, v in d.items():
        full_key = f"{path}.{k}" if path else str(k)
        if isinstance(v, float):
            if not math.isfinite(v):
                errors.append(f"{full_key}={v!r}")
        elif isinstance(v, dict):
            errors.extend(validate_no_nan_inf(v, full_key))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, float) and not math.isfinite(item):
                    errors.append(f"{full_key}[{i}]={item!r}")
                elif isinstance(item, dict):
                    errors.extend(validate_no_nan_inf(item, f"{full_key}[{i}]"))
    return errors
