"""
moo/security — Core Secure Code Analysis subsystem for TOACD.

Provides standalone source scanning, LLVM IR parsing, sink recognition,
candidate IR evaluation, and optimization security gating.
"""

from .models import (
    CandidateSecurity,
    CandidateVerdict,
    GuardAssessment,
    GuardSink,
    GuardStatus,
    ModuleSinks,
    Severity,
    SinkClass,
    SourceFinding,
)
from .rules import (
    DEFAULT_SENTINELS,
    RULES,
    SENTINEL_FUNCTIONS,
    SourceRule,
    get_rule,
)
from .source_scan import (
    scan_source,
    scan_source_text,
)
from .ir_parse import (
    ParsedBlock,
    ParsedFunction,
    ParsedInstruction,
    ParsedModule,
    parse_llvm_ir,
)
from .sinks import (
    analyze_module_sinks,
    find_sinks,
)
from .candidate import (
    compute_candidate_verdict,
    evaluate_candidate_security,
)
from .gate import (
    GateDecision,
    GateResult,
    OptimizationSecurityGate,
)
from .ir_artifacts import (
    emit_baseline_ir,
    emit_candidate_ir,
)

__all__ = [
    "CandidateSecurity",
    "CandidateVerdict",
    "GuardAssessment",
    "GuardSink",
    "GuardStatus",
    "ModuleSinks",
    "ParsedBlock",
    "ParsedFunction",
    "ParsedInstruction",
    "ParsedModule",
    "Severity",
    "SinkClass",
    "SourceFinding",
    "SourceRule",
    "DEFAULT_SENTINELS",
    "RULES",
    "SENTINEL_FUNCTIONS",
    "analyze_module_sinks",
    "find_sinks",
    "get_rule",
    "parse_llvm_ir",
    "scan_source",
    "scan_source_text",
    "compute_candidate_verdict",
    "evaluate_candidate_security",
    "GateDecision",
    "GateResult",
    "OptimizationSecurityGate",
    "emit_baseline_ir",
    "emit_candidate_ir",
]
