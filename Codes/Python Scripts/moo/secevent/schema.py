"""
moo.secevent.schema — Canonical, deterministic schema for SecurityEvent.

All fields are fully typed, JSON-serializable, and deterministic.
Timestamps are ISO-8601 strings and do NOT participate in event ID hashing or equality.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
import hashlib
import json
from typing import Any, Optional

SECEVENT_SCHEMA_VERSION = "secevent.1.0"


class ThreatDomain(str, Enum):
    OPTIMIZATION_SAFETY = "OPTIMIZATION_SAFETY"
    AGENTIC_AI_SECURITY = "AGENTIC_AI_SECURITY"
    SOURCE_INTEGRITY = "SOURCE_INTEGRITY"
    SYSTEM_INTEGRITY = "SYSTEM_INTEGRITY"


class AttackType(str, Enum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    POLICY_BYPASS = "POLICY_BYPASS"
    VALIDATION_DISABLE = "VALIDATION_DISABLE"
    VERDICT_MANIPULATION = "VERDICT_MANIPULATION"
    FINDING_SUPPRESSION = "FINDING_SUPPRESSION"
    STRATEGY_MUTATION = "STRATEGY_MUTATION"
    SECRET_EXFILTRATION = "SECRET_EXFILTRATION"
    PII_ACCESS = "PII_ACCESS"
    COMMAND_EXECUTION = "COMMAND_EXECUTION"
    NETWORK_EXFILTRATION = "NETWORK_EXFILTRATION"
    SENSITIVE_FILE_ACCESS = "SENSITIVE_FILE_ACCESS"
    LOG_TAMPERING = "LOG_TAMPERING"
    OPTIMIZATION_GUARD_ELIMINATION = "OPTIMIZATION_GUARD_ELIMINATION"
    OPTIMIZATION_GUARD_REDUCTION = "OPTIMIZATION_GUARD_REDUCTION"
    INJECTED_CAPABILITY = "INJECTED_CAPABILITY"
    REPORT_TAMPERING = "REPORT_TAMPERING"
    GUARD_ERROR = "GUARD_ERROR"
    UNKNOWN_ATTACK = "UNKNOWN_ATTACK"


class EventSource(str, Enum):
    L1_INPUT_SCREEN = "L1_INPUT_SCREEN"
    L2_ACTION_POLICY = "L2_ACTION_POLICY"
    L3_ARTIFACT_SCAN = "L3_ARTIFACT_SCAN"
    OUTPUT_VALIDATOR = "OUTPUT_VALIDATOR"
    OPTIMIZATION_SECURITY_GATE = "OPTIMIZATION_SECURITY_GATE"
    SOURCE_SCANNER = "SOURCE_SCANNER"


class RiskLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionAttempted(str, Enum):
    INSTRUCTION_INJECTION = "INSTRUCTION_INJECTION"
    DISABLE_VALIDATION = "DISABLE_VALIDATION"
    OVERRIDE_POLICY = "OVERRIDE_POLICY"
    MARK_SAFE = "MARK_SAFE"
    SUPPRESS_FINDINGS = "SUPPRESS_FINDINGS"
    MUTATE_STRATEGY = "MUTATE_STRATEGY"
    READ_SECRET = "READ_SECRET"
    READ_SENSITIVE_FILE = "READ_SENSITIVE_FILE"
    ACCESS_PII = "ACCESS_PII"
    EXEC_COMMAND = "EXEC_COMMAND"
    NETWORK_CALL = "NETWORK_CALL"
    CLEAR_LOG = "CLEAR_LOG"
    ELIMINATE_GUARD = "ELIMINATE_GUARD"
    REDUCE_GUARD = "REDUCE_GUARD"
    SUBMIT_TAMPERED_REPORT = "SUBMIT_TAMPERED_REPORT"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"


class ActionTaken(str, Enum):
    BLOCK = "BLOCK"
    ALLOW_FLAGGED = "ALLOW_FLAGGED"
    ALLOW = "ALLOW"
    QUARANTINE = "QUARANTINE"
    FALLBACK = "FALLBACK"


@dataclasses.dataclass(frozen=True)
class SecurityEvent:
    """
    Deterministic security event representing a detected threat, violation, or warning.

    Event identity (event_id) is derived purely from deterministic operational fields,
    NEVER from wall-clock timestamps (created_at).
    """
    event_id: str
    sequence: int
    created_at: str
    schema_version: str = SECEVENT_SCHEMA_VERSION
    threat_domain: ThreatDomain = ThreatDomain.AGENTIC_AI_SECURITY
    attack_type: AttackType = AttackType.UNKNOWN_ATTACK
    source: EventSource = EventSource.L1_INPUT_SCREEN
    risk_level: RiskLevel = RiskLevel.NONE
    score: int = 0
    confidence: float = 0.0
    evidence: str = ""
    action_attempted: ActionAttempted = ActionAttempted.UNKNOWN_ACTION
    action_taken: ActionTaken = ActionTaken.BLOCK
    blocked: bool = True
    reason: str = ""
    affected_run_id: Optional[str] = None
    affected_artifact_id: Optional[str] = None
    policy_rules: list[str] = dataclasses.field(default_factory=list)
    detector: str = "toacd_security_layer"
    detector_version: str = "1.0.0"
    policy_version: str = "1.0.0"

    @classmethod
    def create(
        cls,
        sequence: int,
        threat_domain: ThreatDomain,
        attack_type: AttackType,
        source: EventSource,
        risk_level: RiskLevel,
        score: int,
        confidence: float,
        evidence: str,
        action_attempted: ActionAttempted,
        action_taken: ActionTaken,
        blocked: bool,
        reason: str,
        created_at: str = "2026-10-07T00:00:00Z",
        affected_run_id: Optional[str] = None,
        affected_artifact_id: Optional[str] = None,
        policy_rules: Optional[list[str]] = None,
        detector: str = "toacd_security_layer",
        detector_version: str = "1.0.0",
        policy_version: str = "1.0.0",
    ) -> "SecurityEvent":
        """Factory method that generates deterministic event_id."""
        rules = list(policy_rules) if policy_rules else []
        # Redact/truncate evidence to avoid unbounded size or secret persistence
        safe_evidence = evidence[:512] if evidence else ""

        # Deterministic hashing inputs (excluding created_at)
        h_payload = (
            f"{sequence}:{threat_domain.value}:{attack_type.value}:{source.value}:"
            f"{risk_level.value}:{score}:{round(confidence, 4)}:{safe_evidence}:"
            f"{action_attempted.value}:{action_taken.value}:{blocked}:{reason}:"
            f"{affected_run_id}:{affected_artifact_id}:{','.join(sorted(rules))}:"
            f"{detector}:{detector_version}:{policy_version}"
        )
        digest = hashlib.sha256(h_payload.encode("utf-8")).hexdigest()[:16]
        event_id = f"sec_evt_{sequence:04d}_{digest}"

        return cls(
            event_id=event_id,
            sequence=sequence,
            created_at=created_at,
            schema_version=SECEVENT_SCHEMA_VERSION,
            threat_domain=threat_domain,
            attack_type=attack_type,
            source=source,
            risk_level=risk_level,
            score=int(score),
            confidence=float(confidence),
            evidence=safe_evidence,
            action_attempted=action_attempted,
            action_taken=action_taken,
            blocked=blocked,
            reason=reason,
            affected_run_id=affected_run_id,
            affected_artifact_id=affected_artifact_id,
            policy_rules=rules,
            detector=detector,
            detector_version=detector_version,
            policy_version=policy_version,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "threat_domain": self.threat_domain.value if isinstance(self.threat_domain, ThreatDomain) else str(self.threat_domain),
            "attack_type": self.attack_type.value if isinstance(self.attack_type, AttackType) else str(self.attack_type),
            "source": self.source.value if isinstance(self.source, EventSource) else str(self.source),
            "risk_level": self.risk_level.value if isinstance(self.risk_level, RiskLevel) else str(self.risk_level),
            "score": self.score,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "action_attempted": self.action_attempted.value if isinstance(self.action_attempted, ActionAttempted) else str(self.action_attempted),
            "action_taken": self.action_taken.value if isinstance(self.action_taken, ActionTaken) else str(self.action_taken),
            "blocked": self.blocked,
            "reason": self.reason,
            "affected_run_id": self.affected_run_id,
            "affected_artifact_id": self.affected_artifact_id,
            "policy_rules": list(self.policy_rules),
            "detector": self.detector,
            "detector_version": self.detector_version,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SecurityEvent":
        """Deserialize from dictionary safely."""
        def _to_enum(enum_cls: Any, val: Any, default: Any) -> Any:
            if not val:
                return default
            try:
                return enum_cls(val)
            except ValueError:
                return default

        return cls(
            event_id=str(d.get("event_id", "")),
            sequence=int(d.get("sequence", 0)),
            created_at=str(d.get("created_at", "")),
            schema_version=str(d.get("schema_version", SECEVENT_SCHEMA_VERSION)),
            threat_domain=_to_enum(ThreatDomain, d.get("threat_domain"), ThreatDomain.AGENTIC_AI_SECURITY),
            attack_type=_to_enum(AttackType, d.get("attack_type"), AttackType.UNKNOWN_ATTACK),
            source=_to_enum(EventSource, d.get("source"), EventSource.L1_INPUT_SCREEN),
            risk_level=_to_enum(RiskLevel, d.get("risk_level"), RiskLevel.NONE),
            score=int(d.get("score", 0)),
            confidence=float(d.get("confidence", 0.0)),
            evidence=str(d.get("evidence", "")),
            action_attempted=_to_enum(ActionAttempted, d.get("action_attempted"), ActionAttempted.UNKNOWN_ACTION),
            action_taken=_to_enum(ActionTaken, d.get("action_taken"), ActionTaken.BLOCK),
            blocked=bool(d.get("blocked", True)),
            reason=str(d.get("reason", "")),
            affected_run_id=d.get("affected_run_id"),
            affected_artifact_id=d.get("affected_artifact_id"),
            policy_rules=list(d.get("policy_rules") or []),
            detector=str(d.get("detector", "toacd_security_layer")),
            detector_version=str(d.get("detector_version", "1.0.0")),
            policy_version=str(d.get("policy_version", "1.0.0")),
        )
