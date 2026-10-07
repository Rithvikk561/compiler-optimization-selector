"""
moo.agentic_security.guard — Unified Agentic AI Security Guard.

Coordinates L1 input screening, L2 action enforcement, L3 artifact scanning,
and output report validation, creating canonical SecurityEvents in the shared log.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from .schema import (
    SimulatedAgentRequest,
    GeneratedArtifact,
    ActionCategory,
    SimulatedChannel,
)
from .policy import check_action_allowed
from .input_screen import screen_input_text
from .artifact_scan import evaluate_differential_artifact
from .output_validator import validate_agent_report
from ..secevent.schema import (
    ThreatDomain,
    AttackType,
    EventSource,
    RiskLevel,
    ActionAttempted,
    ActionTaken,
    SecurityEvent,
)
from ..secevent.risk import Signal, compute_risk_assessment
from ..secevent.log import SecurityEventLog


@dataclasses.dataclass(frozen=True)
class GuardExecutionResult:
    allowed: bool
    blocked: bool
    risk_level: RiskLevel
    score: int
    confidence: float
    events: list[SecurityEvent]
    reason: str
    action_taken: ActionTaken = ActionTaken.ALLOW


class AgenticSecurityGuard:
    """
    Unified gatekeeper for all agent interactions, artifacts, and reports.
    """

    def __init__(self, event_log: Optional[SecurityEventLog] = None) -> None:
        self.event_log = event_log if event_log is not None else SecurityEventLog()

    def screen_request(
        self,
        request: SimulatedAgentRequest,
        run_id: Optional[str] = None,
    ) -> GuardExecutionResult:
        """
        Screen an untrusted incoming request through L1 (text) and L2 (actions).
        """
        events: list[SecurityEvent] = []
        is_blocked = False
        primary_reason = ""
        max_score = 0
        worst_level = RiskLevel.NONE
        max_conf = 0.0

        # L1: Text screening
        if request.text:
            l1_res = screen_input_text(request.text)
            if l1_res.blocked or l1_res.score > 0:
                is_blocked = is_blocked or l1_res.blocked
                max_score = max(max_score, l1_res.score)
                worst_level = l1_res.risk_level
                max_conf = max(max_conf, l1_res.confidence)
                primary_reason = l1_res.reason

                evt = SecurityEvent.create(
                    sequence=self.event_log.next_sequence,
                    threat_domain=ThreatDomain.AGENTIC_AI_SECURITY,
                    attack_type=l1_res.attack_types[0] if l1_res.attack_types else AttackType.PROMPT_INJECTION,
                    source=EventSource.L1_INPUT_SCREEN,
                    risk_level=l1_res.risk_level,
                    score=l1_res.score,
                    confidence=l1_res.confidence,
                    evidence=request.text[:128],
                    action_attempted=l1_res.action_attempted,
                    action_taken=l1_res.action_taken,
                    blocked=l1_res.blocked,
                    reason=l1_res.reason,
                    affected_run_id=run_id,
                    affected_artifact_id=request.request_id,
                    policy_rules=["L1_INPUT_SCREEN"],
                )
                self.event_log.append(evt)
                events.append(evt)

        # L2: Action enforcement (Default-Deny)
        for act in request.requested_actions:
            allowed, act_reason = check_action_allowed(act)
            if not allowed:
                is_blocked = True
                act_sig = Signal("L2_DENY", "action_policy_violation", 10, 0.95, evidence=str(act))
                act_risk = compute_risk_assessment([act_sig], has_forbidden_capability=True)
                max_score = max(max_score, act_risk.score)
                worst_level = act_risk.risk_level
                max_conf = max(max_conf, act_risk.confidence)
                if not primary_reason:
                    primary_reason = act_reason

                # Map action category to AttackType
                atk_map = {
                    ActionCategory.DISABLE_VALIDATION: (AttackType.VALIDATION_DISABLE, ActionAttempted.DISABLE_VALIDATION),
                    ActionCategory.MODIFY_POLICY: (AttackType.POLICY_BYPASS, ActionAttempted.OVERRIDE_POLICY),
                    ActionCategory.SET_SECURITY_VERDICT: (AttackType.VERDICT_MANIPULATION, ActionAttempted.MARK_SAFE),
                    ActionCategory.SUPPRESS_FINDING: (AttackType.FINDING_SUPPRESSION, ActionAttempted.SUPPRESS_FINDINGS),
                    ActionCategory.MODIFY_STRATEGY: (AttackType.STRATEGY_MUTATION, ActionAttempted.MUTATE_STRATEGY),
                    ActionCategory.READ_ENV_SECRET: (AttackType.SECRET_EXFILTRATION, ActionAttempted.READ_SECRET),
                    ActionCategory.READ_FILE_OUTSIDE_SCOPE: (AttackType.SENSITIVE_FILE_ACCESS, ActionAttempted.READ_SENSITIVE_FILE),
                    ActionCategory.ACCESS_PII: (AttackType.PII_ACCESS, ActionAttempted.ACCESS_PII),
                    ActionCategory.EXEC_COMMAND: (AttackType.COMMAND_EXECUTION, ActionAttempted.EXEC_COMMAND),
                    ActionCategory.NETWORK_ACCESS: (AttackType.NETWORK_EXFILTRATION, ActionAttempted.NETWORK_CALL),
                    ActionCategory.CLEAR_LOG: (AttackType.LOG_TAMPERING, ActionAttempted.CLEAR_LOG),
                }
                mapped_atk, mapped_act = atk_map.get(
                    act if isinstance(act, ActionCategory) else ActionCategory.UNKNOWN_CATEGORY,
                    (AttackType.POLICY_BYPASS, ActionAttempted.UNKNOWN_ACTION),
                )

                evt = SecurityEvent.create(
                    sequence=self.event_log.next_sequence,
                    threat_domain=ThreatDomain.AGENTIC_AI_SECURITY,
                    attack_type=mapped_atk,
                    source=EventSource.L2_ACTION_POLICY,
                    risk_level=act_risk.risk_level,
                    score=act_risk.score,
                    confidence=act_risk.confidence,
                    evidence=f"Attempted forbidden action: {act}",
                    action_attempted=mapped_act,
                    action_taken=ActionTaken.BLOCK,
                    blocked=True,
                    reason=act_reason,
                    affected_run_id=run_id,
                    affected_artifact_id=request.request_id,
                    policy_rules=["L2_ACTION_POLICY_DEFAULT_DENY"],
                )
                self.event_log.append(evt)
                events.append(evt)

        if not events:
            return GuardExecutionResult(
                allowed=True,
                blocked=False,
                risk_level=RiskLevel.NONE,
                score=0,
                confidence=0.0,
                events=[],
                reason="Request passed L1 and L2 security screening",
                action_taken=ActionTaken.ALLOW,
            )

        action_taken = ActionTaken.BLOCK if is_blocked else (ActionTaken.ALLOW_FLAGGED if max_score >= 15 else ActionTaken.ALLOW)

        return GuardExecutionResult(
            allowed=not is_blocked,
            blocked=is_blocked,
            risk_level=worst_level,
            score=max_score,
            confidence=max_conf,
            events=events,
            reason=primary_reason,
            action_taken=action_taken,
        )

    def scan_artifact(
        self,
        artifact: GeneratedArtifact,
        baseline_text: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> GuardExecutionResult:
        """
        Scan a generated/healed artifact differentially against baseline (L3).
        """
        res = evaluate_differential_artifact(artifact, baseline_text)
        if not res.blocked and res.score == 0:
            return GuardExecutionResult(
                allowed=True,
                blocked=False,
                risk_level=RiskLevel.NONE,
                score=0,
                confidence=0.0,
                events=[],
                reason=res.reason,
                action_taken=ActionTaken.ALLOW,
            )

        evt = SecurityEvent.create(
            sequence=self.event_log.next_sequence,
            threat_domain=ThreatDomain.AGENTIC_AI_SECURITY,
            attack_type=AttackType.INJECTED_CAPABILITY if res.is_malicious else AttackType.POLICY_BYPASS,
            source=EventSource.L3_ARTIFACT_SCAN,
            risk_level=res.risk_level,
            score=res.score,
            confidence=res.confidence,
            evidence=f"Injected: {[c.value for c in res.injected_capabilities]}; Inherited: {[c.value for c in res.inherited_capabilities]}",
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=res.action_taken,
            blocked=res.blocked,
            reason=res.reason,
            affected_run_id=run_id,
            affected_artifact_id=artifact.artifact_id,
            policy_rules=["L3_ARTIFACT_CAPABILITY_SCAN"],
        )
        self.event_log.append(evt)

        return GuardExecutionResult(
            allowed=not res.blocked,
            blocked=res.blocked,
            risk_level=res.risk_level,
            score=res.score,
            confidence=res.confidence,
            events=[evt],
            reason=res.reason,
            action_taken=res.action_taken,
        )

    def validate_report(
        self,
        report_dict: dict[str, Any],
        expected_selected_strategy: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> GuardExecutionResult:
        """
        Validate agent analysis report output before attaching to RunRecord.
        """
        val_res = validate_agent_report(report_dict, expected_selected_strategy)
        if val_res.is_valid:
            return GuardExecutionResult(
                allowed=True,
                blocked=False,
                risk_level=RiskLevel.NONE,
                score=0,
                confidence=0.0,
                events=[],
                reason="Report validated successfully",
                action_taken=ActionTaken.ALLOW,
            )

        evt = SecurityEvent.create(
            sequence=self.event_log.next_sequence,
            threat_domain=ThreatDomain.AGENTIC_AI_SECURITY,
            attack_type=val_res.attack_types[0] if val_res.attack_types else AttackType.REPORT_TAMPERING,
            source=EventSource.OUTPUT_VALIDATOR,
            risk_level=val_res.risk_level,
            score=val_res.score,
            confidence=val_res.confidence,
            evidence=f"Quarantined report SHA-256 digest: {val_res.report_digest}",
            action_attempted=ActionAttempted.SUBMIT_TAMPERED_REPORT,
            action_taken=ActionTaken.QUARANTINE,
            blocked=True,
            reason=val_res.reason,
            affected_run_id=run_id,
            affected_artifact_id=val_res.report_digest[:16],
            policy_rules=["AGENT_REPORT_OUTPUT_VALIDATION"],
        )
        self.event_log.append(evt)

        return GuardExecutionResult(
            allowed=False,
            blocked=True,
            risk_level=val_res.risk_level,
            score=val_res.score,
            confidence=val_res.confidence,
            events=[evt],
            reason=val_res.reason,
            action_taken=ActionTaken.QUARANTINE,
        )
