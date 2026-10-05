"""
TOACD — Week 12: Real-Time Agentic AI Analysis — Adapter & Context Builder
===========================================================================
Defensive adapter that builds immutable AgentContext instances from heterogeneous
upstream Week 7–11 artifacts without mutating any upstream objects.

Scope Guard:
- Read-only: never modifies any inputs.
- Safe type conversion and tier resolution.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from moo.agentic.schema import AgentContext, EvidenceTier


def _safe_dict(obj: Any) -> Optional[Dict[str, Any]]:
    """Safely extracts a dictionary from an object or dictionary."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return copy.deepcopy(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return copy.deepcopy(obj.to_dict())
    return None


def build_agent_context(
    program_id: str,
    source_hash: str,
    selected_strategy: str,
    decision_trace: Optional[Any] = None,
    program_profile: Optional[Any] = None,
    experience_records: Optional[List[Any]] = None,
    program_comparison: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentContext:
    """
    Builds a validated, immutable AgentContext from upstream objects.
    
    Automatically determines available evidence tiers:
    - TIER_1_STATIC_SELECTION: if decision_trace or program_profile is present
    - TIER_2_HISTORICAL_EXPERIENCE: if experience_records is non-empty
    - TIER_3_EMPIRICAL_BENCHMARK: if program_comparison is present
    """
    trace_dict = _safe_dict(decision_trace)
    profile_dict = _safe_dict(program_profile)
    comparison_dict = _safe_dict(program_comparison)

    experiences_list: List[Dict[str, Any]] = []
    if experience_records:
        for rec in experience_records:
            d = _safe_dict(rec)
            if d is not None:
                experiences_list.append(d)

    # Resolve evidence tiers
    tiers: List[EvidenceTier] = []
    if trace_dict is not None or profile_dict is not None:
        tiers.append(EvidenceTier.TIER_1_STATIC_SELECTION)

    if experiences_list:
        tiers.append(EvidenceTier.TIER_2_HISTORICAL_EXPERIENCE)

    if comparison_dict is not None:
        tiers.append(EvidenceTier.TIER_3_EMPIRICAL_BENCHMARK)

    return AgentContext(
        program_id=str(program_id or ""),
        source_hash=str(source_hash or ""),
        selected_strategy=str(selected_strategy or ""),
        tiers_available=tiers,
        decision_trace=trace_dict,
        program_profile=profile_dict,
        historical_experiences=experiences_list,
        program_comparison=comparison_dict,
        metadata=copy.deepcopy(metadata or {}),
    )
