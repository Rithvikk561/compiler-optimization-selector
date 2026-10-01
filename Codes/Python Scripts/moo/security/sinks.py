"""
moo/security/sinks.py — Security sink identification and guardedness analysis for LLVM IR.

Recognizes flag stores (e.g. store 1, @assert_failed), abort calls, assert calls,
and trap instructions. Performs CFG-based reachability to classify sinks as guarded
versus unconditional.

Chunk 1 hardening (6 MUST-FIX):
  #2  Store sink recognition now handles volatile/atomic/i1 true forms and
      quoted sentinel names.  Safety-net warning if a store line looks like
      a sentinel write but no sink is produced.
  #3  is_guarded is now Optional[bool]:
        True  = proven guarded (block reachable only via conditional branch)
        False = proven unconditional
        None  = unknown / unsupported CFG pattern
  #4  provably_dead_at_baseline computed via _fold_function() constant folding.
  #5  Provenance fields populated from debug metadata where available.
  #6  canonical_text, ordinal, ir_line fields set on every GuardSink.
      Sink IDs are module-local only (documented).
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Set

from .ir_parse import (
    ParsedBlock,
    ParsedFunction,
    ParsedModule,
    _fold_function,
    classify_provenance,
    parse_llvm_ir,
    resolve_provenance,
)
from .models import GuardSink, ModuleSinks, Provenance, SinkClass, _canonicalize
from .rules import DEFAULT_SENTINELS


# ---------------------------------------------------------------------------
# Known Sink Functions
# ---------------------------------------------------------------------------

_ABORT_FUNCTIONS: frozenset[str] = frozenset({
    "abort",
    "exit",
    "_exit",
})

_ASSERT_FUNCTIONS: frozenset[str] = frozenset({
    "__assert_fail",
    "_wassert",
    "__assertfail",
    "assert",
})

_TRAP_FUNCTIONS: frozenset[str] = frozenset({
    "llvm.trap",
    "llvm.ubsantrap",
    "__fastfail",
})


# ---------------------------------------------------------------------------
# Guardedness Analysis (Fix #3: tri-state)
# ---------------------------------------------------------------------------

def _is_block_guarded(func: ParsedFunction, target_block_name: str) -> Optional[bool]:
    """
    Determine whether target_block_name is guarded by conditional branching.

    Returns:
        True   — block is reachable ONLY via at least one conditional branch
                 (never reached unconditionally from entry).
        False  — block is reachable unconditionally from entry (no conditional
                 branch required to reach it).
        None   — the analysis encountered an unsupported CFG pattern, a loop,
                 an invoke, or a switch and cannot safely determine guardedness.
                 This must NOT be treated as guarded.

    Conservative guarantee: if in doubt, return None (not True).
    """
    entry_name = func.entry_block
    if target_block_name == entry_name:
        return False

    # BFS from entry following ONLY unconditional branches.
    # If we reach the target this way -> unconditional (False).
    # If we exhaust reachable unconditional blocks without hitting the target
    # AND the target actually exists -> it requires a conditional branch (True).
    # If any block on the path has an unsupported/unknown terminator -> None.

    visited: set[str] = set()
    queue: list[str] = [entry_name]
    encountered_unknown = False

    while queue:
        curr_name = queue.pop(0)
        if curr_name == target_block_name:
            return False  # reached without any conditional branch

        if curr_name in visited:
            continue
        visited.add(curr_name)

        curr_block = func.blocks.get(curr_name)
        if not curr_block:
            continue

        term = curr_block.terminator
        if not term:
            # Block with no terminator: truncated / unsupported CFG
            encountered_unknown = True
            continue

        opcode = term.opcode

        if opcode == "unreachable":
            # Dead block — do not follow
            continue

        if opcode == "ret":
            continue

        if opcode == "br":
            if not term.branch_cond and len(term.branch_targets) == 1:
                # Unconditional branch — follow it
                nxt = term.branch_targets[0]
                if nxt not in visited:
                    queue.append(nxt)
            elif term.branch_cond:
                # Conditional branch — STOP following this path for unconditional
                # reachability (we could follow but those paths require a condition).
                # We do NOT add the targets to the BFS; they are conditionally reached.
                pass
            else:
                encountered_unknown = True

        elif opcode in ("switch", "invoke", "indirectbr"):
            # We cannot easily prove guardedness through switch/invoke/indirectbr
            # conservatively.
            encountered_unknown = True

        else:
            # Unknown terminator (e.g., catchret, cleanupret, resumé)
            encountered_unknown = True

    # target_block_name was NOT reached by any unconditional path from entry.
    if target_block_name not in func.blocks:
        # Block doesn't exist at all (parse artifact) — unknown
        return None

    if encountered_unknown:
        # Had unknown terminators on the way — cannot safely claim guarded
        return None

    # The target exists, was not unconditionally reachable, and no unknown
    # terminators were encountered — it is conditionally guarded.
    return True


# ---------------------------------------------------------------------------
# Safety-net: sentinel-store line detection (Fix #2)
# ---------------------------------------------------------------------------

# Detects lines that look like a store to a configured sentinel,
# used for the safety-net warning when a sink is not produced.
_SENTINEL_STORE_LINE_RE = re.compile(r"\bstore\b")


def _line_looks_like_sentinel_store(line: str, clean_sentinels: set[str]) -> bool:
    """Return True if the line looks like a store instruction targeting a sentinel."""
    if not _SENTINEL_STORE_LINE_RE.search(line):
        return False
    for sentinel in clean_sentinels:
        # Match both @sentinel and @"sentinel" forms
        if f"@{sentinel}" in line or f'@"{sentinel}"' in line:
            return True
    return False


# ---------------------------------------------------------------------------
# Sink Recognition Engine
# ---------------------------------------------------------------------------

def find_sinks(
    parsed: ParsedModule,
    extra_sentinels: Optional[Set[str]] = None,
) -> list[GuardSink]:
    """
    Discover all security-relevant sinks in the parsed LLVM module.
    Deterministic output sorted by IR order (function, ordinal).

    Fix #2: sentinel store recognition handles volatile/atomic/i1/quoted forms.
    Fix #3: is_guarded is tri-state Optional[bool].
    Fix #4: provably_dead_at_baseline uses constant-fold reachability.
    Fix #5: provenance fields populated from debug metadata.
    Fix #6: canonical_text, ordinal, ir_line set on every sink.
    """
    sentinels = set(DEFAULT_SENTINELS)
    if extra_sentinels:
        sentinels.update(extra_sentinels)

    # Standardize sentinels with and without '@'
    clean_sentinels = {s.lstrip("@") for s in sentinels}

    sinks: list[GuardSink] = []
    sink_counter = 0  # global ordinal counter (IR-order)

    for fn_name, func in sorted(parsed.functions.items(), key=lambda x: x[0]):

        # Fix #4: compute constant-fold reachability per function
        reachability = _fold_function(func)

        # Iterate blocks in IR-definition order (block_seq not available here,
        # fall back to insertion order which Python dicts preserve since 3.7)
        for b_name, block in func.blocks.items():
            # Fix #3: tri-state guardedness per block
            block_guarded = _is_block_guarded(func, b_name)

            # Fix #4: is this block provably dead?
            block_provably_dead = not reachability.get(b_name, True)

            for inst in block.instructions:

                # ----------------------------------------------------------
                # Fix #2: Safety-net: warn if a line looks like a sentinel
                #         store but parsing produced no target
                # ----------------------------------------------------------
                if inst.opcode == "store" and inst.store_target is None:
                    if _line_looks_like_sentinel_store(inst.raw_text, clean_sentinels):
                        parsed.warnings.append(
                            f"Safety-net [fn={fn_name}, block={b_name}, "
                            f"line={inst.line_number}]: Line appears to be a "
                            f"store to a security sentinel but no sink target "
                            f"was parsed. Instruction: {inst.raw_text.strip()[:120]}"
                        )

                # ----------------------------------------------------------
                # 1. FLAG_STORE: store non-zero constant to a sentinel global
                # ----------------------------------------------------------
                if inst.opcode == "store" and inst.store_target:
                    target_raw = inst.store_target.lstrip("@").strip('"')
                    if target_raw in clean_sentinels:
                        val_int: Optional[int] = None
                        try:
                            val_int = int(inst.store_val) if inst.store_val is not None else None
                        except (ValueError, TypeError):
                            val_int = None

                        # Only flag non-zero stores as security sinks
                        if val_int is not None and val_int != 0:
                            sink_counter += 1
                            # Fix #6: module-local sink ID only
                            sink_id = f"sink_{fn_name}_{b_name}_{sink_counter}"

                            # Fix #5: provenance
                            origin_fn, src_line, inlined = resolve_provenance(
                                parsed, inst.dbg_ref, fn_name
                            )
                            prov = classify_provenance(origin_fn, fn_name, inlined) if parsed.provenance_available else None

                            sinks.append(GuardSink(
                                # Fix #6: module-local ID (NOT stable cross-opt)
                                sink_id=sink_id,
                                sink_class=SinkClass.FLAG_STORE,
                                function_name=fn_name,
                                basic_block=b_name,
                                instruction_text=inst.raw_text.strip(),
                                # canonical_text auto-computed by __post_init__
                                target_symbol=inst.store_target,
                                constant_value=val_int,
                                # Fix #3: tri-state
                                is_guarded=block_guarded,
                                guard_condition=None,
                                # Fix #4: dead at baseline
                                provably_dead_at_baseline=block_provably_dead,
                                details=f"Flag store '{inst.store_val}' to sentinel '{inst.store_target}'",
                                # Fix #6: stable fields
                                ir_line=inst.line_number,
                                ordinal=sink_counter,
                                # Fix #5: provenance
                                origin_function=origin_fn,
                                source_line=src_line,
                                inlined=inlined,
                                provenance=prov,
                            ))
                            continue

                # ----------------------------------------------------------
                # 2. CALL / TRAP: calls to abort, assert, trap, exit
                # ----------------------------------------------------------
                if inst.opcode in ("call", "invoke") and inst.callee:
                    callee_name = inst.callee
                    sink_class: Optional[SinkClass] = None

                    if callee_name in _ABORT_FUNCTIONS:
                        sink_class = SinkClass.ABORT_CALL
                    elif callee_name in _ASSERT_FUNCTIONS:
                        sink_class = SinkClass.ASSERT_CALL
                    elif callee_name in _TRAP_FUNCTIONS:
                        sink_class = SinkClass.TRAP

                    if sink_class is not None:
                        sink_counter += 1
                        sink_id = f"sink_{fn_name}_{b_name}_{sink_counter}"

                        # Fix #5: provenance
                        origin_fn, src_line, inlined = resolve_provenance(
                            parsed, inst.dbg_ref, fn_name
                        )
                        prov = classify_provenance(origin_fn, fn_name, inlined) if parsed.provenance_available else None

                        sinks.append(GuardSink(
                            sink_id=sink_id,
                            sink_class=sink_class,
                            function_name=fn_name,
                            basic_block=b_name,
                            instruction_text=inst.raw_text.strip(),
                            target_symbol=f"@{callee_name}",
                            constant_value=None,
                            # Fix #3: tri-state
                            is_guarded=block_guarded,
                            guard_condition=None,
                            # Fix #4
                            provably_dead_at_baseline=block_provably_dead,
                            details=f"Call to security sink '{callee_name}'",
                            # Fix #6
                            ir_line=inst.line_number,
                            ordinal=sink_counter,
                            # Fix #5
                            origin_function=origin_fn,
                            source_line=src_line,
                            inlined=inlined,
                            provenance=prov,
                        ))

    # Fix #6: Deterministic sort by (function_name, ordinal) — IR order.
    # We use ordinal (insertion/IR order) rather than lexicographic block-name sort.
    # This is stable across opt levels when function structure is preserved.
    sinks.sort(key=lambda s: (s.function_name, s.ordinal))
    return sinks


def analyze_module_sinks(
    ir_text_or_path: str,
    is_path: bool = True,
    extra_sentinels: Optional[Set[str]] = None,
) -> ModuleSinks:
    """
    Parse an LLVM IR module and discover all security guard sinks.
    Returns complete ModuleSinks data model.

    Fix #1: ModuleSinks.parse_ok will be False if define count != parsed count.
    Fix #2: Store parsing handles volatile/atomic/i1/quoted sentinel forms.
    """
    parsed = parse_llvm_ir(ir_text_or_path, is_path=is_path)
    module_sinks = parsed.to_module_sinks()
    module_sinks.sinks = find_sinks(parsed, extra_sentinels=extra_sentinels)
    # Propagate any safety-net warnings that find_sinks may have appended
    # to parsed.warnings (find_sinks mutates parsed.warnings for safety-net).
    module_sinks.parse_warnings = list(parsed.warnings)
    return module_sinks
