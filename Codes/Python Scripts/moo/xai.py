"""
moo/xai.py — Explainable AI (XAI) foundation for TOACD.

Phase 1 (Week 7): Exposes the existing AI model outputs (9 Q-values),
input IR feature counts (8 canonical features), Pareto filtering decisions,
and selection rationale from DecisionTrace in a clean, JSON-safe structure.

ACADEMIC DEFICIENCY BOUNDS:
This module explains what the model DID, not why the model is correct.
It does NOT compute confidence scores, feature importance, causal attributions,
or reliability estimates, as the current model has limited training evidence.
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Optional, Sequence, Any


# ---------------------------------------------------------------------------
# Canonical IR Feature Schema (matches ml_optimizer.py CompilerEnv)
# ---------------------------------------------------------------------------
CANONICAL_IR_FEATURE_NAMES: tuple[str, ...] = (
    "BasicBlocksCount",
    "InstructionsCount",
    "BranchCount",
    "MemInstCount",
    "MathInstCount",
    "FloatInstCount",
    "VectorInstCount",
    "CallInstCount",
)


def format_ir_features(
    features: Optional[dict[str, Any] | Sequence[Any]]
) -> Optional[dict[str, float]]:
    """
    Format raw feature values into a canonical {feature_name: float} dictionary.

    Parameters
    ----------
    features : dict mapping feature names to numbers, or sequence of numbers
               ordered according to CANONICAL_IR_FEATURE_NAMES.

    Returns
    -------
    dict[str, float] or None if features is None.
    """
    if features is None:
        return None

    if isinstance(features, dict):
        result = {}
        # Keep canonical features in canonical order if present
        for name in CANONICAL_IR_FEATURE_NAMES:
            if name in features:
                val = features[name]
                try:
                    result[name] = float(val)
                except (ValueError, TypeError):
                    result[name] = 0.0
        # Include any extra keys for forward compatibility
        for k, v in features.items():
            if k not in result:
                try:
                    result[str(k)] = float(v)
                except (ValueError, TypeError):
                    result[str(k)] = 0.0
        return result

    # Sequence / array input
    if hasattr(features, "__iter__"):
        result = {}
        for idx, val in enumerate(features):
            if idx < len(CANONICAL_IR_FEATURE_NAMES):
                name = CANONICAL_IR_FEATURE_NAMES[idx]
            else:
                name = f"Feature_{idx}"
            try:
                result[name] = float(val)
            except (ValueError, TypeError):
                result[name] = 0.0
        return result

    return None


# ---------------------------------------------------------------------------
# XAIResult Dataclass
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class XAIResult:
    """
    Structured explainability report for one optimization decision.

    Attributes
    ----------
    ai_top_choice                : Strategy with the highest Q-value from the AI model
    ai_top_q                     : Model output Q-value for ai_top_choice
    q_rank_full                  : Full descending ranking of (strategy_name, q_value)
    ir_features                  : Canonical 8 IR feature counts from unoptimized IR (or None)
    pareto_frontier              : Strategies on the Pareto frontier (from MOO analysis)
    pareto_dominated             : Strategies dominated during Pareto analysis
    pareto_invalid               : Strategies that failed build or correctness
    candidates_considered        : Strategies on frontier that match ACTIONS
    filtered_out                 : Strategies preferred by model (higher Q) excluded by MOO
    final_strategy               : The strategy ultimately selected
    selection_reason             : Human-readable rationale for final strategy selection
    selection_method             : Selection method identifier (e.g. 'moo_aware', 'argmax_fallback_*')
    moo_active                   : True if MOO Pareto filtering was active
    ai_choice_was_pareto_optimal : True if AI choice was on frontier, False if not, None if no MOO data
    """

    # --- AI Layer ---
    ai_top_choice: str
    ai_top_q: float
    q_rank_full: list[tuple[str, float]]

    # --- Input Features ---
    ir_features: Optional[dict[str, float]]

    # --- Pareto / Filtering Layer ---
    pareto_frontier: list[str]
    pareto_dominated: list[str]
    pareto_invalid: list[str]
    candidates_considered: list[str]
    filtered_out: list[str]
    moo_active: bool
    ai_choice_was_pareto_optimal: Optional[bool]

    # --- Final Decision ---
    final_strategy: str
    selection_reason: str
    selection_method: str

    # --- Week 7 Phase 2B: Optional Program Profile (informational only) ---
    program_profile: Optional[dict] = None

    def to_dict(self) -> dict:
        """Serialize XAIResult to a JSON-safe dictionary."""
        return {
            "ai_top_choice": self.ai_top_choice,
            "ai_top_q": float(self.ai_top_q),
            "q_rank_full": [[str(s), float(q)] for s, q in self.q_rank_full],
            "ir_features": (
                {str(k): float(v) for k, v in self.ir_features.items()}
                if self.ir_features is not None
                else None
            ),
            "pareto_frontier": list(self.pareto_frontier),
            "pareto_dominated": list(self.pareto_dominated),
            "pareto_invalid": list(self.pareto_invalid),
            "candidates_considered": list(self.candidates_considered),
            "filtered_out": list(self.filtered_out),
            "moo_active": bool(self.moo_active),
            "ai_choice_was_pareto_optimal": self.ai_choice_was_pareto_optimal,
            "final_strategy": self.final_strategy,
            "selection_reason": self.selection_reason,
            "selection_method": self.selection_method,
            "program_profile": (
                dict(self.program_profile)
                if self.program_profile is not None
                else None
            ),
        }

    @staticmethod
    def from_dict(d: dict) -> "XAIResult":
        """
        Reconstruct XAIResult from a dictionary.
        Gracefully handles missing keys with safe defaults.
        """
        raw_feats = d.get("ir_features")
        feats = format_ir_features(raw_feats) if raw_feats is not None else None

        raw_q_rank = d.get("q_rank_full", [])
        q_rank = []
        for item in raw_q_rank:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    q_rank.append((str(item[0]), float(item[1])))
                except (ValueError, TypeError):
                    q_rank.append((str(item[0]), 0.0))

        raw_prof = d.get("program_profile")
        prof = dict(raw_prof) if isinstance(raw_prof, dict) else None

        return XAIResult(
            ai_top_choice=str(d.get("ai_top_choice", "")),
            ai_top_q=float(d.get("ai_top_q", 0.0)),
            q_rank_full=q_rank,
            ir_features=feats,
            pareto_frontier=list(d.get("pareto_frontier", [])),
            pareto_dominated=list(d.get("pareto_dominated", [])),
            pareto_invalid=list(d.get("pareto_invalid", [])),
            candidates_considered=list(d.get("candidates_considered", [])),
            filtered_out=list(d.get("filtered_out", [])),
            moo_active=bool(d.get("moo_active", False)),
            ai_choice_was_pareto_optimal=d.get("ai_choice_was_pareto_optimal"),
            final_strategy=str(d.get("final_strategy", "")),
            selection_reason=str(d.get("selection_reason", "")),
            selection_method=str(d.get("selection_method", "")),
            program_profile=prof,
        )

    @classmethod
    def from_decision_trace(
        cls,
        trace: Any,
        ir_features: Optional[dict[str, Any] | Sequence[Any]] = None,
    ) -> "XAIResult":
        """
        Build XAIResult from an existing DecisionTrace object or trace dict.
        Does not recompute the AI model or rerun optimizations.
        """
        if trace is None:
            raise ValueError("Cannot create XAIResult from None DecisionTrace")

        # Support dictionary input as well as DecisionTrace dataclass
        if isinstance(trace, dict):
            # If ir_features passed explicitly, use it; else look in dict
            feat_input = ir_features if ir_features is not None else trace.get("ir_features")
            d = dict(trace)
            d["ir_features"] = format_ir_features(feat_input)
            return cls.from_dict(d)

        # Trace dataclass
        feat_input = ir_features if ir_features is not None else getattr(trace, "ir_features", None)
        formatted_feats = format_ir_features(feat_input)
        raw_prof = getattr(trace, "program_profile", None)
        prof = dict(raw_prof) if isinstance(raw_prof, dict) else None

        return cls(
            ai_top_choice=trace.ai_top_choice,
            ai_top_q=trace.ai_top_q,
            q_rank_full=list(trace.q_rank_full),
            ir_features=formatted_feats,
            pareto_frontier=list(trace.pareto_frontier),
            pareto_dominated=list(trace.pareto_dominated),
            pareto_invalid=list(trace.pareto_invalid),
            candidates_considered=list(trace.candidates_considered),
            filtered_out=list(trace.filtered_out),
            moo_active=trace.moo_active,
            ai_choice_was_pareto_optimal=trace.ai_choice_was_pareto_optimal,
            final_strategy=trace.final_strategy,
            selection_reason=trace.selection_reason,
            selection_method=trace.selection_method,
            program_profile=prof,
        )

    def to_text_summary(self) -> str:
        """Return a human-readable text explanation of the decision."""
        return format_xai_summary(self)


# ---------------------------------------------------------------------------
# Transformation Functions
# ---------------------------------------------------------------------------
def create_xai_result(
    trace: Any,
    ir_features: Optional[dict[str, Any] | Sequence[Any]] = None,
) -> XAIResult:
    """
    Transform an existing DecisionTrace into an XAIResult.

    Parameters
    ----------
    trace       : DecisionTrace instance or dictionary representing DecisionTrace.
    ir_features : Optional feature dictionary or sequence to override/supplement trace.

    Returns
    -------
    XAIResult instance.
    """
    return XAIResult.from_decision_trace(trace, ir_features=ir_features)


# ---------------------------------------------------------------------------
# Human-Readable Formatting
# ---------------------------------------------------------------------------
def format_xai_summary(xai_res: XAIResult) -> str:
    """
    Format XAIResult into an explainability summary using clear, academic terms.
    Strictly avoids unsupported terminology such as confidence, trust, or causality.
    """
    lines = []
    sep = "=" * 68
    subsep = "-" * 68

    lines.append(sep)
    lines.append("TOACD EXPLAINABLE AI (XAI) DECISION SUMMARY")
    lines.append(sep)

    lines.append(f"Model-Selected Strategy (Argmax) : {xai_res.ai_top_choice} (Q = {xai_res.ai_top_q:.4f})")
    lines.append(f"Final Selected Strategy          : {xai_res.final_strategy}")
    lines.append(f"Selection Method                 : {xai_res.selection_method}")
    lines.append(f"Pareto Filtering Applied         : {xai_res.moo_active}")

    if xai_res.ai_choice_was_pareto_optimal is not None:
        lines.append(f"Model Top Choice Pareto-Optimal  : {xai_res.ai_choice_was_pareto_optimal}")
    else:
        lines.append("Model Top Choice Pareto-Optimal  : Not evaluated (no MOO data)")

    lines.append("")
    lines.append("Selection Rationale:")
    lines.append(f"  {xai_res.selection_reason}")

    # Model Output Ranking
    lines.append("")
    lines.append("Model Output Q-Values:")
    lines.append(f"  {'Rank':<4}  {'Strategy':<35}  {'Q-Value':>7}   {'Pareto Status':<10}")
    lines.append(f"  {'-'*4}  {'-'*35}  {'-'*7}   {'-'*10}")

    frontier_set = set(xai_res.pareto_frontier)
    dominated_set = set(xai_res.pareto_dominated)
    invalid_set = set(xai_res.pareto_invalid)

    for idx, (strat, q_val) in enumerate(xai_res.q_rank_full, 1):
        if strat in frontier_set:
            status = "FRONTIER"
        elif strat in dominated_set:
            status = "DOMINATED"
        elif strat in invalid_set:
            status = "INVALID"
        else:
            status = "UNKNOWN" if xai_res.moo_active else "N/A"

        marker = ""
        if strat == xai_res.final_strategy and strat == xai_res.ai_top_choice:
            marker = " ← selected & model choice"
        elif strat == xai_res.final_strategy:
            marker = " ← selected"
        elif strat == xai_res.ai_top_choice:
            marker = " ← model top choice"

        lines.append(f"  {idx:<4}  {strat:<35}  {q_val:7.4f}   {status:<10}{marker}")

    # Filtered out strategies
    if xai_res.filtered_out:
        lines.append("")
        lines.append("Filtered Out by MOO (Model preferred, but not Pareto-optimal):")
        for strat in xai_res.filtered_out:
            lines.append(f"  • {strat}")

    # Input Features
    if xai_res.ir_features:
        lines.append("")
        lines.append("Input IR Features (Unoptimized):")
        for name, val in xai_res.ir_features.items():
            lines.append(f"  • {name:<22}: {int(val) if val.is_integer() else val}")
    else:
        lines.append("")
        lines.append("Input IR Features: None recorded")

    # Program Profile (Week 7 Phase 2B - Informational analysis only)
    if xai_res.program_profile:
        lines.append("")
        lines.append("Program Profile (Informational Analysis):")
        lbl = xai_res.program_profile.get("label", "unknown")
        dom_f = xai_res.program_profile.get("dominant_feature", "None")
        dom_v = xai_res.program_profile.get("dominant_feature_value", 0.0)
        is_triv = xai_res.program_profile.get("is_trivial", False)
        method = xai_res.program_profile.get("profile_method", "ir_heuristic_threshold")
        lines.append(f"  • Profile Label        : {lbl}")
        v_str = f"{int(dom_v)}" if isinstance(dom_v, (int, float)) and float(dom_v).is_integer() else f"{dom_v}"
        lines.append(f"  • Dominant Feature     : {dom_f} ({v_str})")
        lines.append(f"  • Profile Method       : {method}")
        lines.append(f"  • Trivial Program      : {is_triv}")

    lines.append(sep)
    return "\n".join(lines)


def print_xai_summary(xai_res: XAIResult, file: Any = None) -> None:
    """Print the XAI summary to stdout or a file stream."""
    import sys
    out = file if file is not None else sys.stdout
    print(format_xai_summary(xai_res), file=out)
