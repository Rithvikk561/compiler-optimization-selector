"""
moo/security/ir_parse.py — Tolerant textual LLVM .ll parser for security analysis.

Extracts functions, basic blocks, control flow graphs, callgraphs, and instructions
(store, call, icmp, br, ret, switch, invoke, unreachable, alloca) across diverse LLVM
versions (LLVM 18 through 23+), tolerating attributes like captures(...), range(...),
memory(...), !tbaa, and Windows CRLF.

Chunk 1 hardening (6 MUST-FIX):
  #1  Parser completeness — count define directives, compare with parsed functions,
      detect truncated functions, broaden function-name regex, emit warnings.
  #2  Store parsing — support volatile/atomic modifiers, i1 true/false, quoted names.
  #4  provably_dead_at_baseline — conservative constant-fold + reachability.
  #5  Provenance — parse !dbg metadata, DILocation, inlinedAt.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import ModuleSinks, Provenance


# ---------------------------------------------------------------------------
# Structural Intermediate Representation
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ParsedInstruction:
    """An individual instruction inside a basic block."""
    opcode: str
    raw_text: str
    line_number: int
    is_terminator: bool = False
    callee: Optional[str] = None           # for call/invoke
    store_val: Optional[str] = None        # for store (normalised string or int str)
    store_target: Optional[str] = None     # for store
    branch_cond: Optional[str] = None      # for conditional br
    branch_targets: list[str] = dataclasses.field(default_factory=list)
    # Fix #5: debug metadata reference
    dbg_ref: Optional[int] = None          # metadata node index from !dbg !N


@dataclasses.dataclass
class ParsedBlock:
    """A basic block within a function."""
    name: str
    instructions: list[ParsedInstruction] = dataclasses.field(default_factory=list)
    predecessors: set[str] = dataclasses.field(default_factory=set)
    successors: set[str] = dataclasses.field(default_factory=set)

    @property
    def terminator(self) -> Optional[ParsedInstruction]:
        for inst in reversed(self.instructions):
            if inst.is_terminator:
                return inst
        return None


@dataclasses.dataclass
class ParsedFunction:
    """A function defined in the LLVM module."""
    name: str
    blocks: dict[str, ParsedBlock] = dataclasses.field(default_factory=dict)
    entry_block: str = "entry"
    is_declaration: bool = False

    def get_callees(self) -> list[str]:
        callees = []
        for blk in self.blocks.values():
            for inst in blk.instructions:
                if inst.callee and inst.callee not in callees:
                    callees.append(inst.callee)
        return callees


@dataclasses.dataclass
class DebugLocation:
    """Parsed DILocation metadata node (Fix #5)."""
    node_id: int
    line: Optional[int] = None
    scope_id: Optional[int] = None         # metadata ref to scope
    inlined_at_id: Optional[int] = None    # metadata ref to outer DILocation


@dataclasses.dataclass
class DebugScope:
    """Parsed DISubprogram / DILexicalBlock metadata node (Fix #5)."""
    node_id: int
    name: Optional[str] = None             # function name in source
    scope_id: Optional[int] = None         # outer scope


@dataclasses.dataclass
class ParsedModule:
    """Parsed representation of an entire LLVM module."""
    ir_path: Optional[str] = None
    sha256: str = ""
    producer: Optional[str] = None
    functions: dict[str, ParsedFunction] = dataclasses.field(default_factory=dict)
    callgraph: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    warnings: list[str] = dataclasses.field(default_factory=list)

    # Fix #1: define-count tracking
    defined_function_count: int = 0        # raw `define` lines seen
    parsed_function_count: int = 0         # successfully parsed functions

    # Fix #5: debug metadata tables
    debug_locations: dict[int, DebugLocation] = dataclasses.field(default_factory=dict)
    debug_scopes: dict[int, DebugScope] = dataclasses.field(default_factory=dict)
    provenance_available: bool = False     # True if any DILocation found

    def to_module_sinks(self) -> ModuleSinks:
        parse_ok = (self.defined_function_count == self.parsed_function_count)
        return ModuleSinks(
            ir_path=self.ir_path,
            sha256=self.sha256,
            producer=self.producer,
            functions=list(self.functions.keys()),
            callgraph={k: list(v) for k, v in sorted(self.callgraph.items())},
            sinks=[],
            parse_warnings=list(self.warnings),
            parse_ok=parse_ok,
            defined_function_count=self.defined_function_count,
            parsed_function_count=self.parsed_function_count,
            provenance_available=self.provenance_available,
        )


# ---------------------------------------------------------------------------
# Regex Matchers (LLVM Version Agnostic)
# ---------------------------------------------------------------------------

# Fix #1: Broadened function-name pattern to handle:
#   - vector return types  (<4 x i32>)
#   - struct return types  ({ i32, i32 })
#   - quoted names         ("some.name")
#   - dso_local / local_unnamed_addr / noundef modifiers
#   - ptr / i32 / void / etc. return types
#
# Strategy: match `define` then skip everything up to `@` and capture the name.
# Quoted names: @"name with spaces"
# Unquoted names: @[a-zA-Z0-9_.$]+
_FUNC_DEF_RE = re.compile(
    r"^define\b.*?@(\"[^\"]+\"|[a-zA-Z0-9_.@$]+)\s*\(",
    re.DOTALL,
)

_FUNC_DECL_RE = re.compile(
    r"^declare\b.*?@(\"[^\"]+\"|[a-zA-Z0-9_.@$]+)\s*\(",
    re.DOTALL,
)

# Block labels:  "NN:" or "name:" or "; <label>:NN"
_LABEL_RE = re.compile(
    r"^(?:;\s*<label>:)?([a-zA-Z0-9_.$]+):(?:\s*;.*)?$"
)

# Fix #2: Store parsing — robust tokeniser for:
#   store [volatile] [atomic] [syncscope(...)] <ty> <val>, ptr <target>
#   bool literals: true -> 1, false -> 0
#   quoted targets: @"name"
#
# We use a two-step approach instead of a single fragile regex:
#   1. Match the line as a store at all.
#   2. Tokenise it properly.
_STORE_LINE_RE = re.compile(r"^\s*store\b")

# Quoted or unquoted global/local name at the store target position.
# Capture group 1 = the target name (may be quoted).
_STORE_TARGET_RE = re.compile(
    r",\s*(?:ptr|[\w\*]+)\s+(@\"[^\"]+\"|@[a-zA-Z0-9_.@$]+)"
)

# Extract value token after optional modifiers:
#   store volatile i32 1, ...
#   store atomic i32 1, ...
#   store atomic volatile i32 1, ...
#   store i1 true, ...
_STORE_VAL_RE = re.compile(
    r"^\s*store\s+"
    r"(?:volatile\s+)?"
    r"(?:atomic\s+)?"
    r"(?:volatile\s+)?"          # atomic volatile order
    r"(?:syncscope\([^)]*\)\s+)?"
    r"(?:[a-zA-Z0-9_<>\[\]{}, *]+?\s+)"   # type (greedy, stops at value)
    r"(true|false|[%@\w\d\-\.]+)"         # value
)

_CALL_RE = re.compile(
    r"^\s*(?:[%@\w\d]+\s*=\s*)?(?:tail\s+|musttail\s+|notail\s+)?(?:call|invoke)\s+"
    r"(?:[\w\(\)\*,\s]+?\s+)?@(\"[^\"]+\"|[a-zA-Z0-9_.@$]+)\s*\("
)

_BR_COND_RE = re.compile(
    r"^\s*br\s+i1\s+([%@\w\d.]+),\s*label\s+%([a-zA-Z0-9_.]+),\s*label\s+%([a-zA-Z0-9_.]+)"
)

_BR_UNCOND_RE = re.compile(r"^\s*br\s+label\s+%([a-zA-Z0-9_.]+)")

# Fix #2: switch terminator — capture default and case targets
_SWITCH_RE = re.compile(
    r"^\s*switch\s+\S+\s+\S+,\s*label\s+%([a-zA-Z0-9_.]+)"
)

# Fix #2 / #5: invoke — treat like call but is also a terminator
_INVOKE_RE = re.compile(
    r"^\s*(?:[%@\w\d]+\s*=\s*)?invoke\s+(?:[\w\(\)\*,\s]+?\s+)?@(\"[^\"]+\"|[a-zA-Z0-9_.@$]+)\s*\("
)

_PRODUCER_RE = re.compile(
    r'producer:\s*"([^"]+)"|!\s*\{\s*!"([^"]*clang[^"]*)"'
)

# Fix #5: debug metadata
# !N = !DILocation(line: M, column: C, scope: !K [, inlinedAt: !J])
_DI_LOCATION_RE = re.compile(
    r"^!(\d+)\s*=\s*(?:distinct\s+)?!DILocation\s*\(line:\s*(\d+).*?scope:\s*!(\d+)"
    r"(?:.*?inlinedAt:\s*!(\d+))?",
    re.DOTALL,
)

# !N = !DISubprogram(name: "funcname", ...)
_DI_SUBPROGRAM_RE = re.compile(
    r"^!(\d+)\s*=\s*(?:distinct\s+)?!DISubprogram\s*\(.*?name:\s*\"([^\"]+)\"",
    re.DOTALL,
)

# !N = !DILexicalBlock(..., scope: !M)
_DI_LEXBLOCK_RE = re.compile(
    r"^!(\d+)\s*=\s*(?:distinct\s+)?!DILexicalBlock(?:File)?\s*\(.*?scope:\s*!(\d+)",
    re.DOTALL,
)

# !dbg !N in an instruction line
_DBG_REF_RE = re.compile(r",\s*!dbg\s*!(\d+)")


# ---------------------------------------------------------------------------
# Store value normalisation (Fix #2)
# ---------------------------------------------------------------------------

def _parse_store_val(line: str) -> Optional[str]:
    """
    Extract the stored value token from a store instruction line.
    Handles: volatile, atomic, atomic volatile, syncscope(...), i1 true/false.
    Returns a string representation or None if unparseable.
    'true' -> '1', 'false' -> '0'.
    """
    m = _STORE_VAL_RE.match(line)
    if not m:
        return None
    tok = m.group(1)
    if tok == "true":
        return "1"
    if tok == "false":
        return "0"
    return tok


def _parse_store_target(line: str) -> Optional[str]:
    """
    Extract the store destination global/local name.
    Handles quoted names like @"assert_failed".
    """
    m = _STORE_TARGET_RE.search(line)
    if not m:
        return None
    return m.group(1)


# ---------------------------------------------------------------------------
# Parser Core
# ---------------------------------------------------------------------------

def parse_llvm_ir(ir_text_or_path: str, is_path: bool = True) -> ParsedModule:
    """
    Parse LLVM IR text or file into a tolerant ParsedModule representation.
    Never crashes on malformed IR.

    Fix #1: Counts `define` directives and compares with parsed functions.
            Emits warnings for incomplete parsing or truncated functions.
    Fix #2: Robust store parsing including volatile/atomic/i1/quoted names.
    Fix #5: Parses !dbg / DILocation / DISubprogram metadata for provenance.
    """
    ir_path: Optional[str] = None
    if is_path:
        ir_path = ir_text_or_path
        if not os.path.isfile(ir_text_or_path):
            return ParsedModule(
                ir_path=ir_path,
                sha256="",
                warnings=[f"IR file not found: {ir_text_or_path}"],
            )
        try:
            with open(ir_text_or_path, "r", encoding="utf-8", errors="replace") as f:
                ir_text = f.read()
        except Exception as exc:
            return ParsedModule(
                ir_path=ir_path,
                sha256="",
                warnings=[f"Error reading IR file: {exc}"],
            )
    else:
        ir_text = ir_text_or_path

    # Normalize newlines (handle Windows CRLF)
    ir_text = ir_text.replace("\r\n", "\n")
    sha256_hash = hashlib.sha256(ir_text.encode("utf-8")).hexdigest()

    parsed = ParsedModule(ir_path=ir_path, sha256=sha256_hash)

    lines = ir_text.splitlines()

    # -----------------------------------------------------------------------
    # Fix #1: Count define directives BEFORE parsing so we can detect drops.
    # -----------------------------------------------------------------------
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("define ") and "@" in line:
            parsed.defined_function_count += 1

    # -----------------------------------------------------------------------
    # Extract producer (best-effort)
    # -----------------------------------------------------------------------
    for line in lines:
        if "!DICompileUnit" in line or "!{" in line:
            m = _PRODUCER_RE.search(line)
            if m:
                parsed.producer = m.group(1) or m.group(2)
                break

    # -----------------------------------------------------------------------
    # Fix #5: Parse debug metadata (single-pass, collect all !N = !DI* lines)
    # -----------------------------------------------------------------------
    for raw_line in lines:
        line = raw_line.strip()

        m_loc = _DI_LOCATION_RE.match(line)
        if m_loc:
            nid = int(m_loc.group(1))
            ln = int(m_loc.group(2))
            scope = int(m_loc.group(3))
            inlined = int(m_loc.group(4)) if m_loc.group(4) else None
            parsed.debug_locations[nid] = DebugLocation(
                node_id=nid, line=ln, scope_id=scope, inlined_at_id=inlined,
            )
            parsed.provenance_available = True
            continue

        m_sub = _DI_SUBPROGRAM_RE.match(line)
        if m_sub:
            nid = int(m_sub.group(1))
            name = m_sub.group(2)
            parsed.debug_scopes[nid] = DebugScope(node_id=nid, name=name)
            continue

        m_lex = _DI_LEXBLOCK_RE.match(line)
        if m_lex:
            nid = int(m_lex.group(1))
            scope = int(m_lex.group(2))
            parsed.debug_scopes[nid] = DebugScope(node_id=nid, scope_id=scope)
            continue

    # -----------------------------------------------------------------------
    # Main parsing pass
    # -----------------------------------------------------------------------
    in_function = False
    current_func: Optional[ParsedFunction] = None
    current_block: Optional[ParsedBlock] = None
    block_seq: list[str] = []
    open_brace_depth = 0  # Fix #1: track truncated functions

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        # Skip metadata-only lines (lines starting with !)
        if line.startswith("!") and "=" in line:
            continue

        # Check function definition start
        if not in_function and line.startswith("define "):
            m = _FUNC_DEF_RE.match(line)
            if m:
                fn_name = m.group(1).strip('"')
                current_func = ParsedFunction(name=fn_name, entry_block="entry")
                in_function = True
                current_block = ParsedBlock(name="entry")
                current_func.blocks["entry"] = current_block
                block_seq = ["entry"]
                open_brace_depth = line.count("{") - line.count("}")
                if open_brace_depth < 0:
                    open_brace_depth = 0
                continue
            # define line present but didn't match — emit a warning (Fix #1)
            else:
                parsed.warnings.append(
                    f"define line at IR line {line_no} did not match function regex "
                    f"(unsupported signature?): {line[:120]}"
                )
                continue

        # Check function end
        if in_function and line == "}":
            open_brace_depth -= 1
            if open_brace_depth <= 0:
                if current_func:
                    _build_cfg(current_func)
                    parsed.functions[current_func.name] = current_func
                    parsed.parsed_function_count += 1
                in_function = False
                current_func = None
                current_block = None
                block_seq = []
                open_brace_depth = 0
            continue

        if in_function:
            # Track nested braces (e.g., struct type literals)
            open_brace_depth += line.count("{") - line.count("}")

        if not in_function:
            continue

        # Inside function: check for basic block label
        lbl_m = _LABEL_RE.match(line)
        if lbl_m:
            lbl_name = lbl_m.group(1)
            # If current block has no instructions and was default entry, rename it
            if (current_block and current_block.name == "entry"
                    and not current_block.instructions
                    and len(current_func.blocks) == 1):
                del current_func.blocks["entry"]
                current_func.entry_block = lbl_name
                current_block = ParsedBlock(name=lbl_name)
                current_func.blocks[lbl_name] = current_block
                block_seq = [lbl_name]
            else:
                current_block = ParsedBlock(name=lbl_name)
                current_func.blocks[lbl_name] = current_block
                block_seq.append(lbl_name)
            continue

        # Instructions inside basic block
        if current_block is None:
            current_block = ParsedBlock(name="entry")
            current_func.blocks["entry"] = current_block
            block_seq.append("entry")

        # Fix #5: extract !dbg reference from instruction line
        dbg_ref: Optional[int] = None
        dbg_m = _DBG_REF_RE.search(line)
        if dbg_m:
            dbg_ref = int(dbg_m.group(1))

        # Parse store (Fix #2: robust multi-form)
        if _STORE_LINE_RE.match(line):
            val_str = _parse_store_val(line)
            target_str = _parse_store_target(line)
            inst = ParsedInstruction(
                opcode="store",
                raw_text=line,
                line_number=line_no,
                store_val=val_str,
                store_target=target_str,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Parse invoke (Fix #2: invoke is a terminator)
        if "invoke " in line:
            inv_m = _INVOKE_RE.search(line)
            callee_name = inv_m.group(1).strip('"') if inv_m else None
            # invoke targets come on the next `to label` / `unwind label` lines;
            # we won't see them here so we leave branch_targets empty.
            inst = ParsedInstruction(
                opcode="invoke",
                raw_text=line,
                line_number=line_no,
                is_terminator=True,
                callee=callee_name,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Parse call
        if "call " in line:
            cm = _CALL_RE.search(line)
            if cm:
                callee_name = cm.group(1).strip('"')
                inst = ParsedInstruction(
                    opcode="call",
                    raw_text=line,
                    line_number=line_no,
                    callee=callee_name,
                    dbg_ref=dbg_ref,
                )
                current_block.instructions.append(inst)
                continue

        # Parse conditional branch  br i1 false, label %dead, label %live
        if line.startswith("br i1 "):
            bm = _BR_COND_RE.search(line)
            if bm:
                inst = ParsedInstruction(
                    opcode="br",
                    raw_text=line,
                    line_number=line_no,
                    is_terminator=True,
                    branch_cond=bm.group(1),
                    branch_targets=[bm.group(2), bm.group(3)],
                    dbg_ref=dbg_ref,
                )
                current_block.instructions.append(inst)
                continue

        # Parse unconditional branch
        if line.startswith("br label "):
            bm = _BR_UNCOND_RE.search(line)
            if bm:
                inst = ParsedInstruction(
                    opcode="br",
                    raw_text=line,
                    line_number=line_no,
                    is_terminator=True,
                    branch_targets=[bm.group(1)],
                    dbg_ref=dbg_ref,
                )
                current_block.instructions.append(inst)
                continue

        # Parse ret
        if line.startswith("ret ") or line == "ret void":
            inst = ParsedInstruction(
                opcode="ret",
                raw_text=line,
                line_number=line_no,
                is_terminator=True,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Parse icmp
        if "icmp " in line:
            inst = ParsedInstruction(
                opcode="icmp",
                raw_text=line,
                line_number=line_no,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Fix #2: switch (terminator) — parse at least the default target
        if line.startswith("switch "):
            sw_m = _SWITCH_RE.search(line)
            targets: list[str] = []
            if sw_m:
                targets.append(sw_m.group(1))
            # Additional case targets on same line: label %X
            for extra_tgt in re.findall(r"label\s+%([a-zA-Z0-9_.]+)", line):
                if extra_tgt not in targets:
                    targets.append(extra_tgt)
            inst = ParsedInstruction(
                opcode="switch",
                raw_text=line,
                line_number=line_no,
                is_terminator=True,
                branch_targets=targets,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Explicit alloca: normalise opcode to "alloca" even when result-assigned
        # e.g. "%1 = alloca i32, align 4"
        if "alloca " in line:
            inst = ParsedInstruction(
                opcode="alloca",
                raw_text=line,
                line_number=line_no,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Explicit load: normalise opcode to "load"
        # e.g. "%11 = load i32, ptr %6, align 4"
        if "= load " in line or line.startswith("load "):
            inst = ParsedInstruction(
                opcode="load",
                raw_text=line,
                line_number=line_no,
                dbg_ref=dbg_ref,
            )
            current_block.instructions.append(inst)
            continue

        # Other instructions (unreachable, indirectbr, phi, getelementptr, etc.)
        is_term = line.startswith(("unreachable", "indirectbr "))
        first_word = line.split()[0] if line.split() else "unknown"
        inst = ParsedInstruction(
            opcode=first_word,
            raw_text=line,
            line_number=line_no,
            is_terminator=is_term,
            dbg_ref=dbg_ref,
        )
        current_block.instructions.append(inst)

    # Fix #1: If we're still in a function at end-of-file, it was truncated.
    if in_function and current_func:
        parsed.warnings.append(
            f"Truncated/unterminated function '{current_func.name}' "
            f"(reached end of file without closing '}}')."
        )
        # Do NOT add the truncated function to parsed.functions — it is incomplete.

    # Fix #1: Compare define count vs parsed count and emit warning if mismatch.
    if parsed.defined_function_count != parsed.parsed_function_count:
        parsed.warnings.append(
            f"Parser completeness warning: {parsed.defined_function_count} define "
            f"directive(s) found but only {parsed.parsed_function_count} function(s) "
            f"successfully parsed. Some functions may have been silently dropped."
        )

    # Build callgraph
    for fn_name, fn in parsed.functions.items():
        parsed.callgraph[fn_name] = fn.get_callees()

    return parsed


def _build_cfg(func: ParsedFunction) -> None:
    """Link basic block predecessors and successors based on terminators."""
    for b_name, block in func.blocks.items():
        term = block.terminator
        if not term:
            continue
        for tgt in term.branch_targets:
            if tgt in func.blocks:
                block.successors.add(tgt)
                func.blocks[tgt].predecessors.add(b_name)


# ---------------------------------------------------------------------------
# Fix #5: Provenance resolution helpers
# ---------------------------------------------------------------------------

def resolve_provenance(
    parsed: ParsedModule,
    dbg_ref: Optional[int],
    containing_fn: str,
) -> tuple[Optional[str], Optional[int], Optional[bool]]:
    """
    Resolve (origin_function, source_line, inlined) from a !dbg reference.

    Returns:
      origin_function — function name in source where the instruction originated
      source_line     — source line number
      inlined         — True if inlinedAt is present (inlined from another func)

    Returns (None, None, None) if debug info is absent.
    """
    if dbg_ref is None or dbg_ref not in parsed.debug_locations:
        return None, None, None

    loc = parsed.debug_locations[dbg_ref]
    source_line = loc.line
    inlined = loc.inlined_at_id is not None

    # Walk scope chain to find DISubprogram
    origin_fn = _resolve_scope_name(parsed, loc.scope_id)

    return origin_fn, source_line, inlined


def _resolve_scope_name(
    parsed: ParsedModule, scope_id: Optional[int], depth: int = 0
) -> Optional[str]:
    """Walk lexical scope chain up to DISubprogram to get function name."""
    if scope_id is None or depth > 32:
        return None
    scope = parsed.debug_scopes.get(scope_id)
    if scope is None:
        return None
    if scope.name is not None:
        return scope.name
    return _resolve_scope_name(parsed, scope.scope_id, depth + 1)


def classify_provenance(
    origin_function: Optional[str],
    containing_fn: str,
    inlined: Optional[bool],
) -> Provenance:
    """
    Determine Provenance enum value given resolved debug info.
    """
    if origin_function is None:
        return Provenance.NONE
    if inlined:
        return Provenance.INLINED
    if origin_function == containing_fn:
        return Provenance.DIRECT
    # Origin differs from containing function but inlined is False — treat as DIRECT
    # (may be a clone; we conservatively say DIRECT without stronger evidence)
    return Provenance.DIRECT


# ---------------------------------------------------------------------------
# Fix #4: Conservative baseline deadness analysis
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _ConstantFolder:
    """
    Lightweight constant-fold pass for a single function.

    Tracks register values that are provably constant integers, supporting:
      - alloca + store constant + load from same alloca
      - icmp between constants
      - br i1 false / br i1 true (literal)

    Only marks edges as dead when provably unreachable.
    If uncertain, leaves everything live.
    """
    func: ParsedFunction
    # reg_name -> int constant value (only when provably constant)
    known_constants: dict[str, int] = dataclasses.field(default_factory=dict)
    # alloca_reg -> int constant (written by a store, not escaped)
    alloca_stores: dict[str, Optional[int]] = dataclasses.field(default_factory=dict)
    # alloca_reg -> set of blocks that loaded it (to detect escapes)
    alloca_loaded_regs: dict[str, str] = dataclasses.field(default_factory=dict)
    # set of alloca regs that escaped (passed to calls, stored through pointer, etc.)
    escaped_allocas: set[str] = dataclasses.field(default_factory=set)
    # block_name -> bool: can we reach this block?
    reachable: dict[str, bool] = dataclasses.field(default_factory=dict)


def _fold_function(func: ParsedFunction) -> dict[str, bool]:
    """
    Conservative constant-fold and reachability analysis.

    Returns a dict block_name -> bool (True = reachable, False = provably dead).
    Blocks not in the dict are considered reachable (conservative).
    """
    # Phase 1: collect alloca/store/load/icmp facts
    folder = _ConstantFolder(func=func)

    # --- Pass 1a: collect alloca registers and their single-store constants ---
    # This pass ONLY collects alloca registrations, store values, and escape info.
    # Load propagation happens AFTER all stores are collected, so that
    # loop-back stores (which invalidate the constant) are seen before loads.
    _LOCAL_STORE_TGT_RE = re.compile(
        r",\s*(?:ptr|[\w\*]+)\s+(%\w+)"
    )

    for b_name, block in func.blocks.items():
        for inst in block.instructions:
            line = inst.raw_text.strip()

            # alloca: %X = alloca <ty>, ...
            if inst.opcode == "alloca":
                m = re.match(r"(%\w+)\s*=\s*alloca\b", line)
                if m:
                    folder.alloca_stores[m.group(1)] = None  # not yet stored

            # store to alloca: handle both global (@) and local (%) targets
            if inst.opcode == "store" and inst.store_val:
                tgt = inst.store_target
                if tgt is None:
                    m_loc = _LOCAL_STORE_TGT_RE.search(line)
                    if m_loc:
                        tgt = m_loc.group(1)
                if tgt and tgt in folder.alloca_stores:
                    try:
                        cv = int(inst.store_val)
                    except (ValueError, TypeError):
                        cv = None
                    # If already has a value (multiple stores) -> not constant
                    if folder.alloca_stores[tgt] is not None:
                        folder.alloca_stores[tgt] = None  # multiple stores -> unknown
                    else:
                        folder.alloca_stores[tgt] = cv

            # call -> any alloca arg escapes
            if inst.opcode in ("call", "invoke"):
                raw = line
                for alloca_reg in list(folder.alloca_stores.keys()):
                    if alloca_reg in raw:
                        folder.escaped_allocas.add(alloca_reg)

    # --- Pass 1b: propagate alloca constants through loads ---
    # All stores are now fully collected; multi-store allocas have alloca_stores[r]=None.
    # Only propagate from allocas with a single, known constant store.
    for b_name, block in func.blocks.items():
        for inst in block.instructions:
            if inst.opcode != "load":
                continue
            line = inst.raw_text.strip()
            m = re.match(r"(%\w+)\s*=\s*load\b.*,\s*ptr\s+(%\w+)", line)
            if m:
                result_reg = m.group(1)
                src_reg = m.group(2)
                # Don't propagate if alloca escaped or has multiple/non-const stores
                if (src_reg in folder.alloca_stores
                        and src_reg not in folder.escaped_allocas):
                    cv = folder.alloca_stores[src_reg]
                    if cv is not None:
                        folder.known_constants[result_reg] = cv

    # --- Pass 2: propagate icmp results ---
    for b_name, block in func.blocks.items():
        for inst in block.instructions:
            if inst.opcode != "icmp":
                continue
            line = inst.raw_text.strip()
            # %result = icmp <pred> i32 %a, %b
            m = re.match(r"(%\w+)\s*=\s*icmp\s+(\w+)\s+\w+\s+([%@\w\d]+),\s*([%@\w\d]+)", line)
            if not m:
                continue
            result_reg = m.group(1)
            pred = m.group(2)
            a_tok = m.group(3)
            b_tok = m.group(4)

            a_val = _tok_const(a_tok, folder.known_constants)
            b_val = _tok_const(b_tok, folder.known_constants)

            if a_val is not None and b_val is not None:
                res = _eval_icmp(pred, a_val, b_val)
                if res is not None:
                    folder.known_constants[result_reg] = int(res)

    # --- Pass 3: reachability BFS with constant-fold of br conditions ---
    all_blocks = set(func.blocks.keys())
    reachable: set[str] = set()
    queue: list[str] = [func.entry_block]
    while queue:
        curr_name = queue.pop(0)
        if curr_name in reachable:
            continue
        if curr_name not in func.blocks:
            continue
        reachable.add(curr_name)
        block = func.blocks[curr_name]
        term = block.terminator
        if not term:
            continue

        if term.opcode == "unreachable":
            continue

        if term.opcode in ("ret",):
            continue

        if term.opcode == "br":
            if not term.branch_cond:
                # unconditional
                for tgt in term.branch_targets:
                    if tgt not in reachable:
                        queue.append(tgt)
            else:
                cond = term.branch_cond
                cond_val: Optional[int] = None
                if cond == "false":
                    cond_val = 0
                elif cond == "true":
                    cond_val = 1
                elif cond in folder.known_constants:
                    cond_val = folder.known_constants[cond]

                if cond_val is not None and len(term.branch_targets) == 2:
                    # condition is constant: only one branch is taken
                    live_idx = 0 if cond_val != 0 else 1
                    tgt = term.branch_targets[live_idx]
                    if tgt not in reachable:
                        queue.append(tgt)
                else:
                    # unknown condition: both branches may be taken
                    for tgt in term.branch_targets:
                        if tgt not in reachable:
                            queue.append(tgt)

        elif term.opcode in ("switch", "invoke"):
            for tgt in term.branch_targets:
                if tgt not in reachable:
                    queue.append(tgt)

        else:
            # Unknown terminator — conservatively mark all successors reachable
            block_obj = func.blocks[curr_name]
            for tgt in block_obj.successors:
                if tgt not in reachable:
                    queue.append(tgt)

    result: dict[str, bool] = {}
    for b_name in all_blocks:
        result[b_name] = b_name in reachable
    return result


def _tok_const(tok: str, known: dict[str, int]) -> Optional[int]:
    """Return integer constant for a token, or None if not known."""
    if tok in known:
        return known[tok]
    try:
        return int(tok)
    except (ValueError, TypeError):
        return None


def _eval_icmp(pred: str, a: int, b: int) -> Optional[bool]:
    """Evaluate icmp predicate on two integer constants."""
    p = pred.lower()
    try:
        if p == "eq":
            return a == b
        if p == "ne":
            return a != b
        if p in ("slt", "ult"):
            return a < b
        if p in ("sle", "ule"):
            return a <= b
        if p in ("sgt", "ugt"):
            return a > b
        if p in ("sge", "uge"):
            return a >= b
    except Exception:
        pass
    return None
