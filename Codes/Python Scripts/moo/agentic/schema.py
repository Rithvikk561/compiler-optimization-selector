"""
TOACD — Week 12: Real-Time Agentic AI Analysis — Schemas
=========================================================
Defines immutable data models, enums, and serialization helpers for the
deterministic, bounded, advisory-only agentic analysis layer.

Scope Guard:
- Week 12 only.
- No PyTorch dependencies.
- No GUI dependencies.
- Advisory only: never modifies compiler flags or selected strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

AGENTIC_SCHEMA_VERSION = "week12.1.0"


class EvidenceTier(str, Enum):
    """Explicit optional evidence tiers available for agentic reasoning."""
    TIER_1_STATIC_SELECTION = "TIER_1_STATIC_SELECTION"    # Static IR profile + DecisionTrace
    TIER_2_HISTORICAL_EXPERIENCE = "TIER_2_HISTORICAL_EXPERIENCE"  # Past ExperienceRecords for same source_hash
    TIER_3_EMPIRICAL_BENCHMARK = "TIER_3_EMPIRICAL_BENCHMARK"      # Empirical ProgramComparison / Regression metrics


class EvidenceQuality(str, Enum):
    """Categorical quality assessment of the available evidence."""
    HIGH = "HIGH"               # T1 + T2 + T3 present with conclusive, reliable empirical measurements
    MEDIUM = "MEDIUM"           # T1 + reliable T2 or reliable T3
    LOW = "LOW"                 # T1 only, or higher tiers present but high noise / small sample / inconclusive
    INSUFFICIENT = "INSUFFICIENT" # Essential T1 inputs missing or unreadable


class AgentVerdict(str, Enum):
    """Advisory verdict produced by the agentic analysis engine."""
    CONFIRMED = "CONFIRMED"                             # Optimization selection verified sound
    CONFIRMED_WITH_WARNINGS = "CONFIRMED_WITH_WARNINGS" # Sound, but notable tradeoffs or noise present
    ALTERNATIVE_ADVISED = "ALTERNATIVE_ADVISED"         # Strict evidence supports superior alternative
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"     # Data too sparse or malformed to reach a definitive verdict


class FindingSeverity(str, Enum):
    """Severity level of an individual analytical finding."""
    INFO = "INFO"
    WARNING = "WARNING"
    ALERT = "ALERT"


@dataclass(frozen=True)
class Finding:
    """An individual analytical observation produced by an agent tool."""
    category: str               # e.g., "PROVENANCE", "NOISE", "IR_PROFILE", "REGRESSION", "TRADEOFF", "DATA_GAP"
    severity: FindingSeverity
    message: str
    evidence_tier: EvidenceTier
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "message": self.message,
            "evidence_tier": self.evidence_tier.value,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Finding:
        return cls(
            category=str(d.get("category", "UNKNOWN")),
            severity=FindingSeverity(d.get("severity", FindingSeverity.INFO.value)),
            message=str(d.get("message", "")),
            evidence_tier=EvidenceTier(d.get("evidence_tier", EvidenceTier.TIER_1_STATIC_SELECTION.value)),
            details=dict(d.get("details", {})),
        )


@dataclass(frozen=True)
class TradeoffAlert:
    """Explicit multi-objective conflict or tradeoff detection."""
    objective_favored: str      # e.g., "execution_time"
    objective_degraded: str     # e.g., "code_size"
    ratio: float                # degraded metric ratio against baseline
    threshold: float            # trigger threshold
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_favored": self.objective_favored,
            "objective_degraded": self.objective_degraded,
            "ratio": float(self.ratio),
            "threshold": float(self.threshold),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TradeoffAlert:
        return cls(
            objective_favored=str(d.get("objective_favored", "")),
            objective_degraded=str(d.get("objective_degraded", "")),
            ratio=float(d.get("ratio", 1.0)),
            threshold=float(d.get("threshold", 1.0)),
            description=str(d.get("description", "")),
        )


@dataclass(frozen=True)
class AlternativeRecommendation:
    """Strictly constrained advisory alternative compiler strategy."""
    strategy: str                         # Valid action in ACTIONS, != selected_strategy
    justification: str                    # Explicit rule name and reasoning
    numerical_evidence: Dict[str, float]  # Empirical deltas supporting recommendation
    pareto_verified: bool                 # Verified on Pareto frontier if frontier was available
    is_advisory_only: bool = True         # Always True — never overrides pipeline

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "justification": self.justification,
            "numerical_evidence": dict(self.numerical_evidence),
            "pareto_verified": bool(self.pareto_verified),
            "is_advisory_only": True,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AlternativeRecommendation:
        return cls(
            strategy=str(d.get("strategy", "")),
            justification=str(d.get("justification", "")),
            numerical_evidence={k: float(v) for k, v in d.get("numerical_evidence", {}).items()},
            pareto_verified=bool(d.get("pareto_verified", False)),
            is_advisory_only=True,
        )


@dataclass(frozen=True)
class StepRecord:
    """Trace record of a single step in the bounded agentic loop."""
    step_number: int
    tool_name: str
    action_reason: str
    findings_produced: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": int(self.step_number),
            "tool_name": self.tool_name,
            "action_reason": self.action_reason,
            "findings_produced": int(self.findings_produced),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> StepRecord:
        return cls(
            step_number=int(d.get("step_number", 0)),
            tool_name=str(d.get("tool_name", "")),
            action_reason=str(d.get("action_reason", "")),
            findings_produced=int(d.get("findings_produced", 0)),
        )


@dataclass(frozen=True)
class AgentContext:
    """Immutable input context supplied to the agentic engine."""
    program_id: str
    source_hash: str
    selected_strategy: str
    tiers_available: List[EvidenceTier]
    decision_trace: Optional[Dict[str, Any]] = None
    program_profile: Optional[Dict[str, Any]] = None
    historical_experiences: List[Dict[str, Any]] = field(default_factory=list)
    program_comparison: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "program_id": self.program_id,
            "source_hash": self.source_hash,
            "selected_strategy": self.selected_strategy,
            "tiers_available": [t.value for t in self.tiers_available],
            "decision_trace": dict(self.decision_trace) if self.decision_trace else None,
            "program_profile": dict(self.program_profile) if self.program_profile else None,
            "historical_experiences": [dict(e) for e in self.historical_experiences],
            "program_comparison": dict(self.program_comparison) if self.program_comparison else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AgentAnalysisReport:
    """Complete advisory report generated by the Week 12 agentic analysis engine."""
    report_id: str
    program_id: str
    source_hash: str
    selected_strategy: str
    verdict: AgentVerdict
    evidence_quality: EvidenceQuality
    tiers_available: List[EvidenceTier]
    findings: List[Finding]
    tradeoffs: List[TradeoffAlert]
    alternative: Optional[AlternativeRecommendation]
    reasoning_steps: List[StepRecord]
    is_advisory_only: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = AGENTIC_SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "program_id": self.program_id,
            "source_hash": self.source_hash,
            "selected_strategy": self.selected_strategy,
            "verdict": self.verdict.value,
            "evidence_quality": self.evidence_quality.value,
            "tiers_available": [t.value for t in self.tiers_available],
            "findings": [f.to_dict() for f in self.findings],
            "tradeoffs": [t.to_dict() for t in self.tradeoffs],
            "alternative": self.alternative.to_dict() if self.alternative else None,
            "reasoning_steps": [s.to_dict() for s in self.reasoning_steps],
            "is_advisory_only": True,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AgentAnalysisReport:
        return cls(
            schema_version=str(d.get("schema_version", AGENTIC_SCHEMA_VERSION)),
            report_id=str(d.get("report_id", "")),
            program_id=str(d.get("program_id", "")),
            source_hash=str(d.get("source_hash", "")),
            selected_strategy=str(d.get("selected_strategy", "")),
            verdict=AgentVerdict(d.get("verdict", AgentVerdict.INSUFFICIENT_EVIDENCE.value)),
            evidence_quality=EvidenceQuality(d.get("evidence_quality", EvidenceQuality.INSUFFICIENT.value)),
            tiers_available=[EvidenceTier(t) for t in d.get("tiers_available", [])],
            findings=[Finding.from_dict(f) for f in d.get("findings", [])],
            tradeoffs=[TradeoffAlert.from_dict(t) for t in d.get("tradeoffs", [])],
            alternative=AlternativeRecommendation.from_dict(d["alternative"]) if d.get("alternative") else None,
            reasoning_steps=[StepRecord.from_dict(s) for s in d.get("reasoning_steps", [])],
            is_advisory_only=True,
            metadata=dict(d.get("metadata", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> AgentAnalysisReport:
        return cls.from_dict(json.loads(json_str))
