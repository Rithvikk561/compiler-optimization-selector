"""
moo/objectives.py — Objective definitions and baseline-relative normalization
for the TOACD Multi-Objective Optimization Stage 2.

Four minimization objectives
-----------------------------
    execution_time  — median elapsed time in seconds (lower = faster)
    energy          — estimated energy in joules (lower = less energy)
    code_size       — primary code-size metric in bytes (lower = smaller)
    carbon          — estimated carbon in grams CO2eq (lower = greener)

All four follow the same direction: lower is better.

Normalization
-------------
Each raw value is normalized against the corresponding baseline value:

    normalized = candidate_value / baseline_value

    < 1.0  →  improvement over baseline
    = 1.0  →  identical to baseline
    > 1.0  →  regression relative to baseline

Design principles
-----------------
* Zero or negative baseline values are handled explicitly — no silent NaN/inf.
* ObjectiveSpec describes what an objective IS (name, direction, unit).
* RawObjectives holds measured values for one candidate.
* NormalizedObjectiveVector holds the normalized tuple and retains raw values,
  baseline values, and the objective specs so it is fully self-describing.
* No weights are applied here.  Weighted scalarization is a later step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
# Objective specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ObjectiveSpec:
    """
    Describes a single optimization objective.

    Attributes
    ----------
    name        : canonical snake_case name used as a key throughout the MOO.
    lower_is_better : True for all four current objectives (minimization).
    unit        : human-readable unit string for display/audit logs.
    description : one-line description for diagnostics and reports.
    """
    name: str
    lower_is_better: bool
    unit: str
    description: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lower_is_better": self.lower_is_better,
            "unit": self.unit,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# The four TOACD objectives (module-level constants — no magic numbers here)
# ---------------------------------------------------------------------------

OBJECTIVE_EXECUTION_TIME = ObjectiveSpec(
    name="execution_time",
    lower_is_better=True,
    unit="seconds",
    description="Median wall-clock execution time of the compiled program",
)

OBJECTIVE_ENERGY = ObjectiveSpec(
    name="energy",
    lower_is_better=True,
    unit="joules",
    description=(
        "Estimated CPU energy consumption (elapsed_time × TDP × utilisation); "
        "marked as estimated — not a hardware measurement"
    ),
)

OBJECTIVE_CODE_SIZE = ObjectiveSpec(
    name="code_size",
    lower_is_better=True,
    unit="bytes",
    description=(
        "Primary code-size metric: PE .text section bytes via llvm-size "
        "when available, raw file size otherwise"
    ),
)

OBJECTIVE_CARBON = ObjectiveSpec(
    name="carbon",
    lower_is_better=True,
    unit="grams CO2eq",
    description=(
        "Estimated carbon footprint derived from estimated energy and grid "
        "intensity (gCO2eq/kWh); marked as estimated"
    ),
)

# Ordered tuple — the canonical objective ordering used throughout Stage 2.
ALL_OBJECTIVES: tuple[ObjectiveSpec, ...] = (
    OBJECTIVE_EXECUTION_TIME,
    OBJECTIVE_ENERGY,
    OBJECTIVE_CODE_SIZE,
    OBJECTIVE_CARBON,
)


# ---------------------------------------------------------------------------
# Raw objectives container
# ---------------------------------------------------------------------------

@dataclass
class RawObjectives:
    """
    Measured objective values for one compiled candidate.

    Any field may be None if the measurement could not be obtained.
    The corresponding normalized value will then also be None.

    Fields map directly to the four TOACD objectives:
        execution_time_s  — seconds (median from TimingStats.median_s)
        energy_j          — joules (from EnergyResult.energy_joules)
        code_size_bytes   — bytes  (from CodeSizeResult.primary_value)
        carbon_g          — grams  (from CarbonResult.carbon_grams)
    """
    strategy: str                      # e.g. "-O2" or "mem2reg,instcombine"
    execution_time_s: Optional[float]
    energy_j: Optional[float]
    code_size_bytes: Optional[int]
    carbon_g: Optional[float]

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "execution_time_s": self.execution_time_s,
            "energy_j": self.energy_j,
            "code_size_bytes": self.code_size_bytes,
            "carbon_g": self.carbon_g,
        }

    def as_values(self) -> tuple[Optional[float], ...]:
        """Return raw values in ALL_OBJECTIVES order."""
        return (
            self.execution_time_s,
            self.energy_j,
            float(self.code_size_bytes) if self.code_size_bytes is not None else None,
            self.carbon_g,
        )

    @staticmethod
    def from_measurement_result(strategy: str, mres) -> "RawObjectives":
        """
        Convenience constructor: extract objectives from a
        moo.measurement.MeasurementResult.

        Parameters
        ----------
        strategy : label string for this candidate
        mres     : moo.measurement.MeasurementResult instance
        """
        t = mres.timing.median_s if mres.timing else None
        e = mres.energy.energy_joules if mres.energy else None
        cs = mres.code_size.primary_value if mres.code_size else None
        co = mres.carbon.carbon_grams if mres.carbon else None
        return RawObjectives(
            strategy=strategy,
            execution_time_s=t,
            energy_j=e,
            code_size_bytes=cs,
            carbon_g=co,
        )


# ---------------------------------------------------------------------------
# Normalization error enum
# ---------------------------------------------------------------------------

class NormalizationError(str):
    """
    Sentinel string used instead of NaN/inf when normalization is
    mathematically invalid.  Stored in normalized_values as a string; callers
    must check type before using the value in dominance comparisons.
    """
    ZERO_BASELINE = "zero_baseline"
    NEGATIVE_BASELINE = "negative_baseline"
    MISSING_RAW = "missing_raw"
    MISSING_BASELINE = "missing_baseline"


# ---------------------------------------------------------------------------
# Normalized objective vector
# ---------------------------------------------------------------------------

@dataclass
class NormalizedObjectiveVector:
    """
    A fully self-describing normalized objective vector for one candidate.

    Attributes
    ----------
    strategy        : strategy label
    objectives      : ordered tuple of ObjectiveSpec (matches ALL_OBJECTIVES)
    raw_values      : raw measured values in objectives order (may contain None)
    baseline_values : baseline raw values in objectives order (may contain None)
    normalized_values : normalized ratios or NormalizationError sentinel strings.
                        normalized_values[i] = raw_values[i] / baseline_values[i]
                        or a NormalizationError string if invalid.
    normalization_notes : per-objective human-readable note when a sentinel
                          is used (empty string = no issue)
    """
    strategy: str
    objectives: tuple[ObjectiveSpec, ...]
    raw_values: tuple[Optional[float], ...]
    baseline_values: tuple[Optional[float], ...]
    normalized_values: tuple               # float | NormalizationError per slot
    normalization_notes: tuple[str, ...]   # same length as objectives

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    def is_fully_valid(self) -> bool:
        """True if every normalized value is a finite float (no sentinels)."""
        return all(isinstance(v, float) and math.isfinite(v)
                   for v in self.normalized_values)

    def valid_mask(self) -> tuple[bool, ...]:
        """Per-objective bool: True = normalized value is a valid finite float."""
        return tuple(
            isinstance(v, float) and math.isfinite(v)
            for v in self.normalized_values
        )

    def valid_values(self) -> list[float]:
        """Return only the valid (finite float) normalized values."""
        return [v for v in self.normalized_values
                if isinstance(v, float) and math.isfinite(v)]

    def objective_index(self, name: str) -> int:
        """Return the index of objective *name* in objectives tuple."""
        for i, o in enumerate(self.objectives):
            if o.name == name:
                return i
        raise KeyError(f"Objective {name!r} not found in this vector")

    def to_dict(self) -> dict:
        obj_rows = []
        for i, obj in enumerate(self.objectives):
            obj_rows.append({
                "objective": obj.to_dict(),
                "raw_value": self.raw_values[i],
                "baseline_value": self.baseline_values[i],
                "normalized_value": (
                    self.normalized_values[i]
                    if isinstance(self.normalized_values[i], float)
                    else str(self.normalized_values[i])
                ),
                "note": self.normalization_notes[i],
            })
        return {
            "strategy": self.strategy,
            "is_fully_valid": self.is_fully_valid(),
            "objectives": obj_rows,
        }


# ---------------------------------------------------------------------------
# Normalization engine
# ---------------------------------------------------------------------------

def _normalize_one(
    raw: Optional[float],
    baseline: Optional[float],
    obj_name: str,
) -> tuple[float | str, str]:
    """
    Normalize a single objective value against its baseline.

    Returns (normalized_value, note).
    normalized_value is a float on success, or a NormalizationError string.
    """
    if raw is None:
        return (
            NormalizationError.MISSING_RAW,
            f"{obj_name}: raw value is None (measurement unavailable)",
        )
    if baseline is None:
        return (
            NormalizationError.MISSING_BASELINE,
            f"{obj_name}: baseline value is None (baseline measurement unavailable)",
        )
    if baseline < 0:
        return (
            NormalizationError.NEGATIVE_BASELINE,
            f"{obj_name}: baseline={baseline} is negative; normalization undefined",
        )
    if baseline == 0.0:
        return (
            NormalizationError.ZERO_BASELINE,
            (
                f"{obj_name}: baseline=0; division undefined. "
                "Raw value is still retained. Consider using absolute values instead."
            ),
        )
    ratio = raw / baseline
    return ratio, ""


def normalize(
    candidate: RawObjectives,
    baseline: RawObjectives,
    objectives: Sequence[ObjectiveSpec] = ALL_OBJECTIVES,
) -> NormalizedObjectiveVector:
    """
    Normalize *candidate* objective values against *baseline*.

    For each objective:
        normalized = candidate_value / baseline_value

    Interpretation (lower_is_better objectives):
        < 1.0 → candidate improved over baseline
        = 1.0 → identical to baseline
        > 1.0 → candidate regressed relative to baseline

    Zero or missing baseline values produce a NormalizationError sentinel
    rather than NaN or inf.  The sentinel is a string, so callers can detect
    and skip invalid objectives during dominance comparisons.

    Parameters
    ----------
    candidate  : RawObjectives for the strategy being evaluated
    baseline   : RawObjectives for the reference (e.g. -O0 unoptimized) build
    objectives : ordered sequence of ObjectiveSpec; defaults to ALL_OBJECTIVES

    Returns
    -------
    NormalizedObjectiveVector — fully self-describing, retains raw and
    baseline values alongside normalized values.
    """
    objectives = tuple(objectives)
    cand_vals = candidate.as_values()
    base_vals = baseline.as_values()

    # Align to the objectives ordering
    # as_values() returns in ALL_OBJECTIVES order; if a custom subset is given
    # we need to map by index.
    if objectives == ALL_OBJECTIVES:
        c_seq = cand_vals
        b_seq = base_vals
    else:
        # Map by position in ALL_OBJECTIVES
        full_c = dict(zip([o.name for o in ALL_OBJECTIVES], cand_vals))
        full_b = dict(zip([o.name for o in ALL_OBJECTIVES], base_vals))
        c_seq = tuple(full_c.get(o.name) for o in objectives)
        b_seq = tuple(full_b.get(o.name) for o in objectives)

    norm_vals = []
    notes = []
    for obj, cv, bv in zip(objectives, c_seq, b_seq):
        n, note = _normalize_one(cv, bv, obj.name)
        norm_vals.append(n)
        notes.append(note)

    return NormalizedObjectiveVector(
        strategy=candidate.strategy,
        objectives=objectives,
        raw_values=tuple(c_seq),
        baseline_values=tuple(b_seq),
        normalized_values=tuple(norm_vals),
        normalization_notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Interpretation helper
# ---------------------------------------------------------------------------

def interpret_normalized(value: float | str, threshold: float = 0.001) -> str:
    """
    Return a human-readable interpretation of a single normalized value.

    Parameters
    ----------
    value     : normalized ratio (float) or NormalizationError string
    threshold : values within this fraction of 1.0 are reported as "equal"
                (default 0.1% to account for measurement noise)
    """
    if not isinstance(value, float):
        return f"invalid ({value})"
    if not math.isfinite(value):
        return f"non-finite ({value})"
    if abs(value - 1.0) <= threshold:
        return f"equal to baseline ({value:.4f})"
    if value < 1.0:
        pct = (1.0 - value) * 100
        return f"improved {pct:.1f}% over baseline ({value:.4f})"
    pct = (value - 1.0) * 100
    return f"regressed {pct:.1f}% vs baseline ({value:.4f})"
