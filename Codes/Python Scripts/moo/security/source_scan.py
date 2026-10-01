"""
moo/security/source_scan.py — Heuristic source code security scanner for C programs.

Extracts security guard patterns (bounds checks, NULL checks, overflow checks,
sentinels) and hazard functions (strcpy, gets, sprintf) without external dependencies.
Preserves original source line numbers by sanitizing comments and literals in-place.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Set

from .models import Severity, SourceFinding
from .rules import (
    DEFAULT_SENTINELS,
    HAZ_GETS_001,
    HAZ_MEMCPY_001,
    HAZ_SPRINTF_001,
    HAZ_STRCAT_001,
    HAZ_STRCPY_001,
    SEC_BOUNDS_001,
    SEC_DIV_001,
    SEC_INTOVF_001,
    SEC_NULL_001,
    SEC_RETCHK_001,
    SEC_SENTINEL_001,
)


# ---------------------------------------------------------------------------
# Comment and String Sanitizer (Line-Preserving)
# ---------------------------------------------------------------------------

def sanitize_c_source(source_text: str) -> str:
    """
    Replace comment bodies and string/character literals with whitespace,
    preserving exact line counts, line numbers, and character positions.
    """
    out = []
    i = 0
    n = len(source_text)
    state = "NORMAL"

    while i < n:
        c = source_text[i]
        nxt = source_text[i + 1] if i + 1 < n else ""

        if state == "NORMAL":
            if c == "/" and nxt == "/":
                state = "LINE_COMMENT"
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            elif c == "/" and nxt == "*":
                state = "BLOCK_COMMENT"
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            elif c == '"':
                state = "STRING"
                out.append('"')
                i += 1
                continue
            elif c == "'":
                state = "CHAR"
                out.append("'")
                i += 1
                continue
            else:
                out.append(c)
                i += 1

        elif state == "LINE_COMMENT":
            if c == "\n":
                state = "NORMAL"
                out.append("\n")
            else:
                out.append(" ")
            i += 1

        elif state == "BLOCK_COMMENT":
            if c == "*" and nxt == "/":
                state = "NORMAL"
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1

        elif state == "STRING":
            if c == "\\":
                out.append(" ")
                if i + 1 < n:
                    out.append("\n" if source_text[i + 1] == "\n" else " ")
                    i += 2
                else:
                    i += 1
                continue
            elif c == '"':
                state = "NORMAL"
                out.append('"')
                i += 1
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1

        elif state == "CHAR":
            if c == "\\":
                out.append(" ")
                if i + 1 < n:
                    out.append("\n" if source_text[i + 1] == "\n" else " ")
                    i += 2
                else:
                    i += 1
                continue
            elif c == "'":
                state = "NORMAL"
                out.append("'")
                i += 1
            else:
                out.append("\n" if c == "\n" else " ")
                i += 1

    return "".join(out)


# ---------------------------------------------------------------------------
# Function Boundary Tracker
# ---------------------------------------------------------------------------

_FUNC_HEADER_RE = re.compile(
    r"^(?:(?:static|inline|extern|__attribute__\s*\(\([^)]*\)\)|const|\w+)\s+)*"
    r"([a-zA-Z_]\w*)\s*\([^;{}]*\)\s*\{",
    re.MULTILINE
)


def _build_function_map(sanitized_text: str) -> list[tuple[int, int, str]]:
    """
    Returns list of (start_line, end_line, func_name) spans.
    Uses brace-depth tracking.
    """
    lines = sanitized_text.splitlines()
    spans: list[tuple[int, int, str]] = []

    brace_depth = 0
    current_func: Optional[str] = None
    func_start_line = 1

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()

        # If at depth 0, check for function header
        if brace_depth == 0:
            m = _FUNC_HEADER_RE.search(line)
            if m:
                candidate = m.group(1)
                # Filter out control flow keywords that look like function calls
                if candidate not in {"if", "while", "for", "switch"}:
                    current_func = candidate
                    func_start_line = line_idx

        # Update brace depth
        open_count = line.count("{")
        close_count = line.count("}")

        new_depth = brace_depth + open_count - close_count
        if brace_depth > 0 and new_depth <= 0 and current_func:
            spans.append((func_start_line, line_idx, current_func))
            current_func = None
            brace_depth = 0
        else:
            brace_depth = max(0, new_depth)

    if current_func:
        spans.append((func_start_line, len(lines), current_func))

    return spans


def _lookup_function(line_no: int, spans: list[tuple[int, int, str]]) -> Optional[str]:
    for start, end, name in spans:
        if start <= line_no <= end:
            return name
    return None


# ---------------------------------------------------------------------------
# Source Scanning Engine
# ---------------------------------------------------------------------------

# Bounds check regex: e.g. idx < 0 || idx >= limit, i >= BUFFER_SIZE, len < 0
_BOUNDS_RE = re.compile(
    r"\b([a-zA-Z_]\w*)\s*(?:<|<=)\s*0\b|"
    r"\b([a-zA-Z_]\w*)\s*(?:>=|>)\s*([A-Za-z0-9_]+)\b",
)

# NULL check regex: e.g. p == NULL, p == (void *)0, !p, !arr, p != 0
_NULL_RE = re.compile(
    r"\b([a-zA-Z_]\w*)\s*(?:==|!=)\s*(?:NULL|\(void\s*\*\s*\)0|\(void\s*\*\s*\)null)\b|"
    r"\b(?:NULL|\(void\s*\*\s*\)0)\s*(?:==|!=)\s*([a-zA-Z_]\w*)\b|"
    r"!\s*([a-zA-Z_]\w*)\b|"
    r"\b([a-zA-Z_]\w*)\s*==\s*0\b"
)

# Integer overflow pre-checks: e.g. b > INT_MAX - a, a > 0 && b > 2147483647 - a
_INTOVF_RE = re.compile(
    r"\b[a-zA-Z_]\w*\s*>\s*(?:INT_MAX|2147483647|\w*_MAX)\s*-\s*[a-zA-Z_]\w*|"
    r"\b[a-zA-Z_]\w*\s*\+\s*[a-zA-Z_]\w*\s*<\s*[a-zA-Z_]\w*|"
    r"\b[a-zA-Z_]\w*\s*<\s*(?:INT_MIN|-2147483648|\w*_MIN)\s*\+\s*[a-zA-Z_]\w*"
)

# Zero divisor checks: e.g. denom == 0, divisor == 0, !d guarding / or %
_DIV_RE = re.compile(
    r"\b(?:divisor|denom|denominator|div)\s*==\s*0\b|"
    r"!\s*(?:divisor|denom|denominator|div)\b"
)

# Sentinel functions
_SENTINEL_FUNC_RE = re.compile(
    r"\b(assert|abort|__builtin_trap)\s*\(|"
    r"\b(exit|_exit)\s*\(\s*(?:[1-9]\d*|EXIT_FAILURE|[A-Z_]*ERR[A-Z_]*)\s*\)"
)

# Hazard functions
_HAZARDS = [
    (HAZ_STRCPY_001, re.compile(r"\bstrcpy\s*\(")),
    (HAZ_STRCAT_001, re.compile(r"\bstrcat\s*\(")),
    (HAZ_SPRINTF_001, re.compile(r"\bsprintf\s*\(")),
    (HAZ_GETS_001, re.compile(r"\bgets\s*\(")),
    (HAZ_MEMCPY_001, re.compile(r"\bmemcpy\s*\(")),
]


def scan_source_text(
    source_text: str,
    filename: str = "",
    extra_sentinels: Optional[Set[str]] = None,
) -> list[SourceFinding]:
    """
    Scan C source text for guard patterns and security hazards.
    Deterministic and stdlib-only.
    """
    if not source_text:
        return []

    sentinels = set(DEFAULT_SENTINELS)
    if extra_sentinels:
        sentinels.update(extra_sentinels)

    # Build regex for sentinel assignments: e.g. assert_failed = 1;
    sentinel_alts = "|".join(re.escape(s) for s in sorted(sentinels))
    sentinel_assign_re = re.compile(rf"\b({sentinel_alts})\s*=\s*([1-9]\d*)\s*;")

    sanitized = sanitize_c_source(source_text)
    raw_lines = source_text.splitlines()
    clean_lines = sanitized.splitlines()

    func_spans = _build_function_map(sanitized)
    findings: list[SourceFinding] = []

    # Track recent allocation lines for return check detection
    recent_alloc: Optional[tuple[int, str]] = None  # (line_no, var_name)

    for line_idx, clean_line in enumerate(clean_lines, start=1):
        raw_line = raw_lines[line_idx - 1] if line_idx - 1 < len(raw_lines) else clean_line
        func_name = _lookup_function(line_idx, func_spans)

        # Check for allocation calls: malloc, calloc, realloc, fopen
        alloc_match = re.search(r"\b([a-zA-Z_]\w*)\s*=\s*(?:\([^)]*\)\s*)?(malloc|calloc|realloc|fopen)\s*\(", clean_line)
        if alloc_match:
            recent_alloc = (line_idx, alloc_match.group(1))

        # Check SEC-RETCHK-001 (allocation check within 4 lines)
        if recent_alloc and line_idx - recent_alloc[0] <= 4:
            var = recent_alloc[1]
            if re.search(rf"\bif\s*\(\s*(!\s*{var}|{var}\s*==\s*(?:NULL|0|\(void\s*\*\s*\)0))\b", clean_line):
                findings.append(SourceFinding(
                    rule_id=SEC_RETCHK_001.rule_id,
                    category=SEC_RETCHK_001.category,
                    line_number=line_idx,
                    matched_text=raw_line.strip(),
                    function_name=func_name,
                    cwe_primary=SEC_RETCHK_001.cwe_primary,
                    cwe_consequences=list(SEC_RETCHK_001.cwe_consequences),
                    severity=SEC_RETCHK_001.severity,
                    details=f"Allocation return value check for '{var}'",
                ))
                recent_alloc = None

        # SEC-SENTINEL-001: assert/abort/trap/exit calls
        sent_m = _SENTINEL_FUNC_RE.search(clean_line)
        if sent_m:
            matched_fn = sent_m.group(1) or sent_m.group(2)
            findings.append(SourceFinding(
                rule_id=SEC_SENTINEL_001.rule_id,
                category=SEC_SENTINEL_001.category,
                line_number=line_idx,
                matched_text=raw_line.strip(),
                function_name=func_name,
                cwe_primary=SEC_SENTINEL_001.cwe_primary,
                cwe_consequences=list(SEC_SENTINEL_001.cwe_consequences),
                severity=SEC_SENTINEL_001.severity,
                details=f"Security sentinel call '{matched_fn}'",
            ))

        # SEC-SENTINEL-001: sentinel flag assignments
        assign_m = sentinel_assign_re.search(clean_line)
        if assign_m:
            var_name, val = assign_m.group(1), assign_m.group(2)
            findings.append(SourceFinding(
                rule_id=SEC_SENTINEL_001.rule_id,
                category=SEC_SENTINEL_001.category,
                line_number=line_idx,
                matched_text=raw_line.strip(),
                function_name=func_name,
                cwe_primary=SEC_SENTINEL_001.cwe_primary,
                cwe_consequences=list(SEC_SENTINEL_001.cwe_consequences),
                severity=SEC_SENTINEL_001.severity,
                details=f"Sentinel flag assignment '{var_name} = {val}'",
            ))

        # SEC-INTOVF-001: integer overflow check
        if _INTOVF_RE.search(clean_line):
            findings.append(SourceFinding(
                rule_id=SEC_INTOVF_001.rule_id,
                category=SEC_INTOVF_001.category,
                line_number=line_idx,
                matched_text=raw_line.strip(),
                function_name=func_name,
                cwe_primary=SEC_INTOVF_001.cwe_primary,
                cwe_consequences=list(SEC_INTOVF_001.cwe_consequences),
                severity=SEC_INTOVF_001.severity,
                details="Integer overflow threshold pre-check",
            ))

        # SEC-DIV-001: zero divisor check
        if _DIV_RE.search(clean_line) or ("/" in clean_line and re.search(r"\bif\s*\(.*==\s*0", clean_line)):
            findings.append(SourceFinding(
                rule_id=SEC_DIV_001.rule_id,
                category=SEC_DIV_001.category,
                line_number=line_idx,
                matched_text=raw_line.strip(),
                function_name=func_name,
                cwe_primary=SEC_DIV_001.cwe_primary,
                cwe_consequences=list(SEC_DIV_001.cwe_consequences),
                severity=SEC_DIV_001.severity,
                details="Zero-divisor pre-check",
            ))

        # Context: only check bounds/null if line is a conditional or assert
        is_conditional = bool(re.search(r"\b(?:if|while|for|assert)\b", clean_line))

        # SEC-BOUNDS-001: bounds check
        if is_conditional or _BOUNDS_RE.search(clean_line):
            # Explicit bounds pattern: idx < 0 || idx >= limit or i >= BUFFER_SIZE
            bounds_check = False
            if re.search(r"\b(?:idx|index|i|j|k|len|length|pos|offset)\s*(?:<|<=)\s*0\b", clean_line):
                bounds_check = True
            elif re.search(r"\b(?:idx|index|i|j|k|len|length|pos|offset)\s*(?:>=|>)\s*(?:[A-Z0-9_]+|\b[a-zA-Z_]\w*)\b", clean_line):
                # Don't false-positive on simple loop increments like for (i = 0; i < 100; i++)
                if not re.search(r"\bfor\s*\(.*<.*\+\+", clean_line):
                    bounds_check = True
            elif "LIMIT" in clean_line or "BUFFER_SIZE" in clean_line or "MAX" in clean_line or "CAP" in clean_line:
                if re.search(r"(?:>|>=|<|<=)\s*[A-Za-z0-9_]*(?:LIMIT|BUFFER|SIZE|CAP|MAX)[A-Za-z0-9_]*\b", clean_line):
                    bounds_check = True

            if bounds_check:
                findings.append(SourceFinding(
                    rule_id=SEC_BOUNDS_001.rule_id,
                    category=SEC_BOUNDS_001.category,
                    line_number=line_idx,
                    matched_text=raw_line.strip(),
                    function_name=func_name,
                    cwe_primary=SEC_BOUNDS_001.cwe_primary,
                    cwe_consequences=list(SEC_BOUNDS_001.cwe_consequences),
                    severity=SEC_BOUNDS_001.severity,
                    details="Array bounds or buffer limit check",
                ))

        # SEC-NULL-001: null pointer check
        if is_conditional or "NULL" in clean_line or "(void *)0" in clean_line or "(void*)0" in clean_line:
            null_match = False
            if re.search(r"\b([a-zA-Z_]\w*)\s*(?:==|!=)\s*(?:NULL|\(void\s*\*\s*\)0|\(void\s*\*\s*\)null)\b", clean_line):
                null_match = True
            elif re.search(r"\b(?:NULL|\(void\s*\*\s*\)0)\s*(?:==|!=)\s*([a-zA-Z_]\w*)\b", clean_line):
                null_match = True
            elif is_conditional and re.search(r"!\s*([a-zA-Z_]\w*)\b", clean_line):
                null_match = True
            elif re.search(r"\b(?:p|ptr|arr|dest|src|buf|buffer|str|s|msg)\s*==\s*0\b", clean_line):
                null_match = True

            if null_match:
                findings.append(SourceFinding(
                    rule_id=SEC_NULL_001.rule_id,
                    category=SEC_NULL_001.category,
                    line_number=line_idx,
                    matched_text=raw_line.strip(),
                    function_name=func_name,
                    cwe_primary=SEC_NULL_001.cwe_primary,
                    cwe_consequences=list(SEC_NULL_001.cwe_consequences),
                    severity=SEC_NULL_001.severity,
                    details="NULL / null-pointer validation guard",
                ))

        # HAZARD rules
        for rule, h_re in _HAZARDS:
            if h_re.search(clean_line):
                findings.append(SourceFinding(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    line_number=line_idx,
                    matched_text=raw_line.strip(),
                    function_name=func_name,
                    cwe_primary=rule.cwe_primary,
                    cwe_consequences=list(rule.cwe_consequences),
                    severity=rule.severity,
                    details=f"Hazard function invocation: {rule.name}",
                ))

    # Return deterministically sorted by line_number, rule_id, matched_text
    findings.sort(key=lambda f: (f.line_number, f.rule_id, f.matched_text))
    return findings


def scan_source(
    source_path: str,
    extra_sentinels: Optional[Set[str]] = None,
) -> list[SourceFinding]:
    """
    Safely read C source file and return detected security findings.
    Never crashes on missing, unreadable, or malformed files.
    """
    if not source_path or not os.path.isfile(source_path):
        return []

    try:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return []

    return scan_source_text(
        content,
        filename=os.path.basename(source_path),
        extra_sentinels=extra_sentinels,
    )
