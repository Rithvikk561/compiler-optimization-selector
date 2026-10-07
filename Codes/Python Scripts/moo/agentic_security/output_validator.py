"""
moo.agentic_security.output_validator — Validation of AgentAnalysisReport outputs.

Validates that:
1. is_advisory_only == True
2. If alternative recommendation present:
   - alternative.strategy is in optimization_selector.ACTIONS
   - alternative recommendation is strictly advisory
3. report.selected_strategy matches current context strategy (no silent mutation)
4. All text fields in report (summary, reasoning, findings, tradeoff alerts) pass L1 screening
5. If invalid: BLOCK / QUARANTINE, store only SHA-256 digest of quarantined report, never raw secrets.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, Optional

from .input_screen import screen_input_text
from ..secevent.schema import AttackType, ActionAttempted, ActionTaken, RiskLevel
from ..secevent.risk import Signal, compute_risk_assessment, assess_decision

# 9 actions from optimization_selector.py
VALID_ACTIONS: frozenset[str] = frozenset({
    "-O0",
    "-O1",
    "-O2",
    "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
})


@dataclasses.dataclass(frozen=True)
class ReportValidationResult:
    is_valid: bool
    quarantine: bool
    report_digest: str
    risk_level: RiskLevel
    score: int
    confidence: float
    violations: list[str]
    attack_types: list[AttackType]
    action_taken: ActionTaken
    blocked: bool
    reason: str


def validate_agent_report(
    report_dict: dict[str, Any],
    expected_selected_strategy: Optional[str] = None,
) -> ReportValidationResult:
    """
    Validate AgentAnalysisReport dictionary for security, consistency, and advisory compliance.
    """
    raw_json = json.dumps(report_dict, sort_keys=True)
    digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    violations: list[str] = []
    attacks: list[AttackType] = []

    # 1. Advisory-only invariant check
    is_advisory = report_dict.get("is_advisory_only")
    if is_advisory is not True:
        violations.append("Report is_advisory_only is not True")
        attacks.append(AttackType.POLICY_BYPASS)

    # 2. Selected strategy consistency check
    rep_selected = report_dict.get("selected_strategy")
    if expected_selected_strategy and rep_selected != expected_selected_strategy:
        violations.append(
            f"Report selected_strategy {rep_selected!r} does not match context {expected_selected_strategy!r}"
        )
        attacks.append(AttackType.REPORT_TAMPERING)

    # 3. Alternative recommendation validation
    alt = report_dict.get("alternative_recommendation")
    if alt and isinstance(alt, dict):
        alt_strat = alt.get("strategy")
        if alt_strat not in VALID_ACTIONS:
            violations.append(f"Alternative recommendation strategy {alt_strat!r} is not a valid action")
            attacks.append(AttackType.REPORT_TAMPERING)

    # 4. L1 text screening across report text fields
    text_fields = [
        str(report_dict.get("summary", "")),
        str(report_dict.get("reasoning", "")),
    ]
    findings = report_dict.get("findings") or []
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict):
                text_fields.append(str(f.get("title", "")))
                text_fields.append(str(f.get("description", "")))

    tradeoffs = report_dict.get("tradeoff_alerts") or []
    if isinstance(tradeoffs, list):
        for t in tradeoffs:
            if isinstance(t, dict):
                text_fields.append(str(t.get("description", "")))

    for tf in text_fields:
        if tf:
            screen = screen_input_text(tf)
            if screen.blocked:
                violations.append(f"Malicious content detected in report text: {screen.reason}")
                attacks.extend(screen.attack_types)

    if not violations:
        return ReportValidationResult(
            is_valid=True,
            quarantine=False,
            report_digest=digest,
            risk_level=RiskLevel.NONE,
            score=0,
            confidence=0.0,
            violations=[],
            attack_types=[],
            action_taken=ActionTaken.ALLOW,
            blocked=False,
            reason="Report passed all output validation checks",
        )

    # Report failed -> QUARANTINE / BLOCK
    signals = [
        Signal(
            rule_id="REP_VAL_FAIL",
            family="report_tampering",
            severity=9,
            rule_confidence=0.95,
            evidence="; ".join(violations)[:128],
        )
    ]
    risk = compute_risk_assessment(signals, has_forbidden_capability=True)
    decision, blocked = assess_decision(risk, is_hard_rule_violation=True)

    return ReportValidationResult(
        is_valid=False,
        quarantine=True,
        report_digest=digest,
        risk_level=risk.risk_level,
        score=risk.score,
        confidence=risk.confidence,
        violations=violations,
        attack_types=attacks or [AttackType.REPORT_TAMPERING],
        action_taken=ActionTaken.QUARANTINE,
        blocked=True,
        reason=f"Agent report failed validation and is quarantined: {'; '.join(violations)}",
    )
