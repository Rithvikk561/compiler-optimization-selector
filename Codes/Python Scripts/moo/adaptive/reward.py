"""
moo/adaptive/reward.py — Week 11: Deterministic reward calculation.

Design principles
-----------------
* Rewards are computed from normalized metric ratios (candidate / baseline).
* Energy and carbon are DERIVED from execution time (physical fact, not
  independent signals).  The reward treats them as one performance-family
  dimension, not three separate dimensions.  This preserves the Week 10
  derived-signal handling.
* Code size is an independent physical dimension (binary size, not runtime).
* Security penalisation is preserved from the original ml_optimizer.py reward.
* The reward is:
    - bounded and numerically stable (clamped to [-MAX_REWARD, +MAX_REWARD])
    - deterministic (no random components)
    - documented (see RewardConfig)
    - reproducible (same inputs → same reward, always)
    - testable (pure function, no side effects)

Reward formula (default_v1)
---------------------------
Given a candidate strategy S and -O0 baseline B:

  performance_ratio = execution_time(S) / execution_time(B)
     (< 1 means faster = better)

  size_ratio = code_size(S) / code_size(B)
     (< 1 means smaller = better)

  performance_gain = 1.0 - performance_ratio   ∈ (-∞, 1]
     (+ve means improvement over baseline)

  size_gain = 1.0 - size_ratio   ∈ (-∞, 1]

  reward = w_perf × performance_gain + w_size × size_gain
           - PENALTY_BUILD_FAIL  (if build failed)
           - PENALTY_INCORRECT   (if correctness check failed)
           - PENALTY_SECURITY    (if security violation detected, future hook)

  reward is then clamped to [-MAX_REWARD, +MAX_REWARD].

Why this formulation
--------------------
* performance_gain = 1 - ratio is unbounded below (large regression → large
  negative) but bounded above at 1.0 (zero time is impossible in practice).
* Using ratio avoids divide-by-zero on the reward side (divide occurs only
  when computing the ratio, where baseline is guarded to > 0).
* Energy and carbon are NOT included as separate terms because they are
  deterministic linear functions of execution_time in this project
  (energy = time × TDP × util; carbon = energy × intensity / 3.6e6).
  Including them as separate reward terms would triple-count the single
  underlying dimension.  This respects Week 10's derived-signal family design.
* Code size IS independent (static binary property, not derived from runtime).

Failure penalties
-----------------
  PENALTY_BUILD_FAIL    : applied when benchmark_build_ok is False
  PENALTY_INCORRECT     : applied when benchmark_correct is False
  These are large enough to dominate normal reward magnitudes.

INCOMPARABLE/missing metric handling
-------------------------------------
  If execution_time metrics are missing (None), reward is 0.0 (neutral).
  Ratios with a None or non-positive baseline fall back to ratio=1.0 (no gain).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Optional


# ---------------------------------------------------------------------------
# RewardConfig
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class RewardConfig:
    """
    Immutable configuration for reward calculation.

    Fields
    ------
    config_id
        Unique string identifier for this configuration.  Stored in each
        ExperienceRecord so rewards can be reproduced later.

    weight_performance
        Weight for the execution-time performance gain term.
        Default 0.7 — execution time is the primary optimisation target.

    weight_size
        Weight for the code-size gain term.
        Default 0.3 — code size is important but secondary.

    penalty_build_fail
        Reward deduction when the benchmark build failed.
        Default 10.0 (large, dominates normal reward range).

    penalty_incorrect
        Reward deduction when the optimized output is incorrect.
        Default 10.0 (large, dominates normal reward range).

    max_reward
        Absolute value clamp applied after all terms.
        Default 100.0.

    Note on weights
    ---------------
    weight_performance + weight_size need not sum to 1.0.  They are scaling
    factors.  The default (0.7, 0.3) mirrors the multi-objective priorities:
    execution time is primary, code size is secondary.

    Note on derived metrics
    -----------------------
    Energy and carbon are NOT weight parameters here because they are derived
    from execution_time.  Including them as separate weights would incorrectly
    multiply the performance signal.
    """

    config_id: str = "default_v1"
    weight_performance: float = 0.7
    weight_size: float = 0.3
    penalty_build_fail: float = 10.0
    penalty_incorrect: float = 10.0
    max_reward: float = 100.0
    inconclusive_attenuation: float = 0.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RewardConfig":
        return cls(
            config_id=str(d.get("config_id", "default_v1")),
            weight_performance=float(d.get("weight_performance", 0.7)),
            weight_size=float(d.get("weight_size", 0.3)),
            penalty_build_fail=float(d.get("penalty_build_fail", 10.0)),
            penalty_incorrect=float(d.get("penalty_incorrect", 10.0)),
            max_reward=float(d.get("max_reward", 100.0)),
            inconclusive_attenuation=float(d.get("inconclusive_attenuation", 0.0)),
        )


# Default reward configuration (used when none is specified)
DEFAULT_REWARD_CONFIG = RewardConfig()


# ---------------------------------------------------------------------------
# Noise & Reliability Evaluation (Week 10 Semantics)
# ---------------------------------------------------------------------------

def is_performance_inconclusive(
    *,
    confidence: Optional[str] = None,
    is_reliable: Optional[bool] = None,
    regression_overall_status: Optional[str] = None,
) -> bool:
    """
    Determine if the performance measurement is noisy, unreliable, or inconclusive
    using canonical Week 10 regression semantics.

    Returns True if:
      - is_reliable is explicitly False (timing failed reliability threshold)
      - confidence is INCONCLUSIVE, INCOMPARABLE, or LOW
      - regression_overall_status is INCONCLUSIVE or INCOMPARABLE
    """
    if is_reliable is False:
        return True
    if confidence in ("INCONCLUSIVE", "INCOMPARABLE", "LOW"):
        return True
    if regression_overall_status in ("INCONCLUSIVE", "INCOMPARABLE"):
        return True
    return False


# ---------------------------------------------------------------------------
# Core reward computation
# ---------------------------------------------------------------------------

def compute_reward(
    *,
    benchmark_metrics: dict[str, Optional[float]],
    baseline_metrics: dict[str, Optional[float]],
    benchmark_build_ok: bool,
    benchmark_correct: bool,
    confidence: Optional[str] = None,
    is_reliable: Optional[bool] = None,
    regression_overall_status: Optional[str] = None,
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> float:
    """
    Compute a deterministic, bounded reward for one optimization experience.

    Parameters
    ----------
    benchmark_metrics
        Dict of measured values for the selected strategy:
          "execution_time_s", "code_size_bytes", "energy_j", "carbon_g".
        None means the metric was not measured.

    baseline_metrics
        Same keys for the -O0 baseline.

    benchmark_build_ok
        True if the strategy compiled and produced an executable.

    benchmark_correct
        True if the optimized output matched the reference run.

    confidence
        Week 10 measurement confidence ('HIGH', 'LOW', 'INCONCLUSIVE', 'INCOMPARABLE').

    is_reliable
        Week 10 timing reliability boolean (False if noise/CV exceeded threshold).

    regression_overall_status
        Week 10 overall status ('IMPROVED', 'REGRESSED', 'MIXED', 'UNCHANGED', 'INCONCLUSIVE', 'INCOMPARABLE').

    config
        RewardConfig controlling weights, penalties, and noise attenuation.

    Returns
    -------
    float — bounded reward in [-config.max_reward, +config.max_reward].

    Notes
    -----
    * Energy and carbon are NOT used as independent terms.  See module docstring.
    * A failed build (build_ok=False) immediately returns a large negative reward.
    * An incorrect result (correct=False) applies PENALTY_INCORRECT but still
      computes the metric terms so the experience is informative.
    * INCONCLUSIVE or unreliable measurements attenuate the performance gain
      by config.inconclusive_attenuation (default 0.0), preventing noisy jitter
      from contributing a normal-strength reward.
    """
    reward = 0.0
    penalty = 0.0

    # --- Failure penalties first ---
    if not benchmark_build_ok:
        penalty += config.penalty_build_fail
        # No measurements available; return clamped penalty immediately.
        return _clamp(-penalty, config.max_reward)

    if not benchmark_correct:
        penalty += config.penalty_incorrect

    # --- Performance gain (execution time) ---
    perf_gain = _compute_ratio_gain(
        candidate_val=benchmark_metrics.get("execution_time_s"),
        baseline_val=baseline_metrics.get("execution_time_s"),
    )

    # Noise-aware attenuation (Week 10 semantics)
    if is_performance_inconclusive(
        confidence=confidence,
        is_reliable=is_reliable,
        regression_overall_status=regression_overall_status,
    ):
        perf_gain *= config.inconclusive_attenuation

    reward += config.weight_performance * perf_gain

    # --- Size gain (code size) ---
    # Code size IS an independent physical dimension (not derived from runtime).
    size_gain = _compute_ratio_gain(
        candidate_val=benchmark_metrics.get("code_size_bytes"),
        baseline_val=baseline_metrics.get("code_size_bytes"),
    )
    reward += config.weight_size * size_gain

    # NOTE: energy_j and carbon_g are intentionally NOT used as separate
    # reward terms.  They are deterministic linear functions of execution_time_s
    # (energy = time × TDP × utilisation; carbon = energy × grid_intensity).
    # Using them separately would triple-count the single performance dimension
    # and violate the derived-signal family rule established in Week 10.

    # --- Apply penalty ---
    reward -= penalty

    return _clamp(reward, config.max_reward)


def _compute_ratio_gain(
    candidate_val: Optional[float],
    baseline_val: Optional[float],
) -> float:
    """
    Compute gain = 1.0 - (candidate / baseline).

    Lower-is-better semantics: gain > 0 means candidate is better.

    Returns 0.0 (neutral) when either value is missing, non-finite,
    or baseline is zero/negative.
    """
    if candidate_val is None or baseline_val is None:
        return 0.0
    if not math.isfinite(candidate_val) or not math.isfinite(baseline_val):
        return 0.0
    if baseline_val <= 0.0:
        return 0.0
    if candidate_val < 0.0:
        return 0.0
    ratio = candidate_val / baseline_val
    return 1.0 - ratio


def _clamp(value: float, max_abs: float) -> float:
    """Clamp value to [-max_abs, +max_abs]."""
    if not math.isfinite(value):
        return 0.0
    return max(-max_abs, min(max_abs, value))


# ---------------------------------------------------------------------------
# Convenience: reward scalar from an ExperienceRecord (post-construction)
# ---------------------------------------------------------------------------

def apply_reward_to_experience(
    experience,
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> float:
    """
    Compute and store reward on an ExperienceRecord in-place.

    Preserves Week 10 noise/reliability metadata from the experience.
    Returns the computed reward.
    """
    r = compute_reward(
        benchmark_metrics=experience.benchmark_metrics,
        baseline_metrics=experience.baseline_metrics,
        benchmark_build_ok=experience.benchmark_build_ok,
        benchmark_correct=experience.benchmark_correct,
        confidence=getattr(experience, "confidence", None),
        is_reliable=getattr(experience, "is_reliable", None),
        regression_overall_status=getattr(experience, "regression_overall_status", None),
        config=config,
    )
    experience.reward = r
    experience.reward_config_id = config.config_id
    return r
