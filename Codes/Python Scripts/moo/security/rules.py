"""
moo/security/rules.py — Rule definitions and registry for Secure Code Analysis.

Contains source-level security guard and hazard rules, CWE mappings,
and sentinel discovery configuration.
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Set

from .models import Severity


# ---------------------------------------------------------------------------
# Rule Data Structure
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class SourceRule:
    """Specification of a source-level guard or hazard rule."""
    rule_id: str
    category: str                           # "GUARD" or "HAZARD"
    name: str
    description: str
    cwe_primary: str
    cwe_consequences: tuple[str, ...]
    severity: Severity = Severity.NOTE


# ---------------------------------------------------------------------------
# Default Configuration Constants
# ---------------------------------------------------------------------------

DEFAULT_SENTINELS: frozenset[str] = frozenset({"assert_failed"})

SENTINEL_FUNCTIONS: frozenset[str] = frozenset({
    "assert",
    "abort",
    "__builtin_trap",
    "exit",
    "_exit",
})


# ---------------------------------------------------------------------------
# Guard Rules
# ---------------------------------------------------------------------------

SEC_BOUNDS_001 = SourceRule(
    rule_id="SEC-BOUNDS-001",
    category="GUARD",
    name="Array Index & Buffer Bounds Check",
    description="Validation of array index or buffer length to prevent out-of-bounds access.",
    cwe_primary="CWE-129",
    cwe_consequences=("CWE-787", "CWE-125"),
    severity=Severity.INFO,
)

SEC_NULL_001 = SourceRule(
    rule_id="SEC-NULL-001",
    category="GUARD",
    name="NULL Pointer Validation",
    description="Check for NULL or zero-pointer before dereference or operation.",
    cwe_primary="CWE-476",
    cwe_consequences=("CWE-476",),
    severity=Severity.INFO,
)

SEC_INTOVF_001 = SourceRule(
    rule_id="SEC-INTOVF-001",
    category="GUARD",
    name="Integer Overflow Pre-Check",
    description="Arithmetic threshold pre-validation guarding against integer wrap or underflow.",
    cwe_primary="CWE-190",
    cwe_consequences=("CWE-191",),
    severity=Severity.INFO,
)

SEC_DIV_001 = SourceRule(
    rule_id="SEC-DIV-001",
    category="GUARD",
    name="Zero Divisor Guard",
    description="Validation that divisor operand is non-zero before division or modulo.",
    cwe_primary="CWE-369",
    cwe_consequences=("CWE-369",),
    severity=Severity.INFO,
)

SEC_SENTINEL_001 = SourceRule(
    rule_id="SEC-SENTINEL-001",
    category="GUARD",
    name="Security Sentinel & Assertion Sink",
    description="Invocation of assert/abort/trap/exit or assignment to security sentinel.",
    cwe_primary="CWE-754",
    cwe_consequences=("CWE-20",),
    severity=Severity.NOTE,
)

SEC_RETCHK_001 = SourceRule(
    rule_id="SEC-RETCHK-001",
    category="GUARD",
    name="API / Allocation Return Value Check",
    description="Validation of memory allocation or system API return values.",
    cwe_primary="CWE-252",
    cwe_consequences=("CWE-476",),
    severity=Severity.INFO,
)


# ---------------------------------------------------------------------------
# Hazard Rules
# ---------------------------------------------------------------------------

HAZ_STRCPY_001 = SourceRule(
    rule_id="HAZ-STRCPY-001",
    category="HAZARD",
    name="Unbounded String Copy (strcpy)",
    description="Use of strcpy without explicit destination buffer bound checking.",
    cwe_primary="CWE-120",
    cwe_consequences=("CWE-787",),
    severity=Severity.WARNING,
)

HAZ_STRCAT_001 = SourceRule(
    rule_id="HAZ-STRCAT-001",
    category="HAZARD",
    name="Unbounded String Concatenation (strcat)",
    description="Use of strcat without destination capacity validation.",
    cwe_primary="CWE-120",
    cwe_consequences=("CWE-787",),
    severity=Severity.WARNING,
)

HAZ_SPRINTF_001 = SourceRule(
    rule_id="HAZ-SPRINTF-001",
    category="HAZARD",
    name="Unbounded Format Output (sprintf)",
    description="Use of sprintf without buffer length constraint (prefer snprintf).",
    cwe_primary="CWE-120",
    cwe_consequences=("CWE-134",),
    severity=Severity.WARNING,
)

HAZ_GETS_001 = SourceRule(
    rule_id="HAZ-GETS-001",
    category="HAZARD",
    name="Inherently Dangerous Function (gets)",
    description="Use of gets which lacks any buffer length protection.",
    cwe_primary="CWE-242",
    cwe_consequences=("CWE-120",),
    severity=Severity.WARNING,
)

HAZ_MEMCPY_001 = SourceRule(
    rule_id="HAZ-MEMCPY-001",
    category="HAZARD",
    name="Unchecked-Length Memory Copy (memcpy)",
    description="Use of memcpy without local size validation.",
    cwe_primary="CWE-120",
    cwe_consequences=("CWE-119",),
    severity=Severity.NOTE,
)


# ---------------------------------------------------------------------------
# Registry & Lookup
# ---------------------------------------------------------------------------

RULES: tuple[SourceRule, ...] = (
    SEC_BOUNDS_001,
    SEC_NULL_001,
    SEC_INTOVF_001,
    SEC_DIV_001,
    SEC_SENTINEL_001,
    SEC_RETCHK_001,
    HAZ_STRCPY_001,
    HAZ_STRCAT_001,
    HAZ_SPRINTF_001,
    HAZ_GETS_001,
    HAZ_MEMCPY_001,
)

_RULE_MAP: dict[str, SourceRule] = {r.rule_id: r for r in RULES}


def get_rule(rule_id: str) -> Optional[SourceRule]:
    """Retrieve rule definition by its unique identifier."""
    return _RULE_MAP.get(rule_id)
