"""
moo/security/compare.py — Compare baseline ModuleSinks against optimized ModuleSinks.

Classifies what happened to each security sink across optimization levels:
- PRESERVED: Guard preserved with conditional semantics intact.
- MERGED: Multiple baseline sinks collapsed into one optimized sink (tail merge).
- FOLDED: Guard condition constant-folded; sink reached unconditionally.
- ELIMINATED: Confirmed eliminated only via rigorous provenance negative search.
- UNKNOWN: Transformation cannot be established safely. Never guess.

Guarantees:
1. Never infers ELIMINATED merely because a baseline sink is absent.
2. Dead baseline sinks (provably_dead_at_baseline) are excluded in Phase 1
   and classified as UNKNOWN (dead_at_baseline) so they never create regressions.
3. Provenance Negative Search requires all 8 conditions to emit ELIMINATED.
4. Tri-state is_guarded: None is never treated as False or True.
5. Deterministic output: sorted by (function_name, ordinal).
6. Never raises exceptions to caller.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import GuardSink, GuardStatus, ModuleSinks, Provenance, SinkClass


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class SinkMatch:
    """
    The correspondence decision for a single baseline GuardSink.

    baseline_sink_id: module-local ID of the baseline GuardSink.
    status: GuardStatus classification.
    optimized_sink_ids: module-local IDs of matched optimized sinks (empty if none).
    confidence: "HIGH" | "MEDIUM" | "LOW".
    match_method: identifier of the matching rule or phase that fired.
    notes: diagnostic explanations for the decision.
    """
    baseline_sink_id: str
    status: GuardStatus
    optimized_sink_ids: list[str] = dataclasses.field(default_factory=list)
    confidence: str = "LOW"
    match_method: str = ""
    notes: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_sink_id": self.baseline_sink_id,
            "status": self.status.value if isinstance(self.status, GuardStatus) else str(self.status),
            "optimized_sink_ids": list(self.optimized_sink_ids),
            "confidence": self.confidence,
            "match_method": self.match_method,
            "notes": list(self.notes),
        }


@dataclasses.dataclass
class CompareResult:
    """
    Full output of a baseline-vs-optimized comparison pass.

    baseline_path: path to baseline IR file if known.
    optimized_path: path to optimized IR file if known.
    sink_matches: one SinkMatch per baseline sink (deterministic order).
    unmatched_optimized_ids: optimized sinks not claimed by any baseline sink.
    comparison_warnings: diagnostics from the comparison process.
    compare_ok: False if either input had parse_ok=False.
    """
    baseline_path: Optional[str] = None
    optimized_path: Optional[str] = None
    sink_matches: list[SinkMatch] = dataclasses.field(default_factory=list)
    unmatched_optimized_ids: list[str] = dataclasses.field(default_factory=list)
    comparison_warnings: list[str] = dataclasses.field(default_factory=list)
    compare_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_path": self.baseline_path,
            "optimized_path": self.optimized_path,
            "sink_matches": [m.to_dict() for m in self.sink_matches],
            "unmatched_optimized_ids": list(self.unmatched_optimized_ids),
            "comparison_warnings": list(self.comparison_warnings),
            "compare_ok": self.compare_ok,
        }


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _sort_sinks(sinks: list[GuardSink]) -> list[GuardSink]:
    """Sort sinks deterministically by (function_name, ordinal)."""
    return sorted(sinks, key=lambda s: (s.function_name, s.ordinal))


def _evaluate_eliminated(
    b: GuardSink,
    baseline: ModuleSinks,
    optimized: ModuleSinks,
) -> tuple[bool, str]:
    """
    Evaluate whether baseline sink `b` can be safely classified as ELIMINATED.

    Requires all 8 non-negotiable conditions from architecture document:
    1. b.provably_dead_at_baseline is False
    2. baseline.provenance_available is True
    3. optimized.provenance_available is True
    4. b.origin_function is not None
    5. b.source_line is not None
    6. optimized.parse_ok is True
    7. Exhaustive negative search over ALL optimized.sinks finds zero sinks
       matching (origin_function, source_line, sink_class, target_symbol).
    8. No optimized sink exists with matching (sink_class, target_symbol)
       and origin_function is None.
    """
    # 1. b.provably_dead_at_baseline is False
    if b.provably_dead_at_baseline:
        return False, "baseline sink was provably dead at baseline"

    # 2. baseline.provenance_available is True
    if not baseline.provenance_available:
        return False, "baseline provenance unavailable"

    # 3. optimized.provenance_available is True
    if not optimized.provenance_available:
        return False, "optimized provenance unavailable"

    # 4. b.origin_function is not None
    if b.origin_function is None:
        return False, "baseline sink origin_function is None"

    # 5. b.source_line is not None
    if b.source_line is None:
        return False, "baseline sink source_line is None"

    # 6. baseline.parse_ok and optimized.parse_ok must both be True
    if not baseline.parse_ok:
        return False, "baseline parse_ok is False"
    if not optimized.parse_ok:
        return False, "optimized parse_ok is False"

    # 7. Exhaustive negative search over all optimized.sinks
    for o in optimized.sinks:
        if (
            o.origin_function == b.origin_function
            and o.source_line == b.source_line
            and o.sink_class == b.sink_class
            and o.target_symbol == b.target_symbol
        ):
            return False, f"found matching sink '{o.sink_id}' in optimized module"

    # 8. No ambiguous optimized sink with missing provenance
    for o in optimized.sinks:
        if (
            o.sink_class == b.sink_class
            and o.target_symbol == b.target_symbol
            and o.origin_function is None
        ):
            return False, f"ambiguous optimized sink '{o.sink_id}' with missing provenance"

    class_str = b.sink_class.value if isinstance(b.sink_class, SinkClass) else str(b.sink_class)
    return True, (
        f"Sink ({b.origin_function}:{b.source_line}, {class_str}, "
        f"{b.target_symbol}) confirmed eliminated via exhaustive provenance search."
    )


# ---------------------------------------------------------------------------
# Main Comparison Engine
# ---------------------------------------------------------------------------

def compare_sinks(
    baseline: ModuleSinks,
    optimized: ModuleSinks,
) -> CompareResult:
    """
    Compare baseline ModuleSinks against optimized ModuleSinks.

    Executes a 6-phase waterfall:
    - Phase 0: Pre-conditions & completeness checks
    - Phase 1: Dead-baseline removal (provably_dead_at_baseline -> UNKNOWN)
    - Phase 2: Provenance matching (source-level identity)
    - Phase 3: Canonical text + class + symbol matching
    - Phase 4: Weak matching (same function or inlining-aware)
    - Phase 5: Classification (PRESERVED, MERGED, FOLDED, ELIMINATED, UNKNOWN)
    - Phase 6: Unclaimed optimized sinks recording

    Never raises. Returns deterministic CompareResult.
    """
    try:
        return _compare_sinks_impl(baseline, optimized)
    except Exception as exc:
        try:
            b_sinks = _sort_sinks(list(getattr(baseline, "sinks", [])))
        except Exception:
            b_sinks = []

        fallback_matches = [
            SinkMatch(
                baseline_sink_id=getattr(s, "sink_id", "unknown_sink"),
                status=GuardStatus.UNKNOWN,
                optimized_sink_ids=[],
                confidence="LOW",
                match_method="exception_fallback",
                notes=[f"Exception occurred during comparison: {type(exc).__name__}: {exc}"],
            )
            for s in b_sinks
        ]

        try:
            o_sinks = [o.sink_id for o in _sort_sinks(list(getattr(optimized, "sinks", [])))]
        except Exception:
            o_sinks = []

        return CompareResult(
            baseline_path=getattr(baseline, "ir_path", None),
            optimized_path=getattr(optimized, "ir_path", None),
            sink_matches=fallback_matches,
            unmatched_optimized_ids=o_sinks,
            comparison_warnings=[f"Comparison failed with exception: {type(exc).__name__}: {exc}"],
            compare_ok=False,
        )


def _compare_sinks_impl(
    baseline: ModuleSinks,
    optimized: ModuleSinks,
) -> CompareResult:
    # -----------------------------------------------------------------------
    # Phase 0: Pre-conditions & Completeness
    # -----------------------------------------------------------------------
    warnings: list[str] = []
    for w in baseline.parse_warnings:
        if w not in warnings:
            warnings.append(w)
    for w in optimized.parse_warnings:
        if w not in warnings:
            warnings.append(w)

    compare_ok = bool(baseline.parse_ok and optimized.parse_ok)
    if not compare_ok:
        msg = "Input parse_ok=False — results may be incomplete."
        if msg not in warnings:
            warnings.append(msg)

    sorted_baseline = _sort_sinks(baseline.sinks)
    sorted_optimized = _sort_sinks(optimized.sinks)

    # -----------------------------------------------------------------------
    # Phase 1: Dead-Baseline Removal
    # -----------------------------------------------------------------------
    dead_baseline_matches: dict[str, SinkMatch] = {}
    active_baseline: list[GuardSink] = []

    for b in sorted_baseline:
        if b.provably_dead_at_baseline:
            dead_baseline_matches[b.sink_id] = SinkMatch(
                baseline_sink_id=b.sink_id,
                status=GuardStatus.UNKNOWN,
                optimized_sink_ids=[],
                confidence="HIGH" if compare_ok else "LOW",
                match_method="dead_at_baseline",
                notes=["Sink was provably dead at baseline (constant-fold reachability). Skipped for regression analysis."],
            )
        else:
            active_baseline.append(b)

    # Tracking candidate matches for active baseline sinks
    matched_b_to_o: dict[str, list[GuardSink]] = {b.sink_id: [] for b in active_baseline}
    match_metadata: dict[str, tuple[str, str]] = {}
    ambiguous_candidates: dict[str, list[str]] = {}

    # -----------------------------------------------------------------------
    # Phase 2: Provenance-Based Matching
    # -----------------------------------------------------------------------
    if baseline.provenance_available and optimized.provenance_available:
        for b in active_baseline:
            if b.origin_function is not None and b.source_line is not None:
                cands = [
                    o for o in sorted_optimized
                    if o.origin_function == b.origin_function
                    and o.source_line == b.source_line
                    and o.sink_class == b.sink_class
                    and o.target_symbol == b.target_symbol
                ]
                if len(cands) == 1:
                    matched_b_to_o[b.sink_id] = [cands[0]]
                    match_metadata[b.sink_id] = ("HIGH", "provenance")
                elif len(cands) > 1:
                    ambiguous_candidates[b.sink_id] = [o.sink_id for o in cands]
                    match_metadata[b.sink_id] = ("LOW", "ambiguous_multi_candidate")

    claimed_in_p2 = {o.sink_id for b_id, o_list in matched_b_to_o.items() for o in o_list}

    # -----------------------------------------------------------------------
    # Phase 3: Canonical-Text + Class + Symbol Matching
    # -----------------------------------------------------------------------
    unmatched_p3 = [b for b in active_baseline if not matched_b_to_o[b.sink_id]]
    for b in unmatched_p3:
        if not b.canonical_text:
            continue
        cands = [
            o for o in sorted_optimized
            if o.sink_id not in claimed_in_p2
            and o.canonical_text
            and o.canonical_text == b.canonical_text
            and o.sink_class == b.sink_class
            and o.target_symbol == b.target_symbol
        ]
        # Prefer candidates within the same function
        same_fn_cands = [o for o in cands if o.function_name == b.function_name]
        target_cands = same_fn_cands if same_fn_cands else cands

        if len(target_cands) == 1:
            matched_b_to_o[b.sink_id] = [target_cands[0]]
            match_metadata[b.sink_id] = ("HIGH", "canonical_text")
            ambiguous_candidates.pop(b.sink_id, None)
        elif len(target_cands) > 1:
            ambiguous_candidates[b.sink_id] = [o.sink_id for o in target_cands]

    # -----------------------------------------------------------------------
    # Phase 4: Weak Matching (same function or inlining context)
    # -----------------------------------------------------------------------
    claimed_so_far = {o.sink_id for b_id, o_list in matched_b_to_o.items() for o in o_list}
    unmatched_p4 = [b for b in active_baseline if not matched_b_to_o[b.sink_id]]

    for b in unmatched_p4:
        # 4a: Same function, same class, same symbol
        c_4a = [
            o for o in sorted_optimized
            if o.function_name == b.function_name
            and o.sink_class == b.sink_class
            and o.target_symbol == b.target_symbol
            and o.sink_id not in claimed_so_far
        ]
        if len(c_4a) == 1:
            matched_b_to_o[b.sink_id] = [c_4a[0]]
            match_metadata[b.sink_id] = ("MEDIUM", "same_function_weak")
            ambiguous_candidates.pop(b.sink_id, None)
            claimed_so_far.add(c_4a[0].sink_id)
            continue
        elif len(c_4a) > 1:
            ambiguous_candidates[b.sink_id] = [o.sink_id for o in c_4a]
            match_metadata[b.sink_id] = ("LOW", "ambiguous_multi_candidate")
            continue

        # 4b: Inlining-aware cross-function
        if b.inlined is not True:
            c_4b = [
                o for o in sorted_optimized
                if o.provenance == Provenance.INLINED
                and o.origin_function == b.function_name
                and o.sink_class == b.sink_class
                and o.target_symbol == b.target_symbol
                and o.sink_id not in claimed_so_far
            ]
            if len(c_4b) == 1:
                matched_b_to_o[b.sink_id] = [c_4b[0]]
                match_metadata[b.sink_id] = ("MEDIUM", "inlined_cross_function")
                ambiguous_candidates.pop(b.sink_id, None)
                claimed_so_far.add(c_4b[0].sink_id)
            elif len(c_4b) > 1:
                ambiguous_candidates[b.sink_id] = [o.sink_id for o in c_4b]
                match_metadata[b.sink_id] = ("LOW", "ambiguous_multi_candidate")

    # -----------------------------------------------------------------------
    # Phase 5: Classification
    # -----------------------------------------------------------------------
    # Count how many baseline sinks each optimized sink is paired with
    opt_match_counts: dict[str, list[str]] = {}
    for b_id, o_list in matched_b_to_o.items():
        for o in o_list:
            opt_match_counts.setdefault(o.sink_id, []).append(b_id)

    active_matches: dict[str, SinkMatch] = {}

    for b in active_baseline:
        matched_os = matched_b_to_o.get(b.sink_id, [])

        if len(matched_os) == 0:
            # Case A: Zero optimized sinks matched
            if b.sink_id in ambiguous_candidates:
                cands_str = ", ".join(ambiguous_candidates[b.sink_id])
                method = match_metadata.get(b.sink_id, ("LOW", "ambiguous_multi_candidate"))[1]
                active_matches[b.sink_id] = SinkMatch(
                    baseline_sink_id=b.sink_id,
                    status=GuardStatus.UNKNOWN,
                    optimized_sink_ids=[],
                    confidence="LOW",
                    match_method=method,
                    notes=[f"Multiple candidate matches found ({cands_str}); cannot disambiguate safely."],
                )
            else:
                is_eliminated, reason_or_note = _evaluate_eliminated(b, baseline, optimized)
                if is_eliminated:
                    active_matches[b.sink_id] = SinkMatch(
                        baseline_sink_id=b.sink_id,
                        status=GuardStatus.ELIMINATED,
                        optimized_sink_ids=[],
                        confidence="HIGH",
                        match_method="provenance_negative_search",
                        notes=[reason_or_note],
                    )
                else:
                    if b.inlined is True or b.provenance == Provenance.INLINED:
                        note = "Inlined baseline sink had no optimized counterpart. Cross-optimization inlining context shift prevents safe classification."
                        method = "inlined_baseline_unmatched"
                    else:
                        note = f"No optimized sink could be safely matched ({reason_or_note}). Cannot determine fate. Not classifying as ELIMINATED."
                        method = "unmatched_fallback"

                    active_matches[b.sink_id] = SinkMatch(
                        baseline_sink_id=b.sink_id,
                        status=GuardStatus.UNKNOWN,
                        optimized_sink_ids=[],
                        confidence="LOW",
                        match_method=method,
                        notes=[note],
                    )

        elif len(matched_os) == 1:
            o = matched_os[0]
            conf, method = match_metadata.get(b.sink_id, ("HIGH", "unknown"))
            matched_baseline_ids = opt_match_counts.get(o.sink_id, [])

            if len(matched_baseline_ids) > 1:
                # Case C: Multiple baseline sinks map to one optimized sink -> MERGED
                active_matches[b.sink_id] = SinkMatch(
                    baseline_sink_id=b.sink_id,
                    status=GuardStatus.MERGED,
                    optimized_sink_ids=[o.sink_id],
                    confidence=conf,
                    match_method=f"{method}_merged" if method else "merged",
                    notes=[
                        f"Multiple baseline sinks ({', '.join(sorted(matched_baseline_ids))}) correspond to one optimized sink '{o.sink_id}' (tail merge or other structural transformation). Security effect may be preserved."
                    ],
                )
            else:
                # Case B: Exactly 1 baseline sink to 1 optimized sink
                b_guarded = b.is_guarded
                o_guarded = o.is_guarded

                if b_guarded is True and o_guarded is False:
                    status = GuardStatus.FOLDED
                    notes = ["Guard condition was folded away by optimizer; security sink is unconditionally reached."]
                elif b_guarded is None and o_guarded is False:
                    status = GuardStatus.UNKNOWN
                    conf = "LOW"
                    notes = ["Guardedness unknown at baseline while unconditional at optimized; cannot safely classify as FOLDED or PRESERVED."]
                elif b_guarded is True and o_guarded is None:
                    status = GuardStatus.UNKNOWN
                    conf = "LOW"
                    notes = ["Guardedness unknown at optimized; cannot confirm conditionality is preserved."]
                elif b_guarded is None and o_guarded is None:
                    status = GuardStatus.PRESERVED
                    conf = "LOW"
                    notes = ["Guardedness unknown on both sides; sink preserved."]
                elif b_guarded is False and o_guarded is None:
                    status = GuardStatus.PRESERVED
                    conf = "LOW"
                    notes = ["Optimized guardedness unknown; sink preserved from unconditional baseline."]
                elif b_guarded is None and o_guarded is True:
                    status = GuardStatus.PRESERVED
                    conf = "LOW"
                    notes = ["Baseline guardedness unknown; sink preserved and conditionally guarded in optimized build."]
                elif b_guarded is False and o_guarded is False:
                    status = GuardStatus.PRESERVED
                    notes = ["Unconditional guard sink preserved."]
                elif b_guarded is True and o_guarded is True:
                    status = GuardStatus.PRESERVED
                    notes = ["Conditionally guarded sink preserved."]
                else:
                    status = GuardStatus.PRESERVED
                    notes = ["Guard sink preserved in optimized build."]

                active_matches[b.sink_id] = SinkMatch(
                    baseline_sink_id=b.sink_id,
                    status=status,
                    optimized_sink_ids=[o.sink_id],
                    confidence=conf,
                    match_method=method,
                    notes=notes,
                )

        else:
            # 1 baseline matched multiple optimized sinks
            cands_str = ", ".join(o.sink_id for o in matched_os)
            active_matches[b.sink_id] = SinkMatch(
                baseline_sink_id=b.sink_id,
                status=GuardStatus.UNKNOWN,
                optimized_sink_ids=[o.sink_id for o in matched_os],
                confidence="LOW",
                match_method="ambiguous_multi_candidate",
                notes=[f"Baseline sink matched multiple optimized sinks ({cands_str}); ambiguous transformation."],
            )

    # -----------------------------------------------------------------------
    # Assemble Final Output
    # -----------------------------------------------------------------------
    sink_matches: list[SinkMatch] = []
    for b in sorted_baseline:
        if b.sink_id in dead_baseline_matches:
            match = dead_baseline_matches[b.sink_id]
        else:
            match = active_matches[b.sink_id]

        if not compare_ok:
            match.confidence = "LOW"

        sink_matches.append(match)

    # Phase 6: Unclaimed Optimized Sinks
    claimed_opt_ids: set[str] = set()
    for m in sink_matches:
        for oid in m.optimized_sink_ids:
            claimed_opt_ids.add(oid)

    unmatched_opt_ids = [
        o.sink_id for o in sorted_optimized
        if o.sink_id not in claimed_opt_ids
    ]

    for b_id, cands in sorted(ambiguous_candidates.items()):
        msg = f"Ambiguous correspondence for baseline sink '{b_id}': multiple candidates [{', '.join(cands)}]"
        if msg not in warnings:
            warnings.append(msg)

    return CompareResult(
        baseline_path=baseline.ir_path,
        optimized_path=optimized.ir_path,
        sink_matches=sink_matches,
        unmatched_optimized_ids=unmatched_opt_ids,
        comparison_warnings=warnings,
        compare_ok=compare_ok,
    )
