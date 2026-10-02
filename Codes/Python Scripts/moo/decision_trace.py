"""
moo/decision_trace.py — Structured model for MOO decision transparency.

Captures the full reasoning chain for one optimization-selection decision:
  DQN Q-values → Pareto frontier filter → final strategy selection

Pure data containers and serialization methods — no selection logic lives here.
"""

from __future__ import annotations

import dataclasses
from typing import Optional


# SelectionMethod: exact string values (not an Enum — avoids JSON serialization friction)
#   "moo_aware"                         — MOO filter applied, strategy from frontier
#   "argmax_fallback_no_frontier"       — frontier was empty; pure argmax used
#   "argmax_fallback_frontier_mismatch" — frontier non-empty but no member in ACTIONS
#   "argmax_fallback_exception"         — moo_aware_select() raised an unhandled exception
SELECTION_METHOD_MOO_AWARE                  = "moo_aware"
SELECTION_METHOD_ARGMAX_NO_FRONTIER         = "argmax_fallback_no_frontier"
SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH   = "argmax_fallback_frontier_mismatch"
SELECTION_METHOD_ARGMAX_EXCEPTION           = "argmax_fallback_exception"


@dataclasses.dataclass
class ObjectiveSnapshot:
    """
    Objective values for ONE strategy at the point of selection.
    All values taken verbatim from CandidateResult.normalized (no recomputation).
    None means the value was not available in the cached report.
    """
    strategy_name: str
    pareto_status: str                     # "FRONTIER" | "DOMINATED" | "INVALID" | "UNKNOWN"
    execution_time_ratio: Optional[float]  # normalized value (candidate / baseline)
    energy_ratio: Optional[float]
    code_size_ratio: Optional[float]
    carbon_ratio: Optional[float]
    q_value: Optional[float]               # DQN Q-value for this strategy (None if not in q_rank)

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "pareto_status": self.pareto_status,
            "execution_time_ratio": self.execution_time_ratio,
            "energy_ratio": self.energy_ratio,
            "code_size_ratio": self.code_size_ratio,
            "carbon_ratio": self.carbon_ratio,
            "q_value": self.q_value,
        }

    @staticmethod
    def from_dict(d: dict) -> "ObjectiveSnapshot":
        return ObjectiveSnapshot(
            strategy_name=d["strategy_name"],
            pareto_status=d.get("pareto_status", "UNKNOWN"),
            execution_time_ratio=d.get("execution_time_ratio"),
            energy_ratio=d.get("energy_ratio"),
            code_size_ratio=d.get("code_size_ratio"),
            carbon_ratio=d.get("carbon_ratio"),
            q_value=d.get("q_value"),
        )


@dataclasses.dataclass
class DecisionTrace:
    """
    Complete, immutable record of one optimization-selection decision.

    Captures the full reasoning chain:
        DQN Q-values → Pareto frontier filter → final strategy selection

    This dataclass records what already happened. It does not influence
    the selection algorithm in any way.

    Fields
    ------
    AI layer:
        ai_top_choice       — strategy name chosen by pure Q-value argmax
                              (i.e. what the AI would have picked without MOO)
        ai_top_q            — Q-value of ai_top_choice
        q_rank_full         — full ranked list of (strategy_name, q_value) tuples,
                              descending by Q-value. Includes all actions passed in.

    Pareto layer:
        pareto_frontier     — strategy names on the Pareto frontier (from cached report)
        pareto_dominated    — strategy names dominated by at least one frontier member
        pareto_invalid      — strategy names that failed build or correctness
        objectives_used     — objective names active in the Pareto analysis
        moo_active          — True if the MOO filter was actually applied

    Filtering:
        ai_choice_was_pareto_optimal
                            — True if ai_top_choice is in pareto_frontier
                            — False if ai_top_choice is NOT in pareto_frontier
                            — None if pareto_frontier was empty or unavailable
        candidates_considered
                            — frontier strategy names that were also in ACTIONS;
                              these were the actual candidates for final selection.
                              Empty if frontier was empty or frontier∩ACTIONS was empty.
        filtered_out        — strategy names the AI ranked higher than the final
                              selection but MOO excluded (not on frontier).
                              Empty if moo_active is False.

    Final decision:
        final_strategy      — the selected strategy (identical to what get_best_optimization returns)
        selection_reason    — human-readable explanation (from SelectionResult.reason)
        selection_method    — one of the SELECTION_METHOD_* constants

    Objective snapshot:
        objective_snapshot  — list of ObjectiveSnapshot, one per strategy that was
                              a candidate for the final decision PLUS the ai_top_choice.
                              Sourced from the cached moo_*.json report.
                              Empty list if the report had no normalized objective data.
    """

    # --- AI layer ---
    ai_top_choice: str
    ai_top_q: float
    q_rank_full: list[tuple[str, float]]    # list of (strategy_name, q_value)

    # --- Pareto layer ---
    pareto_frontier: list[str]
    pareto_dominated: list[str]
    pareto_invalid: list[str]
    objectives_used: list[str]
    moo_active: bool

    # --- Filtering ---
    ai_choice_was_pareto_optimal: Optional[bool]
    candidates_considered: list[str]
    filtered_out: list[str]

    # --- Final decision ---
    final_strategy: str
    selection_reason: str
    selection_method: str

    # --- Objective snapshot ---
    objective_snapshot: list[ObjectiveSnapshot]

    # --- Week 7: Optional Input Features ---
    ir_features: Optional[dict[str, float]] = None

    # --- Week 7 Phase 2B: Optional Program Profile (informational only) ---
    program_profile: Optional[dict] = None

    # ----------------------------------------------------------------

    def to_dict(self) -> dict:
        d = {
            "ai_top_choice": self.ai_top_choice,
            "ai_top_q": self.ai_top_q,
            "q_rank_full": [list(pair) for pair in self.q_rank_full],
            "pareto_frontier": list(self.pareto_frontier),
            "pareto_dominated": list(self.pareto_dominated),
            "pareto_invalid": list(self.pareto_invalid),
            "objectives_used": list(self.objectives_used),
            "moo_active": self.moo_active,
            "ai_choice_was_pareto_optimal": self.ai_choice_was_pareto_optimal,
            "candidates_considered": list(self.candidates_considered),
            "filtered_out": list(self.filtered_out),
            "final_strategy": self.final_strategy,
            "selection_reason": self.selection_reason,
            "selection_method": self.selection_method,
            "objective_snapshot": [s.to_dict() for s in self.objective_snapshot],
        }
        if self.ir_features is not None:
            d["ir_features"] = {str(k): float(v) for k, v in self.ir_features.items()}
        if self.program_profile is not None:
            d["program_profile"] = dict(self.program_profile)
        return d

    @staticmethod
    def from_dict(d: dict) -> "DecisionTrace":
        """
        Reconstruct a DecisionTrace from a JSON-deserialized dict.
        Unknown keys are silently ignored for forward compatibility.
        Missing keys fall back to safe defaults (backward compatibility).
        """
        raw_feats = d.get("ir_features")
        feats = (
            {str(k): float(v) for k, v in raw_feats.items()}
            if isinstance(raw_feats, dict)
            else None
        )
        raw_prof = d.get("program_profile")
        profile = dict(raw_prof) if isinstance(raw_prof, dict) else None
        return DecisionTrace(
            ai_top_choice=d.get("ai_top_choice", ""),
            ai_top_q=d.get("ai_top_q", 0.0),
            q_rank_full=[tuple(pair) for pair in d.get("q_rank_full", [])],
            pareto_frontier=list(d.get("pareto_frontier", [])),
            pareto_dominated=list(d.get("pareto_dominated", [])),
            pareto_invalid=list(d.get("pareto_invalid", [])),
            objectives_used=list(d.get("objectives_used", [])),
            moo_active=bool(d.get("moo_active", False)),
            ai_choice_was_pareto_optimal=d.get("ai_choice_was_pareto_optimal"),
            candidates_considered=list(d.get("candidates_considered", [])),
            filtered_out=list(d.get("filtered_out", [])),
            final_strategy=d.get("final_strategy", ""),
            selection_reason=d.get("selection_reason", ""),
            selection_method=d.get("selection_method", SELECTION_METHOD_ARGMAX_NO_FRONTIER),
            objective_snapshot=[
                ObjectiveSnapshot.from_dict(s)
                for s in d.get("objective_snapshot", [])
            ],
            ir_features=feats,
            program_profile=profile,
        )

    def to_xai_result(self, ir_features: Optional[dict[str, float]] = None) -> Any:
        """Convert this DecisionTrace into an XAIResult (Week 7)."""
        from .xai import create_xai_result
        return create_xai_result(self, ir_features=ir_features)
