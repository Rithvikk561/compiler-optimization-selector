"""
moo/moo_result.py — Structured result model for Stage 3 MOO evaluation.

This module defines the data containers that capture the full output of
one MOO pipeline run (one source program evaluated across all strategies).

Designed to be:
  * Consumed later by: GUI, XAI, regression comparison, adaptive learning
  * Serializable to JSON via to_dict()
  * Backward-compatible with Stage 1 and Stage 2 models

No logic lives here — pure data containers.
"""

from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass
class CandidateResult:
    """
    Full evaluation record for ONE optimization strategy on ONE source file.

    Lifecycle: build → correctness → measure → normalize → Pareto classify

    Fields
    ------
    strategy_name       : e.g. "-O2" or "mem2reg,instcombine"
    strategy_index      : 0-based index in ACTIONS list
    strategy_kind       : "clang_flag" | "opt_passes"

    build_ok            : IR + executable compiled successfully
    build_error         : human-readable build failure reason (None = ok)
    exe_path            : path to the compiled executable (None if build failed)

    correctness_checked : correctness comparison was attempted
    correct             : True = behaviour matches reference
    correctness_details : human-readable correctness diff summary
    reference_exit_code : exit code from the reference/baseline run
    candidate_exit_code : exit code from this candidate's run

    measurement         : raw MeasurementResult from measurement.py (None if not run)
    normalized          : NormalizedObjectiveVector from Stage 2 (None if not measured/correct)

    pareto_status       : "FRONTIER" | "DOMINATED" | "INVALID" | "UNKNOWN"
                          INVALID = failed build or incorrect behaviour
                          UNKNOWN = not yet classified

    dominated_by        : list of strategy names that dominate this candidate
                          (empty unless pareto_status == "DOMINATED")
    """
    strategy_name: str
    strategy_index: int
    strategy_kind: str

    build_ok: bool = False
    build_error: Optional[str] = None
    exe_path: Optional[str] = None

    correctness_checked: bool = False
    correct: bool = False
    correctness_details: str = ""
    reference_exit_code: Optional[int] = None
    candidate_exit_code: Optional[int] = None

    # Stage 1 measurement (stored as a dict for JSON-serializability)
    measurement: Optional[dict] = None   # to_dict() of MeasurementResult

    # Stage 2 normalized objective vector (stored as dict)
    normalized: Optional[dict] = None   # to_dict() of NormalizedObjectiveVector

    pareto_status: str = "UNKNOWN"
    dominated_by: list = dataclasses.field(default_factory=list)

    def is_valid(self) -> bool:
        """True if this candidate may enter Pareto analysis."""
        return self.build_ok and self.correct and self.measurement is not None

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "strategy_index": self.strategy_index,
            "strategy_kind": self.strategy_kind,
            "build_ok": self.build_ok,
            "build_error": self.build_error,
            "exe_path": self.exe_path,
            "correctness_checked": self.correctness_checked,
            "correct": self.correct,
            "correctness_details": self.correctness_details,
            "reference_exit_code": self.reference_exit_code,
            "candidate_exit_code": self.candidate_exit_code,
            "measurement": self.measurement,
            "normalized": self.normalized,
            "pareto_status": self.pareto_status,
            "dominated_by": list(self.dominated_by),
        }


@dataclasses.dataclass
class BaselineMeasurement:
    """
    Baseline (reference/unoptimized) measurement for one source program.

    The baseline is the -O0 unoptimized build against which all candidates
    are normalized.  It is NOT itself a candidate in the Pareto analysis.
    """
    strategy_name: str              # always "baseline (-O0)"
    exe_path: Optional[str]
    build_ok: bool
    build_error: Optional[str]
    reference_exit_code: Optional[int]
    reference_stdout: str
    measurement: Optional[dict]     # to_dict() of MeasurementResult

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "exe_path": self.exe_path,
            "build_ok": self.build_ok,
            "build_error": self.build_error,
            "reference_exit_code": self.reference_exit_code,
            "reference_stdout": self.reference_stdout,
            "measurement": self.measurement,
        }


@dataclasses.dataclass
class MOOEvaluationResult:
    """
    Complete Stage 3 MOO evaluation result for one source program.

    Produced by pipeline.evaluate_program() and consumed by the CLI
    summary printer, JSON report saver, and (later) GUI / XAI layers.

    Fields
    ------
    source_file         : filename of the evaluated C source
    source_path         : absolute path of the C source file
    timestamp           : ISO-8601 timestamp of the run
    toolchain_ok        : True if clang was found (opt may be absent for -Ox strategies)
    toolchain_notes     : list of toolchain warning strings

    baseline            : BaselineMeasurement — the -O0 reference build
    candidates          : list of CandidateResult, one per ACTIONS entry

    pareto_frontier     : strategy names on the Pareto frontier (non-dominated valid candidates)
    pareto_dominated    : strategy names dominated by at least one frontier member
    pareto_invalid      : strategy names that failed build or correctness check

    objectives_used     : list of objective names used in Pareto analysis
                          (subset of ALL_OBJECTIVES; excludes objectives with no valid data)
    pipeline_error      : top-level error string if the pipeline itself crashed (None = ok)
    """
    source_file: str
    source_path: Optional[str]
    timestamp: str
    toolchain_ok: bool = False
    toolchain_notes: list = dataclasses.field(default_factory=list)

    baseline: Optional[BaselineMeasurement] = None
    candidates: list = dataclasses.field(default_factory=list)

    pareto_frontier: list = dataclasses.field(default_factory=list)
    pareto_dominated: list = dataclasses.field(default_factory=list)
    pareto_invalid: list = dataclasses.field(default_factory=list)

    objectives_used: list = dataclasses.field(default_factory=list)
    pipeline_error: Optional[str] = None

    # ----------------------------------------------------------------
    # Convenience views
    # ----------------------------------------------------------------

    def n_valid(self) -> int:
        return sum(1 for c in self.candidates if c.is_valid())

    def n_invalid(self) -> int:
        return sum(1 for c in self.candidates if not c.is_valid())

    def n_strategies(self) -> int:
        return len(self.candidates)

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "source_path": self.source_path,
            "timestamp": self.timestamp,
            "toolchain_ok": self.toolchain_ok,
            "toolchain_notes": list(self.toolchain_notes),
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "pareto_frontier": list(self.pareto_frontier),
            "pareto_dominated": list(self.pareto_dominated),
            "pareto_invalid": list(self.pareto_invalid),
            "objectives_used": list(self.objectives_used),
            "pipeline_error": self.pipeline_error,
            "summary": {
                "n_strategies": self.n_strategies(),
                "n_valid": self.n_valid(),
                "n_invalid": self.n_invalid(),
                "n_frontier": len(self.pareto_frontier),
                "n_dominated": len(self.pareto_dominated),
            },
        }
