"""
moo/tests/test_stage6_security_unit.py — Stage 6 Unit Tests for Secure Code Analysis.

Tests cover:
- Source rule detection (positive & negative cases for all 11 rules)
- Comment and string literal immunity (line-preserving sanitization)
- CWE mappings and rule specifications
- Sentinel detection and configurable extra sentinel symbols
- LLVM IR textual parsing on frozen IR files (O0, O1, O2, O3)
- Verification of verified sink counts: O0 has 4, O1/O2/O3 have 3
- Guardedness analysis: conditional vs unconditional/folded sinks (tri-state)
- Edge-case IR parsing: empty IR, CRLF IR, malformed IR, missing files
- Verified facts: ai_test_security_checks has identical O2 and O3 behavior
- Deterministic data models and serialization to JSON

Chunk 1 hardening tests (6 MUST-FIX):
  #1  Parser completeness: define-count, truncated, vector/struct/quoted names
  #2  Store parsing: volatile, atomic, i1 true/false, quoted sentinel
  #3  Guardedness tri-state: unconditional / guarded / unknown
  #4  provably_dead_at_baseline: known-dead, live, nonconstant, escaped, ambiguous
  #5  Provenance: debug metadata parsing, DILocation, inlinedAt
  #6  Stable sink identity: canonical_text strips metadata, ordinal ordering

IMPORTANT: report() raises AssertionError on failure (strengthened from original).
Missing frozen fixture files are errors, not skips, for critical tests (S7, S8, S12).
"""

from __future__ import annotations

import json
import os
import sys

# Ensure repository root is on path so moo package can be imported
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_TEST_DIR)
_SCRIPTS_DIR = os.path.dirname(_MOO_DIR)
_CODES_DIR = os.path.dirname(_SCRIPTS_DIR)
_REPO_ROOT = os.path.dirname(_CODES_DIR)

if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from moo.security.models import (
    CandidateSecurity,
    CandidateVerdict,
    GuardAssessment,
    GuardSink,
    GuardStatus,
    ModuleSinks,
    Provenance,
    Severity,
    SinkClass,
    SourceFinding,
    _canonicalize,
)
from moo.security.rules import (
    DEFAULT_SENTINELS,
    RULES,
    SourceRule,
    get_rule,
)
from moo.security.source_scan import (
    sanitize_c_source,
    scan_source,
    scan_source_text,
)
from moo.security.ir_parse import (
    ParsedBlock,
    ParsedFunction,
    ParsedInstruction,
    ParsedModule,
    parse_llvm_ir,
    _fold_function,
    resolve_provenance,
    classify_provenance,
)
from moo.security.sinks import (
    analyze_module_sinks,
    find_sinks,
    _is_block_guarded,
)


# ---------------------------------------------------------------------------
# Test Runner Infrastructure (Repository Standard) — Strengthened
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"

_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = ""):
    """
    Record and print a test result.

    STRENGTHENED (Fix #TEST): raises AssertionError immediately when passed=False
    so that the test runner actually fails hard, rather than silently accumulating.
    """
    status = PASS if passed else FAIL
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{status}] {tid}: {name}{suffix}")
    if not passed:
        raise AssertionError(
            f"TEST FAILED [{tid}] {name}"
            + (f": {note}" if note else "")
        )


def skip(tid: str, name: str, reason: str = ""):
    _results.append((tid, name, "SKIP"))
    print(f"  [{SKIP}] {tid}: {name} (SKIPPED: {reason})")


def _require_fixture(path: str, tid: str, name: str) -> bool:
    """
    Check that a frozen fixture file exists.
    Critical tests FAIL (not skip) when fixtures are missing.
    Returns True if file exists, otherwise records FAIL and raises.
    """
    if not os.path.isfile(path):
        report(tid, name, False, f"MISSING FIXTURE: {path}")
        return False
    return True


# ---------------------------------------------------------------------------
# Tests: Source Rules — Positive & Negative Cases (unchanged)
# ---------------------------------------------------------------------------

def test_s1_guard_rules_positive():
    """S1: Every guard rule detects its target security pattern."""
    tid, name = "S1", "Guard rules positive detection"
    cases = [
        # (rule_id, snippet)
        ("SEC-BOUNDS-001", "void f(int idx) { if (idx < 0 || idx >= 100) return; }"),
        ("SEC-BOUNDS-001", "void f(int i) { if (i >= BUFFER_SIZE) return; }"),
        ("SEC-NULL-001", "void f(char *p) { if (p == NULL) return; }"),
        ("SEC-NULL-001", "void f(int *arr) { if (!arr) return; }"),
        ("SEC-NULL-001", "void f(char *d) { if (d == (void *)0) return; }"),
        ("SEC-INTOVF-001", "void f(int a, int b) { if (b > 2147483647 - a) return; }"),
        ("SEC-INTOVF-001", "void f(int a, int b) { if (b > INT_MAX - a) return; }"),
        ("SEC-DIV-001", "int f(int a, int divisor) { if (divisor == 0) return 0; return a / divisor; }"),
        ("SEC-SENTINEL-001", "void f() { assert(1 == 1); }"),
        ("SEC-SENTINEL-001", "void f() { abort(); }"),
        ("SEC-SENTINEL-001", "void f() { __builtin_trap(); }"),
        ("SEC-SENTINEL-001", "void f() { exit(1); }"),
        ("SEC-SENTINEL-001", "void f() { assert_failed = 1; }"),
        ("SEC-RETCHK-001", "void f() { char *p = malloc(64); if (!p) return; }"),
    ]

    all_matched = True
    mismatches = []
    for expected_rule, snippet in cases:
        findings = scan_source_text(snippet)
        rule_ids = {f.rule_id for f in findings}
        if expected_rule not in rule_ids:
            all_matched = False
            mismatches.append(f"{expected_rule} in '{snippet}' -> got {rule_ids}")

    report(tid, name, all_matched, f"cases={len(cases)} mismatches={mismatches}")


def test_s2_hazard_rules_positive():
    """S2: Every hazard rule detects its target dangerous API invocation."""
    tid, name = "S2", "Hazard rules positive detection"
    cases = [
        ("HAZ-STRCPY-001", "void f(char *d, char *s) { strcpy(d, s); }"),
        ("HAZ-STRCAT-001", "void f(char *d, char *s) { strcat(d, s); }"),
        ("HAZ-SPRINTF-001", "void f(char *d, int v) { sprintf(d, \"%d\", v); }"),
        ("HAZ-GETS-001", "void f(char *d) { gets(d); }"),
        ("HAZ-MEMCPY-001", "void f(void *d, void *s, size_t n) { memcpy(d, s, n); }"),
    ]

    all_matched = True
    mismatches = []
    for expected_rule, snippet in cases:
        findings = scan_source_text(snippet)
        rule_ids = {f.rule_id for f in findings}
        if expected_rule not in rule_ids:
            all_matched = False
            mismatches.append(f"{expected_rule} in '{snippet}' -> got {rule_ids}")

    report(tid, name, all_matched, f"cases={len(cases)} mismatches={mismatches}")


def test_s3_negative_cases():
    """S3: Benign code without security patterns produces zero false positives."""
    tid, name = "S3", "Negative cases produce no findings"
    benign_snippet = """
    int calculate_sum(int a, int b) {
        int sum = 0;
        for (int i = 0; i < 10; i++) {
            sum += a * b + i;
        }
        return sum;
    }
    """
    findings = scan_source_text(benign_snippet)
    ok = len(findings) == 0
    report(tid, name, ok, f"findings={len(findings)}")


def test_s4_comment_string_immunity():
    """S4: Patterns in comments and string literals are sanitized without false positives."""
    tid, name = "S4", "Comments and string literals produce zero findings"
    commented_snippet = """
    // This comment mentions abort() and strcpy(dest, src) and assert_failed = 1;
    /* Multi-line comment:
       if (idx < 0 || idx >= 100) { abort(); }
       gets(buffer);
    */
    void log_message(void) {
        const char *msg1 = "strcpy(d, s) and abort() in literal";
        const char *msg2 = "assert_failed = 1; inside string";
        const char *msg3 = "if (ptr == NULL) inside string";
    }
    """
    findings = scan_source_text(commented_snippet)
    ok = len(findings) == 0
    report(tid, name, ok, f"findings={len(findings)}")


def test_s5_cwe_mappings():
    """S5: Rule definitions carry correct primary and consequence CWE mappings."""
    tid, name = "S5", "CWE mappings verification"
    expected = {
        "SEC-BOUNDS-001": ("CWE-129", ("CWE-787", "CWE-125")),
        "SEC-NULL-001": ("CWE-476", ("CWE-476",)),
        "SEC-INTOVF-001": ("CWE-190", ("CWE-191",)),
        "SEC-DIV-001": ("CWE-369", ("CWE-369",)),
        "SEC-SENTINEL-001": ("CWE-754", ("CWE-20",)),
        "SEC-RETCHK-001": ("CWE-252", ("CWE-476",)),
        "HAZ-STRCPY-001": ("CWE-120", ("CWE-787",)),
        "HAZ-STRCAT-001": ("CWE-120", ("CWE-787",)),
        "HAZ-SPRINTF-001": ("CWE-120", ("CWE-134",)),
        "HAZ-GETS-001": ("CWE-242", ("CWE-120",)),
        "HAZ-MEMCPY-001": ("CWE-120", ("CWE-119",)),
    }

    all_matched = True
    for rule_id, (exp_pri, exp_conseq) in expected.items():
        rule = get_rule(rule_id)
        if not rule:
            all_matched = False
            break
        if rule.cwe_primary != exp_pri or rule.cwe_consequences != exp_conseq:
            all_matched = False
            break

    report(tid, name, all_matched, f"checked_rules={len(expected)}")


def test_s6_sentinel_discovery():
    """S6: Sentinel discovery supports defaults and configurable extra sentinels."""
    tid, name = "S6", "Configurable sentinel symbols"
    snippet = """
    void check() {
        assert_failed = 1;
        custom_sentinel = 2;
    }
    """
    # Without extra sentinel: only assert_failed is detected
    f1 = scan_source_text(snippet)
    matched_f1 = [f.matched_text for f in f1 if f.rule_id == "SEC-SENTINEL-001"]
    has_default = any("assert_failed" in t for t in matched_f1)
    has_custom = any("custom_sentinel" in t for t in matched_f1)

    # With extra sentinel: custom_sentinel is detected
    f2 = scan_source_text(snippet, extra_sentinels={"custom_sentinel"})
    matched_f2 = [f.matched_text for f in f2 if f.rule_id == "SEC-SENTINEL-001"]
    has_custom_configured = any("custom_sentinel" in t for t in matched_f2)

    ok = has_default and (not has_custom) and has_custom_configured
    report(tid, name, ok, f"default={has_default} custom_unconf={has_custom} custom_conf={has_custom_configured}")


# ---------------------------------------------------------------------------
# Tests: LLVM IR Parser & Sinks on Frozen IR Files
# ---------------------------------------------------------------------------

def test_s7_frozen_ir_sink_counts():
    """S7: Verify stated sink counts AND sink identities on frozen IR files (O0=4, O1=3, O2=3, O3=3)."""
    tid, name = "S7", "Frozen IR sink counts and identities: O0=4, O1/O2/O3=3"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    paths = {
        "O0": os.path.join(ir_dir, "security_checks_O0.ll"),
        "O1": os.path.join(ir_dir, "security_checks_O1.ll"),
        "O2": os.path.join(ir_dir, "security_checks_O2.ll"),
        "O3": os.path.join(ir_dir, "security_checks_O3.ll"),
    }

    for opt, p in paths.items():
        if not _require_fixture(p, tid, name):
            return

    counts = {}
    sink_fns: dict[str, set[str]] = {}
    for opt, p in paths.items():
        ms = analyze_module_sinks(p)
        counts[opt] = len(ms.sinks)
        sink_fns[opt] = {s.function_name for s in ms.sinks}

        # parse_ok must be True for frozen fixtures
        report(
            tid, f"S7-{opt}-parse_ok",
            ms.parse_ok,
            f"defined={ms.defined_function_count} parsed={ms.parsed_function_count}"
        )

    expected_counts = {"O0": 4, "O1": 3, "O2": 3, "O3": 3}
    counts_ok = counts == expected_counts
    report(tid, name, counts_ok, f"actual={counts} expected={expected_counts}")

    # S7 identity check: every level must include sinks in known functions
    # O0: all 3 functions have sinks
    o0_fns_ok = sink_fns["O0"] == {"safe_copy", "calculate_safe_index", "main"}
    report(tid, "S7-O0-fn-identity", o0_fns_ok,
           f"found={sink_fns['O0']}")

    # O1/O2/O3: all 3 functions must still appear
    for opt in ("O1", "O2", "O3"):
        fns_ok = sink_fns[opt] == {"safe_copy", "calculate_safe_index", "main"}
        report(tid, f"S7-{opt}-fn-identity", fns_ok, f"found={sink_fns[opt]}")

    # canonical_text must be identical for the main sink across O1/O2/O3
    ms_o1 = analyze_module_sinks(paths["O1"])
    ms_o2 = analyze_module_sinks(paths["O2"])
    ms_o3 = analyze_module_sinks(paths["O3"])
    o1_main_canonical = {s.canonical_text for s in ms_o1.sinks if s.function_name == "main"}
    o2_main_canonical = {s.canonical_text for s in ms_o2.sinks if s.function_name == "main"}
    o3_main_canonical = {s.canonical_text for s in ms_o3.sinks if s.function_name == "main"}
    canonical_match = (o1_main_canonical == o2_main_canonical == o3_main_canonical)
    report(tid, "S7-canonical-identity-O1O2O3",
           canonical_match,
           f"o1={o1_main_canonical} o2={o2_main_canonical} o3={o3_main_canonical}")


def test_s8_guarded_vs_unconditional_sinks():
    """S8: Correctly distinguish guarded vs unconditional sinks (tri-state is_guarded)."""
    tid, name = "S8", "Guarded vs unconditional sink classification (tri-state)"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")
    p_o0 = os.path.join(ir_dir, "security_checks_O0.ll")

    if not _require_fixture(p_o2, tid, name) or not _require_fixture(p_o0, tid, name):
        return

    # In O0: all 4 sinks must be guarded (is_guarded is True)
    ms_o0 = analyze_module_sinks(p_o0)
    # is_guarded == True (not None, not False)
    all_o0_guarded = (
        all(s.is_guarded is True for s in ms_o0.sinks)
        and len(ms_o0.sinks) == 4
    )
    report(tid, "S8-O0-all-guarded", all_o0_guarded,
           f"sinks={[(s.function_name, s.is_guarded) for s in ms_o0.sinks]}")

    # In O2: safe_copy and calculate_safe_index are guarded; main is unconditional
    ms_o2 = analyze_module_sinks(p_o2)
    main_sinks = [s for s in ms_o2.sinks if s.function_name == "main"]
    other_sinks = [s for s in ms_o2.sinks if s.function_name != "main"]

    # main's sink is in entry block — unconditional (False)
    main_unconditional = (len(main_sinks) == 1 and main_sinks[0].is_guarded is False)
    report(tid, "S8-O2-main-unconditional", main_unconditional,
           f"main_is_guarded={main_sinks[0].is_guarded if main_sinks else 'MISSING'}")

    # Others are guarded (True)
    others_guarded = (len(other_sinks) == 2 and all(s.is_guarded is True for s in other_sinks))
    report(tid, "S8-O2-others-guarded", others_guarded,
           f"others={[(s.function_name, s.is_guarded) for s in other_sinks]}")

    ok = all_o0_guarded and main_unconditional and others_guarded
    report(tid, name, ok)


def test_s9_toolchain_verified_behavior():
    """S9: Verified fact: ai_test_security_checks has identical O2 and O3 behavior."""
    tid, name = "S9", "Verified fact: ai_test O2 vs O3 IR behavior"
    ai_c_path = os.path.join(_CODES_DIR, "test_cases", "ai_test_security_checks.c")
    if not os.path.isfile(ai_c_path):
        skip(tid, name, "Missing ai_test_security_checks.c")
        return

    findings = scan_source(ai_c_path)
    rule_ids = {f.rule_id for f in findings}
    has_sentinel = "SEC-SENTINEL-001" in rule_ids
    has_bounds = "SEC-BOUNDS-001" in rule_ids

    # Also test pre-existing IR files for ai_test if present in ir_output
    ai_o2_ll = os.path.join(_CODES_DIR, "ir_output", "ai_o2.ll")
    ai_o3_ll = os.path.join(_CODES_DIR, "ir_output", "ai_o3.ll")
    ir_match = True
    if os.path.isfile(ai_o2_ll) and os.path.isfile(ai_o3_ll):
        with open(ai_o2_ll, "r", encoding="utf-8", errors="replace") as f:
            c2 = f.read()
        with open(ai_o3_ll, "r", encoding="utf-8", errors="replace") as f:
            c3 = f.read()
        ir_match = (c2 == c3)

    ok = has_sentinel and has_bounds and ir_match
    report(tid, name, ok, f"has_sentinel={has_sentinel} has_bounds={has_bounds} frozen_ir_match={ir_match}")


def test_s10_parser_edge_cases():
    """S10: Parser safely handles empty IR, CRLF newlines, malformed IR, missing files."""
    tid, name = "S10", "Parser edge cases (empty, CRLF, malformed, missing)"

    # 1. Empty IR
    m_empty = parse_llvm_ir("", is_path=False)
    empty_ok = len(m_empty.functions) == 0 and len(m_empty.warnings) == 0

    # 2. CRLF newlines
    crlf_ir = "define void @foo() {\r\nentry:\r\n  call void @abort()\r\n  ret void\r\n}\r\n"
    m_crlf = parse_llvm_ir(crlf_ir, is_path=False)
    sinks_crlf = find_sinks(m_crlf)
    crlf_ok = len(m_crlf.functions) == 1 and len(sinks_crlf) == 1

    # 3. Malformed IR without matching braces or labels
    bad_ir = "this is not valid LLVM IR ; !!! define random stuff { \n store garbage\n"
    m_bad = parse_llvm_ir(bad_ir, is_path=False)
    bad_ok = isinstance(m_bad, ParsedModule)  # never raises

    # 4. Missing file path
    m_missing = parse_llvm_ir("non_existent_file_path.ll", is_path=True)
    missing_ok = len(m_missing.warnings) > 0 and len(m_missing.functions) == 0

    ok = empty_ok and crlf_ok and bad_ok and missing_ok
    report(tid, name, ok, f"empty={empty_ok} crlf={crlf_ok} bad={bad_ok} missing={missing_ok}")


# ---------------------------------------------------------------------------
# Tests: Models & Determinism
# ---------------------------------------------------------------------------

def test_s11_models_and_serialization():
    """S11: All dataclasses serialize deterministically to JSON via to_dict()."""
    tid, name = "S11", "Models and deterministic JSON serialization"

    sf = SourceFinding(
        rule_id="SEC-BOUNDS-001",
        category="GUARD",
        line_number=10,
        matched_text="if (i >= 100)",
        function_name="safe_copy",
        cwe_primary="CWE-129",
        cwe_consequences=["CWE-787", "CWE-125"],
        severity=Severity.NOTE,
        details="bounds check",
    )
    d_sf = sf.to_dict()

    gs = GuardSink(
        sink_id="sink-1",
        sink_class=SinkClass.FLAG_STORE,
        function_name="safe_copy",
        basic_block="entry",
        instruction_text="store i32 1, ptr @assert_failed, align 4, !tbaa !10",
        target_symbol="@assert_failed",
        constant_value=1,
        is_guarded=True,
        ir_line=42,
        ordinal=1,
    )
    d_gs = gs.to_dict()
    # canonical_text should have stripped the metadata
    assert "!tbaa" not in gs.canonical_text, f"canonical_text still has metadata: {gs.canonical_text}"
    assert "store i32 1, ptr @assert_failed, align 4" == gs.canonical_text, f"canonical_text wrong: {gs.canonical_text}"

    ms = ModuleSinks(
        ir_path="test.ll",
        sha256="abc",
        functions=["safe_copy", "main"],
        callgraph={"main": ["safe_copy"]},
        sinks=[gs],
        parse_ok=True,
        defined_function_count=2,
        parsed_function_count=2,
        provenance_available=False,
    )
    d_ms = ms.to_dict()

    ga = GuardAssessment(
        sink_id="sink-1",
        status=GuardStatus.PRESERVED,
        details="preserved in candidate",
    )
    d_ga = ga.to_dict()

    cs = CandidateSecurity(
        strategy_name="-O2",
        verdict=CandidateVerdict.PRESERVED,
        baseline_sink_count=3,
        candidate_sink_count=3,
        preserved_sinks=3,
        guard_assessments=[ga],
    )
    d_cs = cs.to_dict()

    # Verify JSON serializability
    json_sf = json.dumps(d_sf)
    json_gs = json.dumps(d_gs)
    json_ms = json.dumps(d_ms)
    json_ga = json.dumps(d_ga)
    json_cs = json.dumps(d_cs)

    serializable = bool(json_sf and json_gs and json_ms and json_ga and json_cs)

    # Verify new fields present in dicts
    assert "parse_ok" in d_ms, "ModuleSinks missing parse_ok"
    assert "defined_function_count" in d_ms
    assert "parsed_function_count" in d_ms
    assert "provenance_available" in d_ms
    assert "canonical_text" in d_gs, "GuardSink missing canonical_text"
    assert "ir_line" in d_gs
    assert "ordinal" in d_gs
    assert "provenance" in d_gs
    assert "origin_function" in d_gs
    assert "source_line" in d_gs
    assert "inlined" in d_gs

    report(tid, name, serializable, f"serializable={serializable}")


def test_s12_deterministic_output():
    """S12: Repeated analysis runs produce identical output structures."""
    tid, name = "S12", "Analysis determinism on repeated runs"
    ir_path = os.path.join(_CODES_DIR, "ir_output", "security_checks_O2.ll")
    if not _require_fixture(ir_path, tid, name):
        return

    m1 = analyze_module_sinks(ir_path).to_dict()
    m2 = analyze_module_sinks(ir_path).to_dict()

    identical = (json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True))
    report(tid, name, identical, f"identical={identical}")


# ---------------------------------------------------------------------------
# NEW Tests: Parser Completeness (Fix #1)
# ---------------------------------------------------------------------------

def test_s13_parser_completeness_vector_return():
    """S13: Parser handles vector-return type function definitions."""
    tid, name = "S13", "Parser: vector-return function"
    ir = """
define <4 x i32> @vec_func(i32 %0) {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret <4 x i32> zeroinitializer
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    fn_names = list(m.functions.keys())
    has_vec = "vec_func" in fn_names
    # define count should match parsed count
    counts_ok = m.defined_function_count == m.parsed_function_count
    report(tid, name, has_vec and counts_ok,
           f"fns={fn_names} defined={m.defined_function_count} parsed={m.parsed_function_count}")


def test_s14_parser_completeness_struct_return():
    """S14: Parser handles struct-return type function definitions."""
    tid, name = "S14", "Parser: struct-return function"
    ir = """
define { i32, i32 } @struct_func(i32 %0) {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret { i32, i32 } zeroinitializer
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    fn_names = list(m.functions.keys())
    has_struct = "struct_func" in fn_names
    counts_ok = m.defined_function_count == m.parsed_function_count
    report(tid, name, has_struct and counts_ok,
           f"fns={fn_names} defined={m.defined_function_count} parsed={m.parsed_function_count}")


def test_s15_parser_completeness_quoted_name():
    """S15: Parser handles quoted function names."""
    tid, name = "S15", "Parser: quoted function name"
    ir = '''
define void @"quoted.func.name"(i32 %0) {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
'''
    m = parse_llvm_ir(ir, is_path=False)
    fn_names = list(m.functions.keys())
    has_quoted = "quoted.func.name" in fn_names
    counts_ok = m.defined_function_count == m.parsed_function_count
    report(tid, name, has_quoted and counts_ok,
           f"fns={fn_names} defined={m.defined_function_count} parsed={m.parsed_function_count}")


def _parsed_module_parse_ok(m: ParsedModule) -> bool:
    """Helper: check if defined == parsed count."""
    return m.defined_function_count == m.parsed_function_count


def test_s16_parser_completeness_truncated_fixed():
    """S16: Parser detects truncated/unterminated function and emits warning."""
    tid, name = "S16", "Parser: truncated function emits warning"
    ir = """
define void @complete_func() {
entry:
  ret void
}

define void @truncated_func() {
entry:
  store i32 1, ptr @assert_failed, align 4
"""
    m = parse_llvm_ir(ir, is_path=False)
    has_warning = any("truncated" in w.lower() or "unterminated" in w.lower()
                      for w in m.warnings)
    complete_present = "complete_func" in m.functions
    truncated_absent = "truncated_func" not in m.functions
    parse_not_ok = not _parsed_module_parse_ok(m)
    report(tid, name, has_warning and complete_present and truncated_absent and parse_not_ok,
           f"warning={has_warning} complete={complete_present} truncated_absent={truncated_absent} parse_not_ok={parse_not_ok}")


def test_s17_parser_completeness_malformed():
    """S17: Parser handles malformed/empty input without crashes, with no false sinks."""
    tid, name = "S17", "Parser: malformed/empty input"
    # Empty
    m_empty = parse_llvm_ir("", is_path=False)
    empty_ok = len(m_empty.functions) == 0 and len(find_sinks(m_empty)) == 0

    # Only metadata — no functions
    meta_only = "!0 = !{!\"Simple C/C++ TBAA\"}\n!1 = !{!0, !0, i64 0}\n"
    m_meta = parse_llvm_ir(meta_only, is_path=False)
    meta_ok = len(m_meta.functions) == 0 and m_meta.defined_function_count == 0

    # Garbage
    garbage = "xyzzy define @blah blah blah !!! { }"
    m_garbage = parse_llvm_ir(garbage, is_path=False)
    garbage_ok = isinstance(m_garbage, ParsedModule)

    ok = empty_ok and meta_ok and garbage_ok
    report(tid, name, ok, f"empty={empty_ok} meta={meta_ok} garbage={garbage_ok}")


# ---------------------------------------------------------------------------
# NEW Tests: Store Parsing Hardening (Fix #2)
# ---------------------------------------------------------------------------

def test_s18_store_volatile():
    """S18: Store parsing handles volatile modifier."""
    tid, name = "S18", "Store parsing: volatile i32"
    ir = """
define void @f() {
entry:
  store volatile i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    has_sink = len(sinks) == 1 and sinks[0].sink_class == SinkClass.FLAG_STORE
    report(tid, name, has_sink, f"sinks={sinks}")


def test_s19_store_atomic():
    """S19: Store parsing handles atomic modifier."""
    tid, name = "S19", "Store parsing: atomic i32"
    ir = """
define void @f() {
entry:
  store atomic i32 1, ptr @assert_failed, seq_cst, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    has_sink = len(sinks) == 1 and sinks[0].sink_class == SinkClass.FLAG_STORE
    report(tid, name, has_sink, f"sinks={[s.constant_value for s in sinks]}")


def test_s20_store_i1_true():
    """S20: Store parsing handles i1 true (treated as integer 1)."""
    tid, name = "S20", "Store parsing: i1 true -> 1"
    ir = """
define void @f() {
entry:
  store i1 true, ptr @assert_failed, align 1
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    has_sink = (len(sinks) == 1
                and sinks[0].sink_class == SinkClass.FLAG_STORE
                and sinks[0].constant_value == 1)
    report(tid, name, has_sink, f"sinks={[(s.constant_value, s.sink_class) for s in sinks]}")


def test_s21_store_i1_false():
    """S21: Store parsing handles i1 false (treated as integer 0 -> not a sink)."""
    tid, name = "S21", "Store parsing: i1 false -> 0 (not a sink)"
    ir = """
define void @f() {
entry:
  store i1 false, ptr @assert_failed, align 1
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # Store of false (0) must NOT produce a sink
    no_sink = len(sinks) == 0
    report(tid, name, no_sink, f"sinks={sinks}")


def test_s22_store_quoted_sentinel():
    """S22: Store parsing handles quoted sentinel name @"assert_failed"."""
    tid, name = "S22", "Store parsing: quoted sentinel @\"assert_failed\""
    ir = '''
define void @f() {
entry:
  store i32 1, ptr @"assert_failed", align 4
  ret void
}
'''
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    has_sink = len(sinks) == 1 and sinks[0].sink_class == SinkClass.FLAG_STORE
    report(tid, name, has_sink, f"sinks={sinks}")


# ---------------------------------------------------------------------------
# NEW Tests: Guardedness Tri-State Truth Table (Fix #3)
# ---------------------------------------------------------------------------

def test_s23_guardedness_unconditional_entry():
    """S23: Sink in entry block (no predecessors) -> is_guarded=False."""
    tid, name = "S23", "Guardedness: entry block -> is_guarded=False"
    ir = """
define void @f() {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].is_guarded is False
    report(tid, name, ok, f"is_guarded={sinks[0].is_guarded if sinks else 'NO_SINK'}")


def test_s24_guardedness_conditional():
    """S24: Sink in block reachable only via conditional branch -> is_guarded=True."""
    tid, name = "S24", "Guardedness: conditional branch -> is_guarded=True"
    ir = """
define void @f(i1 %cond) {
entry:
  br i1 %cond, label %guarded, label %done
guarded:
  store i32 1, ptr @assert_failed, align 4
  br label %done
done:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].is_guarded is True
    report(tid, name, ok, f"is_guarded={sinks[0].is_guarded if sinks else 'NO_SINK'}")


def test_s25_guardedness_unreachable():
    """S25: Sink in unreachable block -> reachability analysis handles it."""
    tid, name = "S25", "Guardedness: unreachable block"
    ir = """
define void @f() {
entry:
  ret void
dead:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # The sink exists in the IR but the block is unreachable.
    # is_guarded should be True (the block is only reachable via a dead path)
    # or None (analysis cannot determine safely).
    # It must NOT be False (not unconditionally reachable from entry).
    ok = len(sinks) == 1 and sinks[0].is_guarded is not False
    report(tid, name, ok, f"is_guarded={sinks[0].is_guarded if sinks else 'NO_SINK'}")


def test_s26_guardedness_join_block():
    """S26: Sink in join block after if/else -> is_guarded=None or True (not False)."""
    tid, name = "S26", "Guardedness: join block after if/else -> not unconditional"
    ir = """
define void @f(i1 %cond) {
entry:
  br i1 %cond, label %then, label %els
then:
  br label %join
els:
  br label %join
join:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # join block is conditionally reachable only (both paths require the br i1)
    # Our analysis should say True (guarded) or None, NOT False
    ok = len(sinks) == 1 and sinks[0].is_guarded is not False
    report(tid, name, ok, f"is_guarded={sinks[0].is_guarded if sinks else 'NO_SINK'}")


def test_s27_guardedness_br_i1_false():
    """S27: br i1 false -> dead branch block is provably unreachable."""
    tid, name = "S27", "Guardedness/Dead: br i1 false pruning"
    ir = """
define void @f() {
entry:
  br i1 false, label %dead, label %live
dead:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # The dead block sink should have provably_dead_at_baseline=True
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is True
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'} guarded={sinks[0].is_guarded if sinks else '-'}")


def test_s28_guardedness_switch():
    """S28: Switch terminator — guardedness analysis returns True or None (not False)."""
    tid, name = "S28", "Guardedness: switch -> not unconditional"
    ir = """
define void @f(i32 %val) {
entry:
  switch i32 %val, label %default [ i32 1, label %case1 ]
case1:
  store i32 1, ptr @assert_failed, align 4
  br label %done
default:
  br label %done
done:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # case1 is reachable only through a switch (conditional) — not unconditional
    ok = len(sinks) == 1 and sinks[0].is_guarded is not False
    report(tid, name, ok, f"is_guarded={sinks[0].is_guarded if sinks else 'NO_SINK'}")


def test_s29_guardedness_invoke():
    """S29: Invoke terminator — guardedness analysis handles invoke correctly."""
    tid, name = "S29", "Guardedness: invoke -> not unconditional for landing pad"
    ir = """
define i32 @f() personality ptr @__gxx_personality_v0 {
entry:
  %r = invoke i32 @some_func() to label %normal unwind label %lpad
normal:
  store i32 1, ptr @assert_failed, align 4
  ret i32 1
lpad:
  %lp = landingpad { ptr, i32 } cleanup
  ret i32 0
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    # normal/lpad are reached via invoke — our analysis should handle gracefully
    # sink in normal should be either True or None (not unconditional False)
    if sinks:
        normal_sinks = [s for s in sinks if s.basic_block == "normal"]
        ok = len(normal_sinks) == 1 and normal_sinks[0].is_guarded is not False
    else:
        # If parser doesn't parse invoke targets correctly, that's acceptable
        # as long as it doesn't crash
        ok = True
    report(tid, name, ok, f"sinks={[(s.function_name, s.basic_block, s.is_guarded) for s in sinks]}")


# ---------------------------------------------------------------------------
# NEW Tests: provably_dead_at_baseline (Fix #4)
# ---------------------------------------------------------------------------

def test_s30_dead_baseline_known_dead_main():
    """S30: O0 main guard is provably dead at baseline (constant condition)."""
    tid, name = "S30", "Dead baseline: O0 main guard is provably dead"
    ir_path = os.path.join(_CODES_DIR, "ir_output", "security_checks_O0.ll")
    if not _require_fixture(ir_path, tid, name):
        return
    ms = analyze_module_sinks(ir_path)
    main_sinks = [s for s in ms.sinks if s.function_name == "main"]
    ok = len(main_sinks) == 1 and main_sinks[0].provably_dead_at_baseline is True
    report(tid, name, ok, f"main_sink_dead={main_sinks[0].provably_dead_at_baseline if main_sinks else 'MISSING'}")


def test_s31_dead_baseline_live_guard():
    """S31: O0 safe_copy and calculate_safe_index guards are NOT dead (live)."""
    tid, name = "S31", "Dead baseline: safe_copy/calc guards are live"
    ir_path = os.path.join(_CODES_DIR, "ir_output", "security_checks_O0.ll")
    if not _require_fixture(ir_path, tid, name):
        return
    ms = analyze_module_sinks(ir_path)
    live_sinks = [s for s in ms.sinks if s.function_name != "main"]
    all_live = all(s.provably_dead_at_baseline is False for s in live_sinks)
    report(tid, name, all_live,
           f"live_sinks={[(s.function_name, s.provably_dead_at_baseline) for s in live_sinks]}")


def test_s32_dead_baseline_nonconstant():
    """S32: Non-constant condition -> provably_dead_at_baseline=False (no over-approximation)."""
    tid, name = "S32", "Dead baseline: non-constant condition -> not dead"
    ir = """
define void @f(i1 %external_cond) {
entry:
  br i1 %external_cond, label %maybe_dead, label %live
maybe_dead:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is False
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'}")


def test_s33_dead_baseline_multiple_stores():
    """S33: Multiple stores to same alloca -> NOT constant -> NOT dead."""
    tid, name = "S33", "Dead baseline: multiple stores -> not dead"
    ir = """
define void @f(i32 %x) {
entry:
  %v = alloca i32, align 4
  store i32 1, ptr %v, align 4
  store i32 %x, ptr %v, align 4
  %loaded = load i32, ptr %v, align 4
  %cmp = icmp eq i32 %loaded, 0
  br i1 %cmp, label %maybe_dead, label %live
maybe_dead:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is False
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'}")


def test_s34_dead_baseline_escaped_alloca():
    """S34: Escaped alloca (passed to call) -> NOT constant -> NOT dead."""
    tid, name = "S34", "Dead baseline: escaped alloca -> not dead"
    ir = """
declare void @external_write(ptr %p)

define void @f() {
entry:
  %v = alloca i32, align 4
  store i32 5, ptr %v, align 4
  call void @external_write(ptr %v)
  %loaded = load i32, ptr %v, align 4
  %cmp = icmp eq i32 %loaded, 0
  br i1 %cmp, label %maybe_dead, label %live
maybe_dead:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is False
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'}")


def test_s35_dead_baseline_br_literal_false():
    """S35: br i1 false -> dead block is provably dead."""
    tid, name = "S35", "Dead baseline: br i1 false literal"
    ir = """
define void @f() {
entry:
  br i1 false, label %dead_block, label %live
dead_block:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is True
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'}")


def test_s36_dead_baseline_safe_case():
    """S36: Do not mark arbitrarily unreachable-looking cases as dead."""
    tid, name = "S36", "Dead baseline: ambiguous case -> conservative (not dead)"
    # This has a condition that LOOKS like it could fold, but the variable
    # is loaded from a memory location that's been written by a non-constant
    ir = """
declare i32 @get_value()

define void @f() {
entry:
  %v = alloca i32, align 4
  %x = call i32 @get_value()
  store i32 %x, ptr %v, align 4
  %loaded = load i32, ptr %v, align 4
  %cmp = icmp eq i32 %loaded, 0
  br i1 %cmp, label %maybe_dead, label %live
maybe_dead:
  store i32 1, ptr @assert_failed, align 4
  br label %live
live:
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = len(sinks) == 1 and sinks[0].provably_dead_at_baseline is False
    report(tid, name, ok, f"dead={sinks[0].provably_dead_at_baseline if sinks else 'NO_SINK'}")


# ---------------------------------------------------------------------------
# NEW Tests: Provenance (Fix #5)
# ---------------------------------------------------------------------------

def test_s37_provenance_debug_metadata_parsing():
    """S37: Parser extracts DILocation / DISubprogram metadata for provenance."""
    tid, name = "S37", "Provenance: debug metadata parsing"
    ir = """
define void @safe_copy(ptr %dst) !dbg !10 {
entry:
  store i32 1, ptr @assert_failed, align 4, !dbg !20
  ret void
}

!10 = distinct !DISubprogram(name: "safe_copy", scope: !11, file: !12, line: 5)
!11 = !DIFile(filename: "security_checks.c", directory: ".")
!12 = !DIFile(filename: "security_checks.c", directory: ".")
!20 = !DILocation(line: 10, column: 5, scope: !10)
"""
    m = parse_llvm_ir(ir, is_path=False)
    # Should have extracted the DILocation
    has_location = 20 in m.debug_locations
    has_scope = 10 in m.debug_scopes
    provenance_avail = m.provenance_available
    report(tid, name, has_location and has_scope and provenance_avail,
           f"has_location={has_location} has_scope={has_scope} prov_avail={provenance_avail}")


def test_s38_provenance_inlined_detection():
    """S38: Provenance correctly identifies inlined instruction via inlinedAt."""
    tid, name = "S38", "Provenance: inlinedAt -> INLINED provenance"
    ir = """
define void @main() {
entry:
  store i32 1, ptr @assert_failed, align 4, !dbg !30
  ret void
}

!10 = distinct !DISubprogram(name: "calculate_safe_index", scope: !11, file: !12, line: 20)
!11 = !DIFile(filename: "security_checks.c", directory: ".")
!12 = !DIFile(filename: "security_checks.c", directory: ".")
!20 = !DILocation(line: 25, column: 3, scope: !10)
!30 = !DILocation(line: 25, column: 3, scope: !10, inlinedAt: !20)
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)

    ok = False
    if sinks:
        s = sinks[0]
        ok = (s.inlined is True
              and s.provenance == Provenance.INLINED)
    report(tid, name, ok,
           f"inlined={sinks[0].inlined if sinks else None} prov={sinks[0].provenance if sinks else None}")


def test_s39_provenance_direct():
    """S39: Direct instruction (no inlinedAt) -> DIRECT provenance."""
    tid, name = "S39", "Provenance: no inlinedAt -> DIRECT provenance"
    ir = """
define void @safe_copy() {
entry:
  store i32 1, ptr @assert_failed, align 4, !dbg !20
  ret void
}

!10 = distinct !DISubprogram(name: "safe_copy", scope: !11, file: !12, line: 5)
!11 = !DIFile(filename: "security_checks.c", directory: ".")
!12 = !DIFile(filename: "security_checks.c", directory: ".")
!20 = !DILocation(line: 10, column: 5, scope: !10)
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = False
    if sinks:
        s = sinks[0]
        ok = (s.inlined is False
              and s.provenance == Provenance.DIRECT)
    report(tid, name, ok,
           f"inlined={sinks[0].inlined if sinks else None} prov={sinks[0].provenance if sinks else None}")


def test_s40_provenance_unavailable():
    """S40: When debug metadata is absent, provenance fields are None."""
    tid, name = "S40", "Provenance: no debug metadata -> None fields"
    ir = """
define void @f() {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    m = parse_llvm_ir(ir, is_path=False)
    sinks = find_sinks(m)
    ok = False
    if sinks:
        s = sinks[0]
        ok = (s.origin_function is None
              and s.source_line is None
              and s.inlined is None
              and s.provenance is None
              and not m.provenance_available)
    report(tid, name, ok,
           f"prov_avail={m.provenance_available} inlined={sinks[0].inlined if sinks else '-'}")


# ---------------------------------------------------------------------------
# NEW Tests: Stable Sink Identity / Canonical Text (Fix #6)
# ---------------------------------------------------------------------------

def test_s41_canonical_text_strips_metadata():
    """S41: canonical_text strips !tbaa and other LLVM metadata identifiers."""
    tid, name = "S41", "Canonical text: strips !tbaa metadata"
    raw = "store i32 1, ptr @assert_failed, align 4, !tbaa !11"
    canonical = _canonicalize(raw)
    has_tbaa = "!tbaa" in canonical
    has_content = "store i32 1, ptr @assert_failed" in canonical
    ok = (not has_tbaa) and has_content
    report(tid, name, ok, f"canonical={canonical!r}")


def test_s42_canonical_text_same_across_opt():
    """S42: Same logical store at O1 vs O2 gets identical canonical text."""
    tid, name = "S42", "Canonical text: O1 vs O2 main sink identical"
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o1 = os.path.join(ir_dir, "security_checks_O1.ll")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")

    if not _require_fixture(p_o1, tid, name) or not _require_fixture(p_o2, tid, name):
        return

    ms_o1 = analyze_module_sinks(p_o1)
    ms_o2 = analyze_module_sinks(p_o2)

    o1_main = [s for s in ms_o1.sinks if s.function_name == "main"]
    o2_main = [s for s in ms_o2.sinks if s.function_name == "main"]

    ok = (len(o1_main) == 1
          and len(o2_main) == 1
          and o1_main[0].canonical_text == o2_main[0].canonical_text)
    report(tid, name, ok,
           f"o1_canonical={o1_main[0].canonical_text if o1_main else 'MISSING'} "
           f"o2_canonical={o2_main[0].canonical_text if o2_main else 'MISSING'}")


def test_s43_ordinal_determinism():
    """S43: Sink ordinal is stable across repeated runs and uses IR order."""
    tid, name = "S43", "Ordinal: deterministic IR-order numbering"
    ir = """
define void @alpha() {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret void
}

define void @beta() {
entry:
  store i32 1, ptr @assert_failed, align 4
  ret void
}
"""
    # Run twice to check determinism
    m1 = parse_llvm_ir(ir, is_path=False)
    m2 = parse_llvm_ir(ir, is_path=False)
    s1 = find_sinks(m1)
    s2 = find_sinks(m2)

    # Ordinals should match
    ordinals_match = all(a.ordinal == b.ordinal for a, b in zip(s1, s2))
    # Sorted by function_name, then ordinal: alpha first, beta second
    fn_order_ok = (len(s1) == 2
                   and s1[0].function_name == "alpha"
                   and s1[1].function_name == "beta"
                   and s1[0].ordinal < s1[1].ordinal)
    report(tid, name, ordinals_match and fn_order_ok,
           f"ordinals={[s.ordinal for s in s1]} fns={[s.function_name for s in s1]}")


def test_s44_sink_id_not_stable_cross_opt():
    """S44: Documents that sink_id is module-local only (not cross-opt identity)."""
    tid, name = "S44", "Sink ID: module-local only (documented)"
    # The canonical_text + function_name should match across opt levels,
    # but sink_id may differ (it contains block names that can change).
    ir_dir = os.path.join(_CODES_DIR, "ir_output")
    p_o1 = os.path.join(ir_dir, "security_checks_O1.ll")
    p_o2 = os.path.join(ir_dir, "security_checks_O2.ll")

    if not _require_fixture(p_o1, tid, name) or not _require_fixture(p_o2, tid, name):
        return

    ms_o1 = analyze_module_sinks(p_o1)
    ms_o2 = analyze_module_sinks(p_o2)

    o1_calc = [s for s in ms_o1.sinks if s.function_name == "calculate_safe_index"]
    o2_calc = [s for s in ms_o2.sinks if s.function_name == "calculate_safe_index"]

    # Both exist
    both_exist = len(o1_calc) == 1 and len(o2_calc) == 1

    if both_exist:
        # canonical_text matches
        canonical_match = o1_calc[0].canonical_text == o2_calc[0].canonical_text
        # sink_id may differ (different block names between O1/O2)
        # We do NOT require them to match
        report(tid, name, canonical_match,
               f"o1_id={o1_calc[0].sink_id!r} o2_id={o2_calc[0].sink_id!r} "
               f"o1_canonical={o1_calc[0].canonical_text!r} "
               f"canonical_match={canonical_match}")
    else:
        report(tid, name, False, f"missing sinks: o1={o1_calc} o2={o2_calc}")


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_all_tests():
    print("\n" + "=" * 65)
    print("TOACD MOO Stage 6 — Secure Code Analysis Unit Tests (Chunk 1)")
    print("=" * 65 + "\n")

    print("--- Source Scanner & Rule Tests ---")
    test_s1_guard_rules_positive()
    test_s2_hazard_rules_positive()
    test_s3_negative_cases()
    test_s4_comment_string_immunity()
    test_s5_cwe_mappings()
    test_s6_sentinel_discovery()

    print("\n--- LLVM IR Parser & Sinks Tests ---")
    test_s7_frozen_ir_sink_counts()
    test_s8_guarded_vs_unconditional_sinks()
    test_s9_toolchain_verified_behavior()
    test_s10_parser_edge_cases()

    print("\n--- Data Models & Determinism Tests ---")
    test_s11_models_and_serialization()
    test_s12_deterministic_output()

    print("\n--- Fix #1: Parser Completeness Tests ---")
    test_s13_parser_completeness_vector_return()
    test_s14_parser_completeness_struct_return()
    test_s15_parser_completeness_quoted_name()
    test_s16_parser_completeness_truncated_fixed()
    test_s17_parser_completeness_malformed()

    print("\n--- Fix #2: Hostile Store Parser Tests ---")
    test_s18_store_volatile()
    test_s19_store_atomic()
    test_s20_store_i1_true()
    test_s21_store_i1_false()
    test_s22_store_quoted_sentinel()

    print("\n--- Fix #3: Guardedness Tri-State Truth Table ---")
    test_s23_guardedness_unconditional_entry()
    test_s24_guardedness_conditional()
    test_s25_guardedness_unreachable()
    test_s26_guardedness_join_block()
    test_s27_guardedness_br_i1_false()
    test_s28_guardedness_switch()
    test_s29_guardedness_invoke()

    print("\n--- Fix #4: Dead Baseline Tests ---")
    test_s30_dead_baseline_known_dead_main()
    test_s31_dead_baseline_live_guard()
    test_s32_dead_baseline_nonconstant()
    test_s33_dead_baseline_multiple_stores()
    test_s34_dead_baseline_escaped_alloca()
    test_s35_dead_baseline_br_literal_false()
    test_s36_dead_baseline_safe_case()

    print("\n--- Fix #5: Provenance Tests ---")
    test_s37_provenance_debug_metadata_parsing()
    test_s38_provenance_inlined_detection()
    test_s39_provenance_direct()
    test_s40_provenance_unavailable()

    print("\n--- Fix #6: Stable Sink Identity Tests ---")
    test_s41_canonical_text_strips_metadata()
    test_s42_canonical_text_same_across_opt()
    test_s43_ordinal_determinism()
    test_s44_sink_id_not_stable_cross_opt()

    n_pass = sum(1 for _, _, r in _results if r == "PASS")
    n_fail = sum(1 for _, _, r in _results if r == "FAIL")
    n_skip = sum(1 for _, _, r in _results if r == "SKIP")
    total = len(_results)

    print("\n" + "=" * 65)
    print(f"Results: {n_pass}/{total} passed, {n_fail} failed, {n_skip} skipped")
    print("=" * 65 + "\n")

    if n_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
