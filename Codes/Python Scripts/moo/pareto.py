"""
moo/pareto.py — Pareto dominance and Pareto frontier extraction
for the TOACD Multi-Objective Optimization Stage 2.

Pareto dominance (minimization)
--------------------------------
Candidate A dominates candidate B iff:
  • A is <= B for EVERY objective
  • A is <  B for AT LEAST ONE objective

When any objective value is invalid (NormalizationError sentinel, not a
finite float) that objective is EXCLUDED from the dominance comparison.
If no valid shared objectives remain, neither candidate dominates the other.

Pareto frontier
---------------
The Pareto frontier (non-dominated set) contains all candidates that are
NOT dominated by any other candidate.  No ranking or single "best" choice
is made; that is for a later weighted scalarization step.

Design principles
-----------------
* Operates on NormalizedObjectiveVector so comparisons are scale-independent.
* Preserves strategy names exactly as given — no renaming or reordering.
* Invalid objectives are skipped rather than causing a crash, and the
  skip is recorded in ParetoResult.notes so audit logs explain the behavior.
* Does NOT select a single winner.
* Does NOT apply weights.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .objectives import NormalizedObjectiveVector, ObjectiveSpec


# ---------------------------------------------------------------------------
# Dominance check
# ---------------------------------------------------------------------------

def dominates(
    a: NormalizedObjectiveVector,
    b: NormalizedObjectiveVector,
) -> bool:
    """
    Return True if candidate *a* Pareto-dominates candidate *b*.

    Dominance is evaluated only over the objectives that are valid (finite
    float) in BOTH a and b.  If there are no such shared valid objectives,
    returns False (neither dominates the other).

    All objectives are treated as minimization (lower_is_better=True).
    Maximization objectives are not supported in Stage 2.

    Parameters
    ----------
    a, b : NormalizedObjectiveVector — must share the same objectives tuple
    """
    if a.objectives != b.objectives:
        raise ValueError(
            "Cannot compare NormalizedObjectiveVectors with different objective "
            f"tuples: {[o.name for o in a.objectives]} vs "
            f"{[o.name for o in b.objectives]}"
        )

    a_better_somewhere = False
    has_valid_pair = False

    for a_val, b_val, obj in zip(a.normalized_values, b.normalized_values, a.objectives):
        a_ok = isinstance(a_val, float) and math.isfinite(a_val)
        b_ok = isinstance(b_val, float) and math.isfinite(b_val)

        if not (a_ok and b_ok):
            # Skip objectives where either side is invalid
            continue

        has_valid_pair = True

        if obj.lower_is_better:
            if a_val > b_val:
                # a is worse on this objective → cannot dominate
                return False
            if a_val < b_val:
                a_better_somewhere = True
        else:
            # Maximization — not used in Stage 2 but handled for extensibility
            if a_val < b_val:
                return False
            if a_val > b_val:
                a_better_somewhere = True

    return has_valid_pair and a_better_somewhere


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class CandidateEntry:
    """One candidate in the Pareto analysis."""
    strategy: str
    vector: NormalizedObjectiveVector
    is_dominated: bool = False
    dominated_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "is_dominated": self.is_dominated,
            "dominated_by": list(self.dominated_by),
            "vector": self.vector.to_dict(),
        }


@dataclass
class ParetoResult:
    """
    Output of Pareto frontier extraction over a set of candidates.

    Attributes
    ----------
    frontier        : list of strategy names on the Pareto frontier
                      (non-dominated candidates, in input order)
    dominated       : list of strategy names that are dominated by
                      at least one frontier member
    all_candidates  : CandidateEntry for every input candidate, in order
    objectives      : the ObjectiveSpec tuple used for comparison
    n_valid_objectives : number of objectives for which at least one valid
                         pair was found across all comparisons
    notes           : list of human-readable notes about skipped or
                      invalid objectives, empty lists, etc.
    """
    frontier: list[str]
    dominated: list[str]
    all_candidates: list[CandidateEntry]
    objectives: tuple[ObjectiveSpec, ...]
    n_valid_objectives: int
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "frontier": list(self.frontier),
            "dominated": list(self.dominated),
            "n_frontier": len(self.frontier),
            "n_dominated": len(self.dominated),
            "n_valid_objectives": self.n_valid_objectives,
            "notes": list(self.notes),
            "all_candidates": [c.to_dict() for c in self.all_candidates],
        }


# ---------------------------------------------------------------------------
# Frontier extraction
# ---------------------------------------------------------------------------

def extract_pareto_frontier(
    vectors: Sequence[NormalizedObjectiveVector],
) -> ParetoResult:
    """
    Identify the Pareto-non-dominated candidates from *vectors*.

    Algorithm: O(n²) pairwise dominance check — sufficient for the small
    number of optimization strategies used in TOACD (≤ 20).

    Parameters
    ----------
    vectors : sequence of NormalizedObjectiveVector, one per candidate.
              Strategies must be uniquely named.

    Returns
    -------
    ParetoResult — contains frontier strategy names, dominated strategy
    names, and full CandidateEntry detail for every input candidate.

    Notes
    -----
    * A single candidate is always on the frontier (by convention).
    * Two candidates with identical normalized values neither dominate each
      other; both appear on the frontier.
    * Candidates with NO valid objectives (all sentinels) are placed on the
      frontier with a note, because we cannot determine dominance.
    """
    notes: list[str] = []

    if not vectors:
        return ParetoResult(
            frontier=[],
            dominated=[],
            all_candidates=[],
            objectives=(),
            n_valid_objectives=0,
            notes=["No candidates provided to extract_pareto_frontier()"],
        )

    # Validate unique strategy names
    seen_names: set[str] = set()
    for v in vectors:
        if v.strategy in seen_names:
            raise ValueError(
                f"Duplicate strategy name {v.strategy!r} in input to "
                "extract_pareto_frontier(). Strategy names must be unique."
            )
        seen_names.add(v.strategy)

    objectives = vectors[0].objectives

    # Check that all vectors share the same objectives tuple
    for v in vectors[1:]:
        if v.objectives != objectives:
            raise ValueError(
                f"Cannot mix NormalizedObjectiveVectors with different objective "
                f"tuples in a single Pareto analysis."
            )

    n = len(vectors)
    entries = [
        CandidateEntry(strategy=v.strategy, vector=v)
        for v in vectors
    ]

    # Count valid objectives (objectives where ≥1 comparison had both sides valid)
    valid_obj_set: set[int] = set()

    # Pairwise dominance
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # Check if i dominates j; also track which objective indices fired
            a = vectors[i]
            b = vectors[j]
            a_better = False
            has_pair = False
            for idx, (av, bv, obj) in enumerate(
                zip(a.normalized_values, b.normalized_values, objectives)
            ):
                a_ok = isinstance(av, float) and math.isfinite(av)
                b_ok = isinstance(bv, float) and math.isfinite(bv)
                if not (a_ok and b_ok):
                    continue
                has_pair = True
                valid_obj_set.add(idx)
                if obj.lower_is_better:
                    if av > bv:
                        a_better = False
                        has_pair = False  # a is worse — breaks dominance
                        break
                    if av < bv:
                        a_better = True
                else:
                    if av < bv:
                        a_better = False
                        has_pair = False
                        break
                    if av > bv:
                        a_better = True

            if has_pair and a_better:
                entries[j].is_dominated = True
                entries[j].dominated_by.append(vectors[i].strategy)

    # Candidates with zero valid objectives cannot be ranked → put on frontier with note
    for entry in entries:
        if not entry.vector.is_fully_valid() and not entry.vector.valid_values():
            notes.append(
                f"Strategy {entry.strategy!r} has no valid normalized objectives "
                "and cannot participate in dominance comparisons; placed on frontier."
            )

    frontier = [e.strategy for e in entries if not e.is_dominated]
    dominated = [e.strategy for e in entries if e.is_dominated]

    if not frontier and n > 0:
        # Pathological: every candidate dominated (shouldn't happen in correct code)
        notes.append(
            "WARNING: all candidates marked dominated — this indicates a bug. "
            "Returning all as frontier."
        )
        frontier = [e.strategy for e in entries]
        dominated = []

    return ParetoResult(
        frontier=frontier,
        dominated=dominated,
        all_candidates=entries,
        objectives=objectives,
        n_valid_objectives=len(valid_obj_set),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Convenience: batch normalize + extract frontier
# ---------------------------------------------------------------------------

def pareto_from_raw(
    candidates,          # Sequence[RawObjectives]
    baseline,            # RawObjectives
    objectives=None,     # Sequence[ObjectiveSpec] | None → ALL_OBJECTIVES
) -> tuple[list["NormalizedObjectiveVector"], "ParetoResult"]:
    """
    Normalize a list of RawObjectives against *baseline* and extract the
    Pareto frontier.

    Parameters
    ----------
    candidates  : sequence of RawObjectives (one per strategy)
    baseline    : RawObjectives for the reference build
    objectives  : which objectives to use; defaults to ALL_OBJECTIVES

    Returns
    -------
    (normalized_vectors, pareto_result)
    """
    from .objectives import normalize, ALL_OBJECTIVES

    if objectives is None:
        objectives = ALL_OBJECTIVES

    vectors = [normalize(c, baseline, objectives=objectives) for c in candidates]
    result = extract_pareto_frontier(vectors)
    return vectors, result
