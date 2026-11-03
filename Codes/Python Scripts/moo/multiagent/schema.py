"""
moo.multiagent.schema — Structured Message Protocol for TOACD Multi-Agent System.

Defines immutable AgentMessage envelopes, standard MessageTypes, and AgentRole constants.
Guarantees clean serialization and deserialization for observability, verification,
and downstream UI integration.
"""

from __future__ import annotations

import dataclasses
import datetime
import uuid
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Message Types (Canonical Protocol Constants)
# ---------------------------------------------------------------------------
class MessageType(str, Enum):
    MSG_IR_FEATURES       = "IR_FEATURES"        # CodeAnalyst -> Orchestrator / Downstream
    MSG_PROFILE           = "PROFILE"            # ProgramProfiling -> Orchestrator / Downstream
    MSG_STRATEGY_PROPOSAL = "STRATEGY_PROPOSAL"  # OptimizationStrategist -> OptimizationReviewer
    MSG_REVIEW_ACCEPT     = "REVIEW_ACCEPT"      # OptimizationReviewer -> Orchestrator / Strategist
    MSG_REVIEW_REJECT     = "REVIEW_REJECT"      # OptimizationReviewer -> OptimizationStrategist (Feedback)
    MSG_STRATEGY_REVISED  = "STRATEGY_REVISED"   # OptimizationStrategist -> OptimizationReviewer (Revision)
    MSG_BENCHMARK_RESULT  = "BENCHMARK_RESULT"   # BenchmarkAgent -> Orchestrator
    MSG_FINAL_DECISION    = "FINAL_DECISION"     # FinalDecisionAgent -> Orchestrator
    MSG_ERROR             = "ERROR"              # Any Agent -> Orchestrator


# Standard String Aliases
MSG_IR_FEATURES       = MessageType.MSG_IR_FEATURES.value
MSG_PROFILE           = MessageType.MSG_PROFILE.value
MSG_STRATEGY_PROPOSAL = MessageType.MSG_STRATEGY_PROPOSAL.value
MSG_REVIEW_ACCEPT     = MessageType.MSG_REVIEW_ACCEPT.value
MSG_REVIEW_REJECT     = MessageType.MSG_REVIEW_REJECT.value
MSG_STRATEGY_REVISED  = MessageType.MSG_STRATEGY_REVISED.value
MSG_BENCHMARK_RESULT  = MessageType.MSG_BENCHMARK_RESULT.value
MSG_FINAL_DECISION    = MessageType.MSG_FINAL_DECISION.value
MSG_ERROR             = MessageType.MSG_ERROR.value


# ---------------------------------------------------------------------------
# Agent Role Constants
# ---------------------------------------------------------------------------
ROLE_ORCHESTRATOR           = "ORCHESTRATOR"
ROLE_CODE_ANALYST           = "CodeAnalystAgent"
ROLE_PROGRAM_PROFILING      = "ProgramProfilingAgent"
ROLE_OPTIMIZATION_STRATEGIST = "OptimizationStrategistAgent"
ROLE_OPTIMIZATION_REVIEWER  = "OptimizationReviewerAgent"
ROLE_BENCHMARK              = "BenchmarkAgent"
ROLE_FINAL_DECISION         = "FinalDecisionAgent"


# ---------------------------------------------------------------------------
# Agent Message Envelope
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class AgentMessage:
    """
    Structured message exchanged between specialized agents in the TOACD platform.

    Fields:
      message_id   : Unique identifier for this message
      sender       : Name/role of sending agent
      recipient    : Name/role of intended recipient agent or ORCHESTRATOR
      message_type : Canonical MessageType string
      payload      : Structured data content (JSON-serializable dict)
      run_id       : Pipeline execution run identifier for correlation
      step         : Monotonically increasing execution sequence number
      timestamp    : ISO-8601 formatted UTC timestamp
    """
    message_id: str
    sender: str
    recipient: str
    message_type: str
    payload: Dict[str, Any]
    run_id: str
    step: int
    timestamp: str

    @classmethod
    def create(
        cls,
        sender: str,
        recipient: str,
        message_type: str | MessageType,
        payload: Dict[str, Any],
        run_id: str,
        step: int,
        message_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> AgentMessage:
        """Helper to create an AgentMessage with defaults for ID and timestamp."""
        m_id = message_id or str(uuid.uuid4())
        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        m_type = message_type.value if isinstance(message_type, MessageType) else str(message_type)
        return cls(
            message_id=m_id,
            sender=str(sender),
            recipient=str(recipient),
            message_type=m_type,
            payload=dict(payload),
            run_id=str(run_id),
            step=int(step),
            timestamp=ts,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "message_id": self.message_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_type": self.message_type,
            "payload": dict(self.payload),
            "run_id": self.run_id,
            "step": self.step,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AgentMessage:
        """Construct an AgentMessage from a dictionary."""
        return cls(
            message_id=str(d.get("message_id", "")),
            sender=str(d.get("sender", "")),
            recipient=str(d.get("recipient", "")),
            message_type=str(d.get("message_type", "")),
            payload=dict(d.get("payload") or {}),
            run_id=str(d.get("run_id", "")),
            step=int(d.get("step", 0)),
            timestamp=str(d.get("timestamp", "")),
        )
