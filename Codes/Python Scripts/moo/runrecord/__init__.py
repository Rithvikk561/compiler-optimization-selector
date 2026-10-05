"""
moo/runrecord — Canonical RunRecord layer for TOACD pipeline integration.

RunRecord is the single, authoritative data structure that represents one
complete or partial optimization/compilation run through the TOACD pipeline.

Architecture
------------
  ACTUAL PROGRAM RUN
        ↓
  PROGRAM FEATURES / PROFILE
        ↓
  OPTIMIZATION SELECTION
        ↓
  DECISION TRACE / XAI / PROVENANCE
        ↓
  COMPILATION + BENCHMARK MEASUREMENTS
        ↓
  CANONICAL RunRecord
        ↓
   ┌──────────┬────────────┬──────────────┬──────────────┐
   ↓          ↓            ↓              ↓
Regression  Adaptive     Agentic        Security
Comparison  Learning      AI             Analysis

Scope Guard
-----------
- Week 8–12 only: pipeline bridge, NOT Week 13+ features.
- RunRecord is ADVISORY infrastructure. It does NOT override any selection.
- Agentic AI remains advisory-only.
- Adaptive learning remains advisory/update-only.
- No network/cloud/LLM/database dependencies.
- No background daemons or async monitoring.
"""

from .schema import (
    RunRecord,
    RunStatus,
    MeasurementStatus,
    SelectionProvenance,
    RUNRECORD_SCHEMA_VERSION,
)
from .builder import RunRecordBuilder
from .projections import (
    to_regression_input,
    to_experience_record,
    to_agent_context,
    to_gui_view,
)
from .orchestrator import PipelineOrchestrator

__week__ = "8-12_bridge"
__all__ = [
    "RunRecord",
    "RunStatus",
    "MeasurementStatus",
    "SelectionProvenance",
    "RUNRECORD_SCHEMA_VERSION",
    "RunRecordBuilder",
    "to_regression_input",
    "to_experience_record",
    "to_agent_context",
    "to_gui_view",
    "PipelineOrchestrator",
]
