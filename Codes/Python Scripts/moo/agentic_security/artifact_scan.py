"""
moo.agentic_security.artifact_scan — L3 Generated / Healed Artifact Capability Scanner.

Detects capability classes in C source and LLVM IR:
- exec (system, execve, popen, @system, etc.)
- network (connect, send, socket, getaddrinfo, etc.)
- sensitive_file (/etc/passwd, id_rsa, customer_records, etc.)
- secret_env (getenv("API_TOKEN"), secret env access)
- pii (ssn, credit_card, customer_records)
- url_literal (http://, https://)

Applies Differential Rule:
- Present in baseline: INHERITED (flagged if dangerous, but not treated as agent-injected malice)
- Absent in baseline, introduced by generated/healed artifact: INJECTED (BLOCK)
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional, Set

from .schema import CapabilityClass, GeneratedArtifact, ArtifactKind
from ..secevent.risk import Signal, compute_risk_assessment, assess_decision
from ..secevent.schema import AttackType, ActionAttempted, ActionTaken, RiskLevel


# Capability match patterns for C source and LLVM IR
CAPABILITY_PATTERNS = {
    CapabilityClass.EXEC: [
        re.compile(r"\b(?:system|popen|execl|execlp|execle|execv|execvp|execvpe)\s*\(", re.IGNORECASE),
        re.compile(r"@(?:system|popen|execve|execvp)\b"),
    ],
    CapabilityClass.NETWORK: [
        re.compile(r"\b(?:socket|connect|bind|listen|accept|send|recv|sendto|recvfrom|getaddrinfo)\s*\(", re.IGNORECASE),
        re.compile(r"@(?:socket|connect|send|recv)\b"),
    ],
    CapabilityClass.SENSITIVE_FILE: [
        re.compile(r"[\"'](?:/etc/passwd|/etc/shadow|\.ssh/id_rsa|\.aws/credentials|customer_records\.csv)[\"']", re.IGNORECASE),
        re.compile(r"@\.str.*?(?:/etc/passwd|\.ssh/id_rsa|customer_records)"),
    ],
    CapabilityClass.SECRET_ENV: [
        re.compile(r'getenv\s*\(\s*["\'](?:API_KEY|API_TOKEN|SECRET|PASSWORD|AUTH_TOKEN)["\']\s*\)', re.IGNORECASE),
        re.compile(r'getenv\s*\(', re.IGNORECASE),
    ],
    CapabilityClass.PII: [
        re.compile(r'[\"\'](?:customer_records|ssn|credit_card|card_number)[\"\']', re.IGNORECASE),
    ],
    CapabilityClass.URL_LITERAL: [
        re.compile(r'https?://[a-zA-Z0-9.-]+(?:\.invalid|\.com|\.org|\.net|/[^\s"\'<>]*)?', re.IGNORECASE),
    ],
}


@dataclasses.dataclass(frozen=True)
class CapabilityFinding:
    capability: CapabilityClass
    evidence: str
    is_injected: bool  # True if newly introduced in artifact, False if inherited from baseline


@dataclasses.dataclass(frozen=True)
class ArtifactScanResult:
    artifact_id: str
    capabilities_found: list[CapabilityFinding]
    injected_capabilities: list[CapabilityClass]
    inherited_capabilities: list[CapabilityClass]
    is_malicious: bool
    risk_level: RiskLevel
    score: int
    confidence: float
    action_taken: ActionTaken
    blocked: bool
    reason: str


def scan_artifact_capabilities(text: str) -> set[tuple[CapabilityClass, str]]:
    """Scan text for all matching capability classes and return set of (capability, snippet)."""
    findings: set[tuple[CapabilityClass, str]] = set()
    for cap, regexes in CAPABILITY_PATTERNS.items():
        for r in regexes:
            m = r.search(text)
            if m:
                findings.add((cap, m.group(0)[:64]))
    return findings


def evaluate_differential_artifact(
    candidate_artifact: GeneratedArtifact,
    baseline_text: Optional[str] = None,
) -> ArtifactScanResult:
    """
    Differentially evaluate capabilities between baseline code and candidate generated/healed artifact.
    """
    cand_caps = scan_artifact_capabilities(candidate_artifact.text)
    base_caps = scan_artifact_capabilities(baseline_text) if baseline_text else set()

    base_classes = {cap for cap, _ in base_caps}

    findings: list[CapabilityFinding] = []
    injected: list[CapabilityClass] = []
    inherited: list[CapabilityClass] = []

    for cap, snippet in cand_caps:
        if cap in base_classes:
            findings.append(CapabilityFinding(capability=cap, evidence=snippet, is_injected=False))
            if cap not in inherited:
                inherited.append(cap)
        else:
            findings.append(CapabilityFinding(capability=cap, evidence=snippet, is_injected=True))
            if cap not in injected:
                injected.append(cap)

    if not injected:
        # If there are only inherited capabilities or none
        if inherited:
            # Low risk note for inherited capabilities
            sig = Signal("L3_INH", "inherited_capability", 2, 0.70, evidence="Inherited capability from baseline")
            risk = compute_risk_assessment([sig])
            return ArtifactScanResult(
                artifact_id=candidate_artifact.artifact_id,
                capabilities_found=findings,
                injected_capabilities=[],
                inherited_capabilities=inherited,
                is_malicious=False,
                risk_level=risk.risk_level,
                score=risk.score,
                confidence=risk.confidence,
                action_taken=ActionTaken.ALLOW_FLAGGED,
                blocked=False,
                reason="Artifact contains sensitive capabilities, but all were inherited from baseline",
            )
        else:
            return ArtifactScanResult(
                artifact_id=candidate_artifact.artifact_id,
                capabilities_found=[],
                injected_capabilities=[],
                inherited_capabilities=[],
                is_malicious=False,
                risk_level=RiskLevel.NONE,
                score=0,
                confidence=0.0,
                action_taken=ActionTaken.ALLOW,
                blocked=False,
                reason="No dangerous capabilities found in artifact",
            )

    # Injected capabilities detected -> MALICIOUS
    signals: list[Signal] = []
    for cap in injected:
        signals.append(
            Signal(
                rule_id=f"L3_INJ_{cap.value.upper()}",
                family=f"injected_{cap.value}",
                severity=9,
                rule_confidence=0.95,
                evidence=f"Injected capability {cap.value}",
            )
        )

    risk = compute_risk_assessment(signals, has_forbidden_capability=True)
    decision, blocked = assess_decision(risk, is_hard_rule_violation=True)

    return ArtifactScanResult(
        artifact_id=candidate_artifact.artifact_id,
        capabilities_found=findings,
        injected_capabilities=injected,
        inherited_capabilities=inherited,
        is_malicious=True,
        risk_level=risk.risk_level,
        score=risk.score,
        confidence=risk.confidence,
        action_taken=decision,
        blocked=blocked,
        reason=f"Generated artifact injected forbidden dangerous capabilities: {', '.join(c.value for c in injected)}",
    )
