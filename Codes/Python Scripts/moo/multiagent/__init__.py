"""
moo.multiagent — Genuine Multi-Agent AI Communication Package for TOACD.

Coordinates specialized domain agents through structured, typed message exchange:
- CodeAnalystAgent
- ProgramProfilingAgent
- OptimizationStrategistAgent
- OptimizationReviewerAgent
- BenchmarkAgent
- FinalDecisionAgent

Under the supervision of MultiAgentOrchestrator.
"""

from __future__ import annotations

from .schema import (
    AgentMessage,
    MessageType,
    ROLE_CODE_ANALYST,
    ROLE_PROGRAM_PROFILING,
    ROLE_OPTIMIZATION_STRATEGIST,
    ROLE_OPTIMIZATION_REVIEWER,
    ROLE_BENCHMARK,
    ROLE_FINAL_DECISION,
    ROLE_ORCHESTRATOR,
    MSG_IR_FEATURES,
    MSG_PROFILE,
    MSG_STRATEGY_PROPOSAL,
    MSG_REVIEW_ACCEPT,
    MSG_REVIEW_REJECT,
    MSG_STRATEGY_REVISED,
    MSG_BENCHMARK_RESULT,
    MSG_FINAL_DECISION,
    MSG_ERROR,
)
from .message_log import MessageLog
from .agents import (
    BaseAgent,
    CodeAnalystAgent,
    ProgramProfilingAgent,
    OptimizationStrategistAgent,
    OptimizationReviewerAgent,
    BenchmarkAgent,
    FinalDecisionAgent,
)
from .orchestrator import MultiAgentOrchestrator

__all__ = [
    "AgentMessage",
    "MessageType",
    "ROLE_CODE_ANALYST",
    "ROLE_PROGRAM_PROFILING",
    "ROLE_OPTIMIZATION_STRATEGIST",
    "ROLE_OPTIMIZATION_REVIEWER",
    "ROLE_BENCHMARK",
    "ROLE_FINAL_DECISION",
    "ROLE_ORCHESTRATOR",
    "MSG_IR_FEATURES",
    "MSG_PROFILE",
    "MSG_STRATEGY_PROPOSAL",
    "MSG_REVIEW_ACCEPT",
    "MSG_REVIEW_REJECT",
    "MSG_STRATEGY_REVISED",
    "MSG_BENCHMARK_RESULT",
    "MSG_FINAL_DECISION",
    "MSG_ERROR",
    "MessageLog",
    "BaseAgent",
    "CodeAnalystAgent",
    "ProgramProfilingAgent",
    "OptimizationStrategistAgent",
    "OptimizationReviewerAgent",
    "BenchmarkAgent",
    "FinalDecisionAgent",
    "MultiAgentOrchestrator",
]
