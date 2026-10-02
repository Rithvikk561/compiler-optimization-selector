"""
moo/program_profiler.py — Deterministic IR-based Program Profiler for TOACD.

Part of Week 7 Phase 2A (Profile Data Foundation).

Characterizes a program's intermediate representation structure into an
informational profile label using deterministic, inspectable threshold rules.

ACADEMIC INTEGRITY BOUNDS:
- This is NOT a machine learning classifier.
- It does NOT compute a "confidence score", "probability", or "trust metric".
- It does NOT claim to identify arbitrary source-code semantics or algorithmic correctness.
- The profile reflects relative prominence of instruction types in LLVM IR (-O0).
- This profiler is strictly informational and does NOT affect AI Q-values or MOO selection.
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Optional, Sequence

from .xai import CANONICAL_IR_FEATURE_NAMES, format_ir_features


# ---------------------------------------------------------------------------
# Profile Label Constants
# ---------------------------------------------------------------------------
PROFILE_LOOP_ORIENTED = "loop_oriented"
PROFILE_COMPUTE_ORIENTED = "compute_oriented"
PROFILE_MEMORY_ORIENTED = "memory_oriented"
PROFILE_CALL_ORIENTED = "call_oriented"
PROFILE_MIXED = "mixed"
PROFILE_TRIVIAL = "trivial"
PROFILE_UNKNOWN = "unknown"

VALID_PROFILE_LABELS: tuple[str, ...] = (
    PROFILE_LOOP_ORIENTED,
    PROFILE_COMPUTE_ORIENTED,
    PROFILE_MEMORY_ORIENTED,
    PROFILE_CALL_ORIENTED,
    PROFILE_MIXED,
    PROFILE_TRIVIAL,
    PROFILE_UNKNOWN,
)

PROFILE_METHOD_DETERMINISTIC_RULE = "ir_heuristic_threshold"
PROFILE_METHOD_FALLBACK_ERROR = "fallback_error"

# ---------------------------------------------------------------------------
# Default Baseline Thresholds (Fallback if thresholds.json is absent)
# Derived from 75th percentile of the 40 non-trivial test programs
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLDS: dict[str, float] = {
    "trivial_instructions": 35.0,
    "branch_count": 9.0,
    "compute_count": 5.0,
    "mem_count": 45.25,
    "call_count": 2.0,
}


def get_default_thresholds_path() -> str:
    """Return the absolute path to the default thresholds.json file."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "profile_data", "thresholds.json")


def load_thresholds(json_path: Optional[str] = None) -> dict[str, float]:
    """
    Load threshold constants from JSON. Falls back safely to DEFAULT_THRESHOLDS
    if the file cannot be read or parsed.
    """
    path = json_path or get_default_thresholds_path()
    if not os.path.isfile(path):
        return dict(DEFAULT_THRESHOLDS)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        thresh_dict = data.get("thresholds", {})
        result = dict(DEFAULT_THRESHOLDS)
        for k in DEFAULT_THRESHOLDS:
            if k in thresh_dict:
                try:
                    result[k] = float(thresh_dict[k])
                except (ValueError, TypeError):
                    pass
        return result
    except Exception:
        return dict(DEFAULT_THRESHOLDS)


# ---------------------------------------------------------------------------
# ProgramProfile Data Model
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ProgramProfile:
    """
    Deterministic IR-based profile characterization for one program.

    Attributes
    ----------
    label                  : One of the VALID_PROFILE_LABELS (e.g., 'loop_oriented').
    dominant_feature       : Name of the IR feature most characteristic of this profile.
    dominant_feature_value : Raw count of the dominant feature in the program's IR.
    profile_method         : Identifier of the assignment rule used ('ir_heuristic_threshold').
    is_trivial             : True if InstructionsCount falls below the non-trivial baseline.
    all_features           : Canonical 8 IR feature counts.
    """
    label: str
    dominant_feature: str
    dominant_feature_value: float
    profile_method: str
    is_trivial: bool
    all_features: dict[str, float] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize ProgramProfile to a JSON-safe dictionary."""
        return {
            "label": self.label,
            "dominant_feature": self.dominant_feature,
            "dominant_feature_value": float(self.dominant_feature_value),
            "profile_method": self.profile_method,
            "is_trivial": bool(self.is_trivial),
            "all_features": {str(k): float(v) for k, v in self.all_features.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProgramProfile":
        """Reconstruct ProgramProfile from dictionary representation."""
        raw_feats = d.get("all_features", {})
        feats = (
            {str(k): float(v) for k, v in raw_feats.items()}
            if isinstance(raw_feats, dict)
            else {}
        )
        return cls(
            label=str(d.get("label", PROFILE_UNKNOWN)),
            dominant_feature=str(d.get("dominant_feature", "None")),
            dominant_feature_value=float(d.get("dominant_feature_value", 0.0)),
            profile_method=str(d.get("profile_method", PROFILE_METHOD_DETERMINISTIC_RULE)),
            is_trivial=bool(d.get("is_trivial", False)),
            all_features=feats,
        )

    def to_text_summary(self) -> str:
        """Return a compact human-readable summary string."""
        if self.is_trivial:
            return f"Program Profile: {self.label} (InstructionsCount: {int(self.dominant_feature_value)} < baseline)"
        return (
            f"Program Profile: {self.label} | "
            f"Dominant: {self.dominant_feature}={self.dominant_feature_value:.0f} | "
            f"Method: {self.profile_method}"
        )


# ---------------------------------------------------------------------------
# Deterministic Profiling Logic
# ---------------------------------------------------------------------------
def profile_program(
    features: Optional[dict[str, Any] | Sequence[Any]],
    thresholds: Optional[dict[str, float]] = None,
) -> ProgramProfile:
    """
    Assign an IR-derived program profile using deterministic threshold rules.

    Parameters
    ----------
    features   : Dict or sequence of the canonical 8 IR feature counts.
    thresholds : Optional custom thresholds dictionary; defaults to loaded/cached thresholds.

    Returns
    -------
    ProgramProfile instance. Never raises an uncaught exception.
    """
    thresh = thresholds if thresholds is not None else load_thresholds()

    # 1. Format and validate input features
    feats = format_ir_features(features)
    if feats is None or not feats:
        return ProgramProfile(
            label=PROFILE_UNKNOWN,
            dominant_feature="None",
            dominant_feature_value=0.0,
            profile_method=PROFILE_METHOD_FALLBACK_ERROR,
            is_trivial=False,
            all_features={},
        )

    inst_count = feats.get("InstructionsCount", 0.0)
    trivial_threshold = thresh.get("trivial_instructions", DEFAULT_THRESHOLDS["trivial_instructions"])

    # 2. Trivial program handling:
    # Straight-line code (< 35 IR instructions) lacks loops/branches/complex algorithmics.
    if inst_count < trivial_threshold:
        return ProgramProfile(
            label=PROFILE_TRIVIAL,
            dominant_feature="InstructionsCount",
            dominant_feature_value=inst_count,
            profile_method=PROFILE_METHOD_DETERMINISTIC_RULE,
            is_trivial=True,
            all_features=feats,
        )

    # 3. Non-trivial feature evaluations
    branch_count = feats.get("BranchCount", 0.0)
    math_count = feats.get("MathInstCount", 0.0)
    float_count = feats.get("FloatInstCount", 0.0)
    compute_total = math_count + float_count
    mem_count = feats.get("MemInstCount", 0.0)
    call_count = feats.get("CallInstCount", 0.0)

    # Threshold values (safe non-zero denominators)
    b_thresh = max(thresh.get("branch_count", DEFAULT_THRESHOLDS["branch_count"]), 1.0)
    c_thresh = max(thresh.get("compute_count", DEFAULT_THRESHOLDS["compute_count"]), 1.0)
    m_thresh = max(thresh.get("mem_count", DEFAULT_THRESHOLDS["mem_count"]), 1.0)
    k_thresh = max(thresh.get("call_count", DEFAULT_THRESHOLDS["call_count"]), 1.0)

    # Dimension ratios relative to 75th percentile thresholds
    loop_ratio = branch_count / b_thresh
    compute_ratio = compute_total / c_thresh
    mem_ratio = mem_count / m_thresh
    call_ratio = call_count / k_thresh

    # Dominant feature name per category
    compute_feat_name = "FloatInstCount" if float_count > math_count else "MathInstCount"

    dimensions = [
        (PROFILE_LOOP_ORIENTED, loop_ratio, "BranchCount", branch_count),
        (PROFILE_COMPUTE_ORIENTED, compute_ratio, compute_feat_name, compute_total),
        (PROFILE_MEMORY_ORIENTED, mem_ratio, "MemInstCount", mem_count),
        (PROFILE_CALL_ORIENTED, call_ratio, "CallInstCount", call_count),
    ]

    # Sort dimensions by ratio descending
    dimensions.sort(key=lambda x: x[1], reverse=True)

    top_label, top_ratio, top_feat, top_val = dimensions[0]
    second_label, second_ratio, _, _ = dimensions[1]

    # Active dimensions exceed the 75th percentile threshold (ratio >= 1.0)
    active_dimensions = [dim for dim in dimensions if dim[1] >= 1.0]

    # Rule resolution:
    if len(active_dimensions) == 0:
        # Balanced / normal: all dimensions are sub-threshold
        assigned_label = PROFILE_MIXED
    elif len(active_dimensions) == 1:
        # Unambiguous single dominant orientation
        assigned_label = top_label
    else:
        # Multiple active categories: check if top is distinct (>= 25% margin over runner-up)
        if top_ratio >= 1.25 * second_ratio:
            assigned_label = top_label
        else:
            # Co-dominant characteristics -> genuinely mixed program
            assigned_label = PROFILE_MIXED

    return ProgramProfile(
        label=assigned_label,
        dominant_feature=top_feat,
        dominant_feature_value=top_val,
        profile_method=PROFILE_METHOD_DETERMINISTIC_RULE,
        is_trivial=False,
        all_features=feats,
    )
