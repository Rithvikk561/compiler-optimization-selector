"""
web.events — Canonical event envelope and workflow stage registry for TOACD.

Provides:
- Shared, versioned EventEnvelope schema (schema_version="events.1.0")
- Canonical PipelineStage and StageStatus enumerations
- RunState lifecycle enumeration
- Validation rules for event identity, monotonic sequences, and ISO timestamps
- SSE chunk serialization with standard id: field
"""

from __future__ import annotations

import dataclasses
import datetime
import json
from enum import Enum
from typing import Any, Dict, Optional, Tuple, List, Union


SCHEMA_VERSION = "events.1.0"


# ---------------------------------------------------------------------------
# Lifecycle and Stage Enumerations
# ---------------------------------------------------------------------------

class RunState(str, Enum):
    """
    Authoritative lifecycle states of an execution run.
    """
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class PipelineStage(str, Enum):
    """
    Canonical workflow stages matching the TOACD multi-agent compiler pipeline.
    """
    PROFILING = "profiling"
    STRATEGY_SELECTION = "strategy_selection"
    AGENT_REVIEW = "agent_review"
    SECURITY_VERIFICATION = "security_verification"
    BENCHMARKING = "benchmarking"
    REGRESSION_ANALYSIS = "regression_analysis"


class StageStatus(str, Enum):
    """
    Status of an individual workflow stage transition.
    """
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class EventType(str, Enum):
    """
    Canonical event types emitted over the SSE streaming infrastructure.
    """
    AGENT_MESSAGE = "agent_message"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_BLOCKED = "stage_blocked"
    STAGE_SKIPPED = "stage_skipped"
    DONE = "done"
    ERROR = "error"


class CursorStatus(str, Enum):
    """
    Validation status for Last-Event-ID or reconnection cursors.
    """
    NONE = "none"            # No cursor provided
    VALID = "valid"          # Syntactically matches run and found in event log
    UNKNOWN = "unknown"      # Syntactically matches run but not found in event log
    CROSS_RUN = "cross_run"  # Belongs to a different run
    MALFORMED = "malformed"  # Invalid format or unparseable string


def parse_event_id(event_id: str) -> Optional[Tuple[str, int]]:
    """
    Parse an event ID in canonical format: evt_<run_id>_<seq:04d>.
    Returns (run_id, seq) or None if malformed.
    """
    if not event_id or not isinstance(event_id, str):
        return None
    if not event_id.startswith("evt_"):
        return None
    body = event_id[4:]
    run_id, sep, seq_str = body.rpartition("_")
    if not sep or not run_id or not seq_str.isdigit():
        return None
    seq = int(seq_str)
    if seq < 1:
        return None
    return run_id, seq


def validate_cursor(
    cursor: Optional[str],
    expected_run_id: str,
    known_event_ids: Optional[List[str]] = None,
) -> Tuple[CursorStatus, Optional[int]]:
    """
    Validate a cursor (Last-Event-ID) against the expected run ID and optional known event IDs.

    Returns:
        (CursorStatus, seq_number)
    """
    if not cursor:
        return CursorStatus.NONE, None

    parsed = parse_event_id(cursor)
    if parsed is None:
        return CursorStatus.MALFORMED, None

    run_id, seq = parsed
    if run_id != expected_run_id:
        return CursorStatus.CROSS_RUN, None

    if known_event_ids is not None:
        if cursor in known_event_ids:
            return CursorStatus.VALID, seq
        else:
            return CursorStatus.UNKNOWN, seq

    return CursorStatus.VALID, seq


# ---------------------------------------------------------------------------
# Canonical Event Envelope
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class EventEnvelope:
    """
    Canonical, validated event envelope for run-scoped events.

    Attributes:
        schema_version : Version of the event envelope schema (e.g. "events.1.0")
        event_id       : Globally unique, stable identifier for this event (e.g. "evt_run123_0001")
        run_id         : Unique execution run identifier
        program_id     : Program identity (benchmark id or custom hash)
        seq            : 1-based strictly monotonic sequence counter within the run
        timestamp      : ISO-8601 UTC timestamp string
        event_type     : Canonical EventType string
        stage          : Optional PipelineStage string associated with this event
        status         : Current run or stage status string
        payload        : JSON-serializable dictionary containing technical details
    """
    schema_version: str
    event_id: str
    run_id: str
    program_id: str
    seq: int
    timestamp: str
    event_type: str
    stage: Optional[str] = None
    status: Optional[str] = None
    payload: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def validate(self) -> None:
        """
        Validate envelope fields and raise ValueError if any requirement is violated.
        """
        if not self.schema_version or not isinstance(self.schema_version, str):
            raise ValueError("schema_version must be a non-empty string")
        if not self.event_id or not isinstance(self.event_id, str):
            raise ValueError("event_id must be a non-empty string")
        if not self.run_id or not isinstance(self.run_id, str):
            raise ValueError("run_id must be a non-empty string")
        if not self.program_id or not isinstance(self.program_id, str):
            raise ValueError("program_id must be a non-empty string")
        if not isinstance(self.seq, int) or self.seq < 1:
            raise ValueError(f"seq must be an integer >= 1, got {self.seq!r}")
        if not self.timestamp or not isinstance(self.timestamp, str):
            raise ValueError("timestamp must be a valid ISO-8601 string")
        if not self.event_type or not isinstance(self.event_type, str):
            raise ValueError("event_type must be a non-empty string")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a dictionary")

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to JSON-serializable dictionary."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "program_id": self.program_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "stage": self.stage,
            "status": self.status,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventEnvelope:
        """Construct and validate EventEnvelope from dictionary."""
        envelope = cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            event_id=str(data.get("event_id", "")),
            run_id=str(data.get("run_id", "")),
            program_id=str(data.get("program_id", "")),
            seq=int(data.get("seq", 0)),
            timestamp=str(data.get("timestamp", "")),
            event_type=str(data.get("event_type", data.get("type", ""))),
            stage=data.get("stage"),
            status=data.get("status"),
            payload=dict(data.get("payload", {})),
        )
        envelope.validate()
        return envelope

    def to_sse_chunk(self) -> str:
        """
        Format event as a compliant SSE message chunk with standard id: field.
        """
        payload_json = json.dumps(self.to_dict(), default=str)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {payload_json}\n\n"
