"""
moo/security/models.py — Data models for the Secure Code Analysis subsystem.

Contains enums and dataclasses for source findings, LLVM IR guard sinks,
and optimization security assessments.

Chunk 1 hardening (6 MUST-FIX):
  #3  is_guarded is now Optional[bool]:
        True  = proven conditionally guarded
        False = proven unconditional
        None  = unknown / cannot determine safely
      Unknown MUST NOT be treated as guarded.

  #4  provably_dead_at_baseline is backed by real constant-fold + reachability.

  #5  Provenance: GuardSink gains origin_function, source_line, inlined,
      ir_line, ordinal.  Provenance enum DIRECT/INLINED/CLONE/NONE.
      ModuleSinks gains provenance_available.
      GuardStatus and Provenance are SEPARATE dimensions.

  #6  GuardSink gains canonical_text (metadata-stripped instruction text)
      and ordinal for stable cross-opt-level identity.
      Sink IDs are module-local only — document that clearly.
"""

from __future__ import annotations

import dataclasses
import re
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SinkClass(str, Enum):
    """Classification of a security sink in LLVM IR."""
    FLAG_STORE = "FLAG_STORE"
    ABORT_CALL = "ABORT_CALL"
    ASSERT_CALL = "ASSERT_CALL"
    TRAP = "TRAP"


class GuardStatus(str, Enum):
    """
    Preservation status of a specific security guard in an optimized build.

    NOTE: This is a DIFFERENT dimension from Provenance.
    GuardStatus describes what happened to the guard semantically across
    optimization levels.  Provenance describes where the IR instruction
    originated (direct source, inlined call, clone, or unknown).
    """
    PRESERVED = "PRESERVED"
    MERGED = "MERGED"
    FOLDED = "FOLDED"
    ELIMINATED = "ELIMINATED"
    UNKNOWN = "UNKNOWN"


class Provenance(str, Enum):
    """
    Origin provenance of a GuardSink instruction.

    NOTE: This is a DIFFERENT dimension from GuardStatus.
    Provenance describes where the IR came from; GuardStatus describes
    what optimization did to the guard semantics.

    DIRECT   — instruction directly corresponds to a source-level guard in
                the same function (no inlining).
    INLINED  — instruction was inlined from a callee into this function
                (debug metadata shows inlinedAt pointing to a different scope).
    CLONE    — instruction appears in a cloned/specialized version of a
                function (e.g. loop unrolling, SCC cloning).
    NONE     — provenance could not be determined (debug metadata absent).
    """
    DIRECT = "DIRECT"
    INLINED = "INLINED"
    CLONE = "CLONE"
    NONE = "NONE"


class CandidateVerdict(str, Enum):
    """Overall security verdict for a candidate optimization strategy."""
    PRESERVED = "PRESERVED"
    REDUCED = "REDUCED"
    ELIMINATED = "ELIMINATED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class Severity(str, Enum):
    """Severity level of a finding or warning."""
    INFO = "INFO"
    NOTE = "NOTE"
    WARNING = "WARNING"


# ---------------------------------------------------------------------------
# Canonical text helper (Fix #6)
# ---------------------------------------------------------------------------

# LLVM metadata references are unstable between opt levels (e.g. !tbaa !11 vs !tbaa !10).
# Strip them to produce stable canonical instruction text for cross-version identity.
_META_REF_RE = re.compile(r",?\s*!\w+\s*!\d+")


def _canonicalize(instruction_text: str) -> str:
    """
    Remove unstable LLVM metadata references from an instruction line.

    Strips annotations like ``!tbaa !11``, ``!llvm.loop !5``, etc.
    Does NOT remove meaningful operands or type information.

    Example:
        "store i32 1, ptr @assert_failed, align 4, !tbaa !10"
        -> "store i32 1, ptr @assert_failed, align 4"
    """
    return _META_REF_RE.sub("", instruction_text.strip()).rstrip(",").strip()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class SourceFinding:
    """A finding detected during C source scanning (guard or hazard)."""
    rule_id: str
    category: str                           # "GUARD" or "HAZARD"
    line_number: int
    matched_text: str
    function_name: Optional[str] = None
    cwe_primary: str = ""
    cwe_consequences: list[str] = dataclasses.field(default_factory=list)
    severity: Severity = Severity.NOTE
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "line_number": self.line_number,
            "matched_text": self.matched_text,
            "function_name": self.function_name,
            "cwe_primary": self.cwe_primary,
            "cwe_consequences": list(self.cwe_consequences),
            "severity": self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "details": self.details,
        }


@dataclasses.dataclass
class GuardSink:
    """
    A security sink recognized inside parsed LLVM IR.

    Identity notes (Fix #6):
      ``sink_id`` is a module-local identifier only.  It MUST NOT be relied
      upon as a stable cross-version or cross-optimization-level identity.
      Use (function_name, ordinal) or canonical_text for cross-opt comparison.

    Provenance notes (Fix #5):
      GuardStatus and Provenance are SEPARATE dimensions; see their enum docs.
      When debug metadata is absent, provenance fields are None and the parent
      ModuleSinks.provenance_available will be False.

    Guardedness notes (Fix #3):
      is_guarded is Optional[bool]:
        True  = proven conditionally guarded (requires passing through a
                conditional branch to reach this block)
        False = proven unconditionally reachable from entry without any
                conditional branch
        None  = unknown — CFG analysis could not determine; treat
                conservatively (do NOT assume guarded)
    """
    # Core identity
    sink_id: str                            # module-local only — NOT stable across opt levels
    sink_class: SinkClass
    function_name: str
    basic_block: str

    # Instruction content
    instruction_text: str                   # raw instruction text (may contain metadata)
    canonical_text: str = ""               # Fix #6: metadata-stripped stable text

    # Semantic fields
    target_symbol: Optional[str] = None
    constant_value: Optional[int] = None

    # Fix #3: tri-state guardedness
    is_guarded: Optional[bool] = None      # True=guarded, False=unconditional, None=unknown

    guard_condition: Optional[str] = None

    # Fix #4: provably dead at baseline
    provably_dead_at_baseline: bool = False

    details: str = ""

    # Fix #6: stable ordering / identity
    ir_line: int = 0                       # 1-based line in the IR file
    ordinal: int = 0                       # 1-based sink ordinal in IR order (stable)

    # Fix #5: provenance
    origin_function: Optional[str] = None  # function where guard originated in source
    source_line: Optional[int] = None      # source line from debug metadata
    inlined: Optional[bool] = None         # True if inlined from another function
    provenance: Optional[Provenance] = None  # DIRECT/INLINED/CLONE/NONE

    def __post_init__(self) -> None:
        # Auto-compute canonical_text if not provided
        if not self.canonical_text and self.instruction_text:
            self.canonical_text = _canonicalize(self.instruction_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            # module-local identity (not stable cross-opt)
            "sink_id": self.sink_id,
            "sink_class": self.sink_class.value if isinstance(self.sink_class, SinkClass) else str(self.sink_class),
            "function_name": self.function_name,
            "basic_block": self.basic_block,
            "instruction_text": self.instruction_text,
            "canonical_text": self.canonical_text,
            "target_symbol": self.target_symbol,
            "constant_value": self.constant_value,
            # Fix #3: tri-state (serialise None as null)
            "is_guarded": self.is_guarded,
            "guard_condition": self.guard_condition,
            "provably_dead_at_baseline": self.provably_dead_at_baseline,
            "details": self.details,
            # Fix #6: stable fields
            "ir_line": self.ir_line,
            "ordinal": self.ordinal,
            # Fix #5: provenance (separate dimension from GuardStatus)
            "origin_function": self.origin_function,
            "source_line": self.source_line,
            "inlined": self.inlined,
            "provenance": self.provenance.value if isinstance(self.provenance, Provenance) else self.provenance,
        }


@dataclasses.dataclass
class ModuleSinks:
    """
    All security sinks and structural metadata discovered in an LLVM IR module.

    Fix #1: parse_ok, defined_function_count, parsed_function_count track
            completeness.  parse_ok=False means parsing was incomplete; callers
            MUST NOT treat this as "no sinks".

    Fix #5: provenance_available indicates whether debug metadata was present
            and provenance fields on GuardSink instances are populated.
    """
    ir_path: Optional[str] = None
    sha256: Optional[str] = None
    producer: Optional[str] = None
    functions: list[str] = dataclasses.field(default_factory=list)
    callgraph: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    sinks: list[GuardSink] = dataclasses.field(default_factory=list)
    parse_warnings: list[str] = dataclasses.field(default_factory=list)

    # Fix #1: parse completeness
    parse_ok: bool = True
    defined_function_count: int = 0        # `define` directives seen in text
    parsed_function_count: int = 0         # functions successfully parsed

    # Fix #5: provenance availability
    provenance_available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ir_path": self.ir_path,
            "sha256": self.sha256,
            "producer": self.producer,
            "functions": list(self.functions),
            "callgraph": {k: list(v) for k, v in sorted(self.callgraph.items())},
            "sinks": [s.to_dict() for s in self.sinks],
            "parse_warnings": list(self.parse_warnings),
            # Fix #1
            "parse_ok": self.parse_ok,
            "defined_function_count": self.defined_function_count,
            "parsed_function_count": self.parsed_function_count,
            # Fix #5
            "provenance_available": self.provenance_available,
        }


@dataclasses.dataclass
class GuardAssessment:
    """Preservation assessment of an individual guard across optimization."""
    sink_id: str
    status: GuardStatus = GuardStatus.UNKNOWN
    details: str = ""
    notes: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sink_id": self.sink_id,
            "status": self.status.value if isinstance(self.status, GuardStatus) else str(self.status),
            "details": self.details,
            "notes": list(self.notes),
        }


@dataclasses.dataclass
class CandidateSecurity:
    """Security assessment summary for an optimization strategy candidate."""
    strategy_name: str
    verdict: CandidateVerdict = CandidateVerdict.UNKNOWN
    baseline_sink_count: int = 0
    candidate_sink_count: int = 0
    preserved_sinks: int = 0
    eliminated_sinks: int = 0
    merged_sinks: int = 0
    folded_sinks: int = 0
    guard_assessments: list[GuardAssessment] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "verdict": self.verdict.value if isinstance(self.verdict, CandidateVerdict) else str(self.verdict),
            "baseline_sink_count": self.baseline_sink_count,
            "candidate_sink_count": self.candidate_sink_count,
            "preserved_sinks": self.preserved_sinks,
            "eliminated_sinks": self.eliminated_sinks,
            "merged_sinks": self.merged_sinks,
            "folded_sinks": self.folded_sinks,
            "guard_assessments": [a.to_dict() for a in self.guard_assessments],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }
