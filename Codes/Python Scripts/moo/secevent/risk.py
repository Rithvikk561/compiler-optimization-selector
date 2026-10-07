"""
moo.secevent.risk — Deterministic Security Risk Assessment Model.

Formula specification:
Signals have:
  rule_id: str
  family: str
  severity: int (1..10)
  rule_confidence: float (0.0..1.0)

Aggregate confidence:
  C = min(1.0, max(rule_conf) + 0.02 * (n_signals - 1))  [if signals exist, else 0.0]

Base score:
  base = S_max * 10 * (0.6 + 0.4 * C)

Capability bonus:
  cap_bonus = 10 if has_forbidden_capability else 0

Correlation bonus:
  corr = min(10, 5 * (distinct_families - 1)) if distinct_families > 1 else 0

Total score:
  score = min(100, floor(base + cap_bonus + corr + 0.5)) if signals else 0

Risk levels:
  NONE:      0–14
  LOW:      15–34
  MEDIUM:   35–59
  HIGH:     60–84
  CRITICAL: 85–100

Decision:
  hard_rule_violation -> BLOCK
  otherwise:
    score >= 60 -> BLOCK
    15 <= score <= 59 -> ALLOW_FLAGGED
    score < 15 -> ALLOW
"""

from __future__ import annotations

import dataclasses
import math
from typing import Sequence

from .schema import RiskLevel, ActionTaken


@dataclasses.dataclass(frozen=True)
class Signal:
    """A discrete detection signal produced by a security detector."""
    rule_id: str
    family: str
    severity: int  # 1..10
    rule_confidence: float  # e.g. 0.95 (strong exact phrase), 0.80 (keyword), 0.60 (heuristic)
    evidence: str = ""


@dataclasses.dataclass(frozen=True)
class RiskAssessment:
    """Result of risk evaluation over a set of signals."""
    score: int
    confidence: float
    risk_level: RiskLevel
    signals: list[Signal]
    s_max: int
    distinct_families: int
    cap_bonus: int
    corr_bonus: int


def compute_risk_assessment(
    signals: Sequence[Signal],
    *,
    has_forbidden_capability: bool = False,
) -> RiskAssessment:
    """
    Compute deterministic risk score, aggregate confidence, and risk level.
    """
    if not signals:
        return RiskAssessment(
            score=0,
            confidence=0.0,
            risk_level=RiskLevel.NONE,
            signals=[],
            s_max=0,
            distinct_families=0,
            cap_bonus=0,
            corr_bonus=0,
        )

    s_max = max(s.severity for s in signals)
    max_conf = max(s.rule_confidence for s in signals)
    n_signals = len(signals)

    # C = min(1.0, max(rule_conf) + 0.02*(n_signals-1))
    c = min(1.0, max_conf + 0.02 * (n_signals - 1))

    # base = S_max * 10 * (0.6 + 0.4 * C)
    base = s_max * 10.0 * (0.6 + 0.4 * c)

    cap_bonus = 10 if has_forbidden_capability else 0

    families = {s.family for s in signals}
    distinct_families = len(families)
    corr = min(10, 5 * (distinct_families - 1)) if distinct_families > 1 else 0

    raw_score = base + cap_bonus + corr + 0.5
    score = min(100, int(math.floor(raw_score)))

    # Determine RiskLevel
    if score >= 85:
        level = RiskLevel.CRITICAL
    elif score >= 60:
        level = RiskLevel.HIGH
    elif score >= 35:
        level = RiskLevel.MEDIUM
    elif score >= 15:
        level = RiskLevel.LOW
    else:
        level = RiskLevel.NONE

    return RiskAssessment(
        score=score,
        confidence=round(c, 4),
        risk_level=level,
        signals=list(signals),
        s_max=s_max,
        distinct_families=distinct_families,
        cap_bonus=cap_bonus,
        corr_bonus=corr,
    )


def assess_decision(
    risk: RiskAssessment,
    *,
    is_hard_rule_violation: bool = False,
) -> tuple[ActionTaken, bool]:
    """
    Determine (action_taken, blocked) based on risk and hard rule status.

    Returns:
      (ActionTaken.BLOCK, True) if hard rule violation or score >= 60
      (ActionTaken.ALLOW_FLAGGED, False) if 15 <= score < 60
      (ActionTaken.ALLOW, False) if score < 15
    """
    if is_hard_rule_violation:
        return ActionTaken.BLOCK, True

    if risk.score >= 60:
        return ActionTaken.BLOCK, True
    elif risk.score >= 15:
        return ActionTaken.ALLOW_FLAGGED, False
    else:
        return ActionTaken.ALLOW, False
