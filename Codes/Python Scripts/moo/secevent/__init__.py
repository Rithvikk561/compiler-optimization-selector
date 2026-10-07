"""
moo.secevent — Shared Security Event and Risk Model for TOACD.

Provides deterministic security event schemas, deterministic risk calculation,
and resilient event logging.
"""

from .schema import (
    SECEVENT_SCHEMA_VERSION,
    ThreatDomain,
    AttackType,
    EventSource,
    RiskLevel,
    ActionAttempted,
    ActionTaken,
    SecurityEvent,
)
from .risk import (
    Signal,
    compute_risk_assessment,
    assess_decision,
)
from .log import (
    SecurityEventLog,
)

__all__ = [
    "SECEVENT_SCHEMA_VERSION",
    "ThreatDomain",
    "AttackType",
    "EventSource",
    "RiskLevel",
    "ActionAttempted",
    "ActionTaken",
    "SecurityEvent",
    "Signal",
    "compute_risk_assessment",
    "assess_decision",
    "SecurityEventLog",
]
