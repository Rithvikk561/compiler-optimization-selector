"""
moo/adaptive/schema.py — Versioned data models for Week 11 Adaptive Self-Learning.

Core models
-----------
ExperienceRecord
    Durable, versioned representation of one optimization experience.
    Contains program identity, features, selected strategy, provenance,
    benchmark outcome, regression outcome, computed reward, and metadata.

ModelVersionInfo
    Metadata attached to each candidate model artifact.  Identifies which
    experience range was used, which schema version, and ensures backward
    compatibility.

ADAPTIVE_SCHEMA_VERSION
    Version string embedded in every ExperienceRecord and ModelVersionInfo.

Design constraints
------------------
* ExperienceRecord is JSON-serializable (to_dict / from_dict).
* No duplicate of information already canonical elsewhere (e.g. strategy
  names from ACTIONS, metric names from objectives.py).
* Derived-metric families (energy, carbon) are represented as a group
  to avoid treating them as independent dimensions.
* schema_version is checked on deserialization — old records with
  unsupported versions are rejected.
* Reward is stored verbatim (deterministic, bounded).
* source_hash is a SHA-256 of the program source used for identity.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Version identifier
# ---------------------------------------------------------------------------

ADAPTIVE_SCHEMA_VERSION: str = "week11.1.0"
"""Version string embedded in every ExperienceRecord and ModelVersionInfo."""

SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("week11.1.0",)
"""Versions that can be deserialized without error."""


# ---------------------------------------------------------------------------
# ExperienceRecord
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ExperienceRecord:
    """
    Durable, versioned record of one complete optimization experience.

    One experience captures:
      - program identity and source integrity
      - canonical IR features used for DQN state
      - the action (strategy) selected
      - selection provenance (model version, method, trace reference)
      - benchmark outcome (measured metrics)
      - regression outcome (comparison vs baseline, overall status)
      - computed reward (deterministic, bounded)
      - metadata (timestamp, run_id, schema_version)

    Fields
    ------
    schema_version
        Always ADAPTIVE_SCHEMA_VERSION.

    experience_id
        Unique identifier for this record.  Typically:
        ``{program_id}_{run_id}_{timestamp_compact}``.

    program_id
        Stable identifier for the benchmark program
        (e.g. "01_hello_world" or "gen_loop_seed42_0").

    source_hash
        SHA-256 hex digest of the C source file used for this run.
        Used for identity and staleness detection.

    run_id
        Identifier of the benchmark run that produced this experience
        (matches bench.schema.ProgramRecord.run_id where applicable).

    timestamp
        ISO-8601 creation timestamp (set at record creation, never updated).

    ir_features
        Canonical 8 IR feature vector used as DQN input state.
        Dict mapping feature name → float.
        Must not be empty; validated on acceptance.

    selected_action
        The optimization strategy string selected by the pipeline
        (e.g. "-O2" or "mem2reg,instcombine,simplifycfg,dce").
        Must be a member of the known ACTIONS list.

    selection_method
        How the strategy was chosen:
        "moo_aware" | "argmax_fallback_no_frontier" |
        "argmax_fallback_frontier_mismatch" | "argmax_fallback_exception".

    model_identifier
        Identifies which model checkpoint generated the Q-values
        (e.g. "production_v0" or a SHA-256 of the .pth file).

    trace_id
        Optional reference to a DecisionTrace artifact or file.

    q_value_selected
        Q-value assigned to selected_action by the model.

    q_value_argmax
        Q-value of the pure argmax action (may equal q_value_selected).

    pareto_frontier
        List of strategy names on the Pareto frontier at selection time.
        Empty if MOO was unavailable.

    benchmark_metrics
        Dict of measured objective values:
          {
            "execution_time_s": float | None,
            "code_size_bytes":  float | None,
            "energy_j":         float | None,   # estimated; derived family
            "carbon_g":         float | None,   # derived from energy
          }
        None means the metric was not measured (e.g. build failed).

    baseline_metrics
        Same keys as benchmark_metrics but for the -O0 baseline.
        Used to compute normalized reward.

    benchmark_build_ok
        True if the selected strategy compiled and ran correctly.

    benchmark_correct
        True if the optimized output matched the reference run.

    regression_overall_status
        String from Week 10 OverallStatus:
        "IMPROVED" | "REGRESSED" | "MIXED" | "UNCHANGED" |
        "INCONCLUSIVE" | "INCOMPARABLE".
        None if regression analysis was not performed.

    regression_report_id
        Optional reference to the Week 10 RegressionReport artifact.

    reward
        Computed reward (bounded float).  Set by compute_reward().
        None until explicitly computed.

    reward_config_id
        Identifier of the RewardConfig used to compute reward.
        Ensures reproducibility.

    success
        True if the experience represents a successful optimization
        (build_ok AND correct AND reward > 0).

    notes
        List of free-form diagnostic notes.
    """

    schema_version: str
    experience_id: str
    program_id: str
    source_hash: str
    run_id: str
    timestamp: str

    # State / features
    ir_features: dict[str, float]

    # Action / selection
    selected_action: str
    selection_method: str
    model_identifier: str
    trace_id: Optional[str]
    q_value_selected: Optional[float]
    q_value_argmax: Optional[float]
    pareto_frontier: list[str]

    # Outcome
    benchmark_metrics: dict[str, Optional[float]]
    baseline_metrics: dict[str, Optional[float]]
    benchmark_build_ok: bool
    benchmark_correct: bool

    # Regression
    regression_overall_status: Optional[str]
    regression_report_id: Optional[str]

    # Reward (computed separately via compute_reward())
    reward: Optional[float]
    reward_config_id: str

    # Summary
    success: bool
    notes: list[str]

    # Week 10 Noise & Reliability Provenance
    confidence: Optional[str] = "HIGH"
    is_reliable: Optional[bool] = True

    # ----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "schema_version": self.schema_version,
            "experience_id": self.experience_id,
            "program_id": self.program_id,
            "source_hash": self.source_hash,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "ir_features": {str(k): float(v) for k, v in self.ir_features.items()},
            "selected_action": self.selected_action,
            "selection_method": self.selection_method,
            "model_identifier": self.model_identifier,
            "trace_id": self.trace_id,
            "q_value_selected": self.q_value_selected,
            "q_value_argmax": self.q_value_argmax,
            "pareto_frontier": list(self.pareto_frontier),
            "benchmark_metrics": dict(self.benchmark_metrics),
            "baseline_metrics": dict(self.baseline_metrics),
            "benchmark_build_ok": self.benchmark_build_ok,
            "benchmark_correct": self.benchmark_correct,
            "regression_overall_status": self.regression_overall_status,
            "regression_report_id": self.regression_report_id,
            "reward": self.reward,
            "reward_config_id": self.reward_config_id,
            "success": self.success,
            "notes": list(self.notes),
            "confidence": self.confidence,
            "is_reliable": self.is_reliable,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperienceRecord":
        """
        Reconstruct an ExperienceRecord from a JSON-deserialized dict.

        Raises ValueError if schema_version is unsupported.
        Missing optional fields fall back to safe defaults.
        """
        sv = d.get("schema_version", "")
        if sv not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"ExperienceRecord: unsupported schema_version {sv!r}. "
                f"Supported: {SUPPORTED_SCHEMA_VERSIONS}"
            )

        raw_feats = d.get("ir_features") or {}
        feats: dict[str, float] = {str(k): float(v) for k, v in raw_feats.items()}

        raw_bm = d.get("benchmark_metrics") or {}
        bm: dict[str, Optional[float]] = {
            k: (float(v) if v is not None else None)
            for k, v in raw_bm.items()
        }
        raw_bl = d.get("baseline_metrics") or {}
        bl: dict[str, Optional[float]] = {
            k: (float(v) if v is not None else None)
            for k, v in raw_bl.items()
        }

        return cls(
            schema_version=str(sv),
            experience_id=str(d.get("experience_id", "")),
            program_id=str(d.get("program_id", "")),
            source_hash=str(d.get("source_hash", "")),
            run_id=str(d.get("run_id", "")),
            timestamp=str(d.get("timestamp", "")),
            ir_features=feats,
            selected_action=str(d.get("selected_action", "")),
            selection_method=str(d.get("selection_method", "")),
            model_identifier=str(d.get("model_identifier", "")),
            trace_id=d.get("trace_id"),
            q_value_selected=_float_or_none(d.get("q_value_selected")),
            q_value_argmax=_float_or_none(d.get("q_value_argmax")),
            pareto_frontier=list(d.get("pareto_frontier") or []),
            benchmark_metrics=bm,
            baseline_metrics=bl,
            benchmark_build_ok=bool(d.get("benchmark_build_ok", False)),
            benchmark_correct=bool(d.get("benchmark_correct", False)),
            regression_overall_status=d.get("regression_overall_status"),
            regression_report_id=d.get("regression_report_id"),
            reward=_float_or_none(d.get("reward")),
            reward_config_id=str(d.get("reward_config_id", "default_v1")),
            success=bool(d.get("success", False)),
            notes=list(d.get("notes") or []),
            confidence=d.get("confidence", "HIGH"),
            is_reliable=d.get("is_reliable", True),
        )

    def to_json(self, **kwargs) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, s: str) -> "ExperienceRecord":
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(s))

    @classmethod
    def from_program_comparison(
        cls,
        comparison: Any,
        **kwargs: Any,
    ) -> Optional["ExperienceRecord"]:
        """
        Construct an ExperienceRecord from a Week 10 ProgramComparison.

        Delegates to adapter.experience_from_program_comparison().
        """
        from .adapter import experience_from_program_comparison
        return experience_from_program_comparison(comparison, **kwargs)


# ---------------------------------------------------------------------------
# ModelVersionInfo
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ModelVersionInfo:
    """
    Metadata attached to a candidate model artifact.

    Never embedded in a production model.  Written alongside each .pth
    file as a companion JSON so that every artifact is self-describing.

    Fields
    ------
    schema_version
        Always ADAPTIVE_SCHEMA_VERSION.

    model_version
        Monotonically increasing integer version tag (starts at 1).

    model_id
        Unique string identifier, e.g. "candidate_v1_2026-10-05".

    created_at
        ISO-8601 timestamp.

    source_model_id
        model_id of the model used as starting checkpoint (None for fresh).

    experience_count
        Number of experiences consumed in the training run.

    experience_id_first
        experience_id of the first experience in the training batch.

    experience_id_last
        experience_id of the last experience in the training batch.

    training_epochs
        Number of training epochs completed.

    mean_loss
        Mean training loss over the final epoch (or over all epochs).

    mean_reward
        Mean reward of experiences used in training.

    reward_config_id
        RewardConfig identifier used for reward values in training.

    dqn_input_dim
        DQN input dimension (must match active model).

    dqn_output_dim
        DQN output dimension (must match len(ACTIONS)).

    is_production
        Always False for candidate models — the active production model
        is never managed by this package.

    notes
        Free-form diagnostic notes.
    """
    schema_version: str
    model_version: int
    model_id: str
    created_at: str
    source_model_id: Optional[str]
    experience_count: int
    experience_id_first: Optional[str]
    experience_id_last: Optional[str]
    training_epochs: int
    mean_loss: Optional[float]
    mean_reward: Optional[float]
    reward_config_id: str
    dqn_input_dim: int
    dqn_output_dim: int
    is_production: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_version": self.model_version,
            "model_id": self.model_id,
            "created_at": self.created_at,
            "source_model_id": self.source_model_id,
            "experience_count": self.experience_count,
            "experience_id_first": self.experience_id_first,
            "experience_id_last": self.experience_id_last,
            "training_epochs": self.training_epochs,
            "mean_loss": self.mean_loss,
            "mean_reward": self.mean_reward,
            "reward_config_id": self.reward_config_id,
            "dqn_input_dim": self.dqn_input_dim,
            "dqn_output_dim": self.dqn_output_dim,
            "is_production": self.is_production,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModelVersionInfo":
        return cls(
            schema_version=str(d.get("schema_version", ADAPTIVE_SCHEMA_VERSION)),
            model_version=int(d.get("model_version", 0)),
            model_id=str(d.get("model_id", "")),
            created_at=str(d.get("created_at", "")),
            source_model_id=d.get("source_model_id"),
            experience_count=int(d.get("experience_count", 0)),
            experience_id_first=d.get("experience_id_first"),
            experience_id_last=d.get("experience_id_last"),
            training_epochs=int(d.get("training_epochs", 0)),
            mean_loss=_float_or_none(d.get("mean_loss")),
            mean_reward=_float_or_none(d.get("mean_reward")),
            reward_config_id=str(d.get("reward_config_id", "default_v1")),
            dqn_input_dim=int(d.get("dqn_input_dim", 8)),
            dqn_output_dim=int(d.get("dqn_output_dim", 9)),
            is_production=bool(d.get("is_production", False)),
            notes=list(d.get("notes") or []),
        )

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, s: str) -> "ModelVersionInfo":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float_or_none(v: Any) -> Optional[float]:
    """Convert to float, returning None if v is None or non-finite."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def make_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat(timespec="seconds")


def experience_from_program_comparison(*args: Any, **kwargs: Any) -> Optional[ExperienceRecord]:
    """Canonical conversion helper delegating to adapter.experience_from_program_comparison."""
    from .adapter import experience_from_program_comparison as _exp_from_comp
    return _exp_from_comp(*args, **kwargs)
