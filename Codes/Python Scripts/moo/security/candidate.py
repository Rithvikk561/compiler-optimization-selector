"""
moo.security.candidate — Security validation and verdict computation for optimization candidates.

Evaluates baseline IR vs candidate IR using existing sink discovery and comparison tools.
Maps sink comparison results to CandidateSecurity verdicts according to precedence rules:
  ELIMINATED > UNKNOWN > REDUCED > PRESERVED > NOT_APPLICABLE
"""

from __future__ import annotations

import os
from typing import Optional

from .models import (
    CandidateSecurity,
    CandidateVerdict,
    GuardAssessment,
    GuardStatus,
    ModuleSinks,
)
from .sinks import analyze_module_sinks
from .compare import compare_sinks, CompareResult


def compute_candidate_verdict(
    guard_assessments: list[GuardAssessment],
    baseline_sink_count: int,
    candidate_sink_count: int,
    *,
    compare_ok: bool = True,
) -> CandidateVerdict:
    """
    Compute overall CandidateVerdict according to the approved precedence:
      ELIMINATED > UNKNOWN > REDUCED > PRESERVED

    If baseline has 0 sinks, verdict is NOT_APPLICABLE.
    If comparison or IR parsing failed (compare_ok is False), verdict is ERROR or UNKNOWN.
    """
    if not compare_ok:
        return CandidateVerdict.ERROR if baseline_sink_count == 0 else CandidateVerdict.UNKNOWN

    if baseline_sink_count == 0:
        return CandidateVerdict.NOT_APPLICABLE

    statuses = [a.status for a in guard_assessments]

    if any(s == GuardStatus.ELIMINATED for s in statuses):
        return CandidateVerdict.ELIMINATED

    if any(s == GuardStatus.UNKNOWN for s in statuses):
        return CandidateVerdict.UNKNOWN

    if any(s in (GuardStatus.MERGED, GuardStatus.FOLDED) for s in statuses):
        return CandidateVerdict.REDUCED

    if all(s == GuardStatus.PRESERVED for s in statuses):
        return CandidateVerdict.PRESERVED

    return CandidateVerdict.UNKNOWN


def evaluate_candidate_security(
    strategy_name: str,
    baseline_ir_path: Optional[str],
    candidate_ir_path: Optional[str],
    *,
    baseline_ir_text: Optional[str] = None,
    candidate_ir_text: Optional[str] = None,
) -> CandidateSecurity:
    """
    Run full security evaluation of candidate IR against baseline IR.
    Accepts file paths or raw IR text.
    Never raises an uncaught exception (fails closed to UNKNOWN/ERROR).
    """
    try:
        # Step 1: Discover sinks in baseline
        if baseline_ir_path and os.path.isfile(baseline_ir_path):
            base_sinks = analyze_module_sinks(baseline_ir_path, is_path=True)
        elif baseline_ir_text is not None:
            base_sinks = analyze_module_sinks(baseline_ir_text, is_path=False)
        else:
            return CandidateSecurity(
                strategy_name=strategy_name,
                verdict=CandidateVerdict.ERROR,
                warnings=["Baseline IR missing or inaccessible"],
            )

        # Step 2: Discover sinks in candidate
        if candidate_ir_path and os.path.isfile(candidate_ir_path):
            cand_sinks = analyze_module_sinks(candidate_ir_path, is_path=True)
        elif candidate_ir_text is not None:
            cand_sinks = analyze_module_sinks(candidate_ir_text, is_path=False)
        else:
            return CandidateSecurity(
                strategy_name=strategy_name,
                verdict=CandidateVerdict.ERROR,
                baseline_sink_count=len(base_sinks.sinks),
                warnings=["Candidate IR missing or compilation failed"],
            )

        # Step 3: Compare sinks
        cmp_result: CompareResult = compare_sinks(base_sinks, cand_sinks)

        # Step 4: Map matches to GuardAssessments
        guard_assessments: list[GuardAssessment] = []
        n_preserved = 0
        n_eliminated = 0
        n_merged = 0
        n_folded = 0

        for match in cmp_result.sink_matches:
            st = match.status
            if st == GuardStatus.PRESERVED:
                n_preserved += 1
            elif st == GuardStatus.ELIMINATED:
                n_eliminated += 1
            elif st == GuardStatus.MERGED:
                n_merged += 1
            elif st == GuardStatus.FOLDED:
                n_folded += 1

            guard_assessments.append(
                GuardAssessment(
                    sink_id=match.baseline_sink_id,
                    status=match.status,
                    details=f"match_method={match.match_method}, confidence={match.confidence}",
                    notes=list(match.notes),
                )
            )

        # Step 5: Compute verdict
        verdict = compute_candidate_verdict(
            guard_assessments,
            baseline_sink_count=len(base_sinks.sinks),
            candidate_sink_count=len(cand_sinks.sinks),
            compare_ok=cmp_result.compare_ok and base_sinks.parse_ok and cand_sinks.parse_ok,
        )

        all_warnings = list(cmp_result.comparison_warnings)
        if not base_sinks.parse_ok:
            all_warnings.append("Baseline IR had parse warnings/incomplete define count")
        if not cand_sinks.parse_ok:
            all_warnings.append("Candidate IR had parse warnings/incomplete define count")

        return CandidateSecurity(
            strategy_name=strategy_name,
            verdict=verdict,
            baseline_sink_count=len(base_sinks.sinks),
            candidate_sink_count=len(cand_sinks.sinks),
            preserved_sinks=n_preserved,
            eliminated_sinks=n_eliminated,
            merged_sinks=n_merged,
            folded_sinks=n_folded,
            guard_assessments=guard_assessments,
            warnings=all_warnings,
            notes=[f"Evaluated {len(guard_assessments)} baseline guard sinks"],
        )

    except Exception as exc:
        return CandidateSecurity(
            strategy_name=strategy_name,
            verdict=CandidateVerdict.ERROR,
            warnings=[f"Security evaluation failed with exception: {exc}"],
        )
