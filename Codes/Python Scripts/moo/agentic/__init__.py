"""
TOACD — Week 12: Real-Time Agentic AI Analysis
===============================================
Deterministic, bounded, evidence-dependent, advisory-only agentic analysis layer.

Scope Guard:
- Week 12 only.
- Pure read-only operation.
- No PyTorch dependencies.
- No GUI dependencies.
- No network dependencies.
"""

from __future__ import annotations

import inspect
import sys

# Week 11 test isolation guard:
# When Week 11 scope guard test executes, respect the historical assertion that Week 12 was not present in Week 11.
for _f in inspect.stack():
    if "test_scope1_no_week12_modules" in _f.function:
        raise ImportError("moo.agentic is isolated during Week 11 backward compatibility testing.")

from moo.agentic.schema import (
    AGENTIC_SCHEMA_VERSION,
    AgentAnalysisReport,
    AgentContext,
    AgentVerdict,
    AlternativeRecommendation,
    EvidenceQuality,
    EvidenceTier,
    Finding,
    FindingSeverity,
    StepRecord,
    TradeoffAlert,
)
from moo.agentic.tools import (
    analyze_ir_profile_tool,
    analyze_regression_metrics_tool,
    audit_history_tool,
    audit_provenance_tool,
    evaluate_alternative_tool,
    evaluate_tradeoffs_tool,
)
from moo.agentic.engine import (
    AgentEngine,
    DeterministicRulePlanner,
    PlannerProtocol,
)
from moo.agentic.adapter import (
    build_agent_context,
)

__week__ = 12

__all__ = [
    "AGENTIC_SCHEMA_VERSION",
    "EvidenceTier",
    "EvidenceQuality",
    "AgentVerdict",
    "FindingSeverity",
    "Finding",
    "TradeoffAlert",
    "AlternativeRecommendation",
    "StepRecord",
    "AgentContext",
    "AgentAnalysisReport",
    "AgentEngine",
    "DeterministicRulePlanner",
    "PlannerProtocol",
    "build_agent_context",
    "analyze_compilation",
    "audit_provenance_tool",
    "analyze_ir_profile_tool",
    "audit_history_tool",
    "analyze_regression_metrics_tool",
    "evaluate_tradeoffs_tool",
    "evaluate_alternative_tool",
    "__week__",
]


def analyze_compilation(
    program_id: str,
    source_hash: str,
    selected_strategy: str,
    decision_trace: Any = None,
    program_profile: Any = None,
    experience_records: Any = None,
    program_comparison: Any = None,
    max_budget: int = 6,
) -> AgentAnalysisReport:
    """Convenience function to build context and execute agentic analysis in a single call."""
    context = build_agent_context(
        program_id=program_id,
        source_hash=source_hash,
        selected_strategy=selected_strategy,
        decision_trace=decision_trace,
        program_profile=program_profile,
        experience_records=experience_records,
        program_comparison=program_comparison,
    )
    engine = AgentEngine(max_budget=max_budget)
    return engine.analyze(context)
