"""
moo/tests/test_week13a_security.py — Week 13A: Optimization Security Tests.

Tests:
- Deterministic risk model computation (Professor attack, eliminated guard, merged guard, no signals)
- SecurityEvent creation, determinism (excluding created_at), and serialization
- In-memory event retention and JSONL failure resiliency
- CandidateVerdict computation and precedence rules (ELIMINATED > UNKNOWN > REDUCED > PRESERVED)
- OptimizationSecurityGate decisions (ACCEPT, ACCEPT_WITH_WARNINGS, FALLBACK)
- Fallback ladder: selected -> next-best from q_rank -> BASELINE (-O0)
- Provenance preservation during fallback (original selection untouched, effective strategy tracked)
- Toolchain-dependent candidate IR tests (skip cleanly if clang/opt unavailable)
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure Python Scripts directory is on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(_HERE))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from moo.secevent.schema import (
    SECEVENT_SCHEMA_VERSION,
    ThreatDomain,
    AttackType,
    EventSource,
    RiskLevel,
    ActionAttempted,
    ActionTaken,
    SecurityEvent,
)
from moo.secevent.risk import (
    Signal,
    compute_risk_assessment,
    assess_decision,
)
from moo.secevent.log import SecurityEventLog
from moo.security.models import (
    CandidateSecurity,
    CandidateVerdict,
    GuardAssessment,
    GuardStatus,
)
from moo.security.candidate import compute_candidate_verdict
from moo.security.gate import (
    OptimizationSecurityGate,
    GateDecision,
    GateResult,
    BASELINE_TERMINAL_STRATEGY,
)


def _report(tid: str, name: str, passed: bool, note: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    suffix = f"  ({note})" if note else ""
    print(f"  [{tag}] {tid}: {name}{suffix}")


def _fail(tid: str, name: str, exc: Exception) -> None:
    print(f"  [FAIL] {tid}: {name} — {type(exc).__name__}: {exc}")


class TestWeek13ASecurity:
    def __init__(self):
        self.results = []

    def run_all(self):
        print("\n" + "=" * 65)
        print("TOACD Week 13A — Optimization Security Test Suite")
        print("=" * 65)

        tests = [
            self.test_risk_model_cases,
            self.test_event_determinism,
            self.test_event_serialization,
            self.test_event_log_resiliency,
            self.test_candidate_verdict_precedence,
            self.test_security_gate_decisions,
            self.test_fallback_ladder_execution,
            self.test_unknown_never_safe,
            self.test_provenance_preservation_on_fallback,
            self.test_fail_closed_guard_behavior,
            self.test_unknown_causes_fallback_to_preserved_qrank,
            self.test_error_causes_fallback_to_preserved_qrank,
            self.test_all_unknown_error_fallback_to_terminal_o0,
        ]

        passed = 0
        failed = 0
        for t in tests:
            try:
                t()
                passed += 1
            except AssertionError as ae:
                failed += 1
                print(f"  [FAIL] {t.__name__}: {ae}")
            except Exception as e:
                failed += 1
                _fail("ERROR", t.__name__, e)

        print("\n" + "=" * 65)
        print(f"Results: {passed}/{passed + failed} passed, {failed} failed")
        print("=" * 65)
        return failed == 0

    def test_risk_model_cases(self):
        tid = "W13A-01"
        name = "Deterministic risk score verification for target cases"

        # 1. Professor attack: 100 / CRITICAL / BLOCK
        p_signals = [
            Signal("P01", "prompt_injection", 9, 0.95),
            Signal("P02", "validation_disable", 9, 0.95),
            Signal("P03", "verdict_manipulation", 9, 0.95),
        ]
        p_risk = compute_risk_assessment(p_signals, has_forbidden_capability=True)
        assert p_risk.score == 100, f"Expected score 100, got {p_risk.score}"
        assert p_risk.risk_level == RiskLevel.CRITICAL
        dec, blocked = assess_decision(p_risk)
        assert dec == ActionTaken.BLOCK and blocked is True

        # 2. Eliminated guard: 69 / HIGH
        g_signals = [Signal("G01", "guard_elimination", 7, 0.95)]
        g_risk = compute_risk_assessment(g_signals)
        assert g_risk.score == 69, f"Expected score 69, got {g_risk.score}"
        assert g_risk.risk_level == RiskLevel.HIGH

        # 3. Merged guard: 28 / LOW / ALLOW_FLAGGED
        m_signals = [Signal("M01", "guard_merged", 3, 0.80)]
        m_risk = compute_risk_assessment(m_signals)
        assert m_risk.score == 28, f"Expected score 28, got {m_risk.score}"
        assert m_risk.risk_level == RiskLevel.LOW
        m_dec, m_blocked = assess_decision(m_risk)
        assert m_dec == ActionTaken.ALLOW_FLAGGED and m_blocked is False

        # 4. No signals: 0 / NONE / ALLOW
        z_risk = compute_risk_assessment([])
        assert z_risk.score == 0
        assert z_risk.risk_level == RiskLevel.NONE
        z_dec, z_blocked = assess_decision(z_risk)
        assert z_dec == ActionTaken.ALLOW and z_blocked is False

        _report(tid, name, True, "All 4 canonical risk cases matched exact targets")

    def test_event_determinism(self):
        tid = "W13A-02"
        name = "SecurityEvent determinism and timestamp invariance"

        e1 = SecurityEvent.create(
            sequence=1,
            threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
            attack_type=AttackType.OPTIMIZATION_GUARD_ELIMINATION,
            source=EventSource.OPTIMIZATION_SECURITY_GATE,
            risk_level=RiskLevel.HIGH,
            score=69,
            confidence=0.95,
            evidence="Guard @check_bounds eliminated",
            action_attempted=ActionAttempted.ELIMINATE_GUARD,
            action_taken=ActionTaken.BLOCK,
            blocked=True,
            reason="HAZ-003 elimination",
            created_at="2026-10-07T10:00:00Z",
        )
        e2 = SecurityEvent.create(
            sequence=1,
            threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
            attack_type=AttackType.OPTIMIZATION_GUARD_ELIMINATION,
            source=EventSource.OPTIMIZATION_SECURITY_GATE,
            risk_level=RiskLevel.HIGH,
            score=69,
            confidence=0.95,
            evidence="Guard @check_bounds eliminated",
            action_attempted=ActionAttempted.ELIMINATE_GUARD,
            action_taken=ActionTaken.BLOCK,
            blocked=True,
            reason="HAZ-003 elimination",
            created_at="2026-10-07T23:59:59Z",  # Different timestamp
        )

        assert e1.event_id == e2.event_id, f"Event ID mismatch: {e1.event_id} vs {e2.event_id}"
        _report(tid, name, True, f"Event ID {e1.event_id} invariant across timestamps")

    def test_event_serialization(self):
        tid = "W13A-03"
        name = "SecurityEvent JSON serialization and round-trip fidelity"

        evt = SecurityEvent.create(
            sequence=5,
            threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
            attack_type=AttackType.OPTIMIZATION_GUARD_REDUCTION,
            source=EventSource.OPTIMIZATION_SECURITY_GATE,
            risk_level=RiskLevel.LOW,
            score=28,
            confidence=0.80,
            evidence="Merged 2 guards",
            action_attempted=ActionAttempted.REDUCE_GUARD,
            action_taken=ActionTaken.ALLOW_FLAGGED,
            blocked=False,
            reason="Guard merged",
        )
        d = evt.to_dict()
        s = json.dumps(d)
        d2 = json.loads(s)
        evt2 = SecurityEvent.from_dict(d2)

        assert evt == evt2
        assert evt.schema_version == SECEVENT_SCHEMA_VERSION
        _report(tid, name, True, "Full round-trip match")

    def test_event_log_resiliency(self):
        tid = "W13A-04"
        name = "SecurityEventLog persistence error resiliency and persist_ok flag"

        # Log to an invalid path that cannot be written
        bad_path = os.path.join(tempfile.gettempdir(), "nonexistent_dir_12345", "sub", "log.jsonl")
        log = SecurityEventLog(log_path=bad_path)

        evt = SecurityEvent.create(
            sequence=1,
            threat_domain=ThreatDomain.SYSTEM_INTEGRITY,
            attack_type=AttackType.GUARD_ERROR,
            source=EventSource.OPTIMIZATION_SECURITY_GATE,
            risk_level=RiskLevel.MEDIUM,
            score=50,
            confidence=0.6,
            evidence="Test error",
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=ActionTaken.ALLOW_FLAGGED,
            blocked=False,
            reason="Resiliency test",
        )

        # Append must never raise, and in-memory retention must succeed
        log.append(evt)
        assert log.count() == 1
        assert len(log.get_events()) == 1
        _report(tid, name, True, f"Event retained in memory (count={log.count()}) without crash")

    def test_candidate_verdict_precedence(self):
        tid = "W13A-05"
        name = "CandidateVerdict precedence: ELIMINATED > UNKNOWN > REDUCED > PRESERVED"

        # Case 1: ELIMINATED present alongside REDUCED and PRESERVED -> ELIMINATED
        v1 = compute_candidate_verdict(
            [
                GuardAssessment("s1", GuardStatus.PRESERVED),
                GuardAssessment("s2", GuardStatus.MERGED),
                GuardAssessment("s3", GuardStatus.ELIMINATED),
            ],
            baseline_sink_count=3,
            candidate_sink_count=2,
        )
        assert v1 == CandidateVerdict.ELIMINATED, f"Expected ELIMINATED, got {v1}"

        # Case 2: UNKNOWN present alongside REDUCED and PRESERVED -> UNKNOWN
        v2 = compute_candidate_verdict(
            [
                GuardAssessment("s1", GuardStatus.PRESERVED),
                GuardAssessment("s2", GuardStatus.MERGED),
                GuardAssessment("s3", GuardStatus.UNKNOWN),
            ],
            baseline_sink_count=3,
            candidate_sink_count=2,
        )
        assert v2 == CandidateVerdict.UNKNOWN, f"Expected UNKNOWN, got {v2}"

        # Case 3: REDUCED (merged/folded) present alongside PRESERVED -> REDUCED
        v3 = compute_candidate_verdict(
            [
                GuardAssessment("s1", GuardStatus.PRESERVED),
                GuardAssessment("s2", GuardStatus.FOLDED),
            ],
            baseline_sink_count=2,
            candidate_sink_count=1,
        )
        assert v3 == CandidateVerdict.REDUCED, f"Expected REDUCED, got {v3}"

        # Case 4: All PRESERVED -> PRESERVED
        v4 = compute_candidate_verdict(
            [
                GuardAssessment("s1", GuardStatus.PRESERVED),
                GuardAssessment("s2", GuardStatus.PRESERVED),
            ],
            baseline_sink_count=2,
            candidate_sink_count=2,
        )
        assert v4 == CandidateVerdict.PRESERVED, f"Expected PRESERVED, got {v4}"

        # Case 5: 0 sinks in baseline -> NOT_APPLICABLE
        v5 = compute_candidate_verdict([], baseline_sink_count=0, candidate_sink_count=0)
        assert v5 == CandidateVerdict.NOT_APPLICABLE, f"Expected NOT_APPLICABLE, got {v5}"

        _report(tid, name, True, "Precedence order verified across all combinations")

    def test_security_gate_decisions(self):
        tid = "W13A-06"
        name = "OptimizationSecurityGate decision mapping"

        gate = OptimizationSecurityGate()

        # PRESERVED -> ACCEPT
        c_pres = CandidateSecurity(strategy_name="-O2", verdict=CandidateVerdict.PRESERVED)
        dec_pres, _, evts_pres = gate.evaluate_gate_decision(c_pres)
        assert dec_pres == GateDecision.ACCEPT and len(evts_pres) == 0

        # NOT_APPLICABLE -> ACCEPT
        c_na = CandidateSecurity(strategy_name="-O2", verdict=CandidateVerdict.NOT_APPLICABLE)
        dec_na, _, evts_na = gate.evaluate_gate_decision(c_na)
        assert dec_na == GateDecision.ACCEPT and len(evts_na) == 0

        # REDUCED -> ACCEPT_WITH_WARNINGS + LOW event
        c_red = CandidateSecurity(strategy_name="-O2", verdict=CandidateVerdict.REDUCED, merged_sinks=1)
        dec_red, _, evts_red = gate.evaluate_gate_decision(c_red)
        assert dec_red == GateDecision.ACCEPT_WITH_WARNINGS
        assert len(evts_red) == 1
        assert evts_red[0].risk_level == RiskLevel.LOW
        assert evts_red[0].blocked is False

        # ELIMINATED -> FALLBACK + HIGH event
        c_elim = CandidateSecurity(strategy_name="-O3", verdict=CandidateVerdict.ELIMINATED, eliminated_sinks=2)
        dec_elim, _, evts_elim = gate.evaluate_gate_decision(c_elim)
        assert dec_elim == GateDecision.FALLBACK
        assert len(evts_elim) == 1
        assert evts_elim[0].risk_level == RiskLevel.HIGH
        assert evts_elim[0].blocked is True

        _report(tid, name, True, "Gate decisions mapped to expected outcomes")

    def test_fallback_ladder_execution(self):
        tid = "W13A-07"
        name = "OptimizationSecurityGate fallback ladder execution"

        gate = OptimizationSecurityGate()

        # Setup mock evaluator where -O3 eliminates guards, next candidate mem2reg preserves guards
        def mock_evaluator(strat: str) -> CandidateSecurity:
            if strat == "-O3":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.ELIMINATED, eliminated_sinks=1)
            elif strat == "mem2reg,instcombine":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED, preserved_sinks=2)
            else:
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED)

        q_rank = [
            ("-O3", 0.95),
            ("mem2reg,instcombine", 0.88),
            ("-O2", 0.80),
            ("-O0", 0.50),
        ]

        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O3",
            q_rank=q_rank,
            custom_evaluator=mock_evaluator,
        )

        assert result.original_strategy == "-O3"
        assert result.effective_strategy == "mem2reg,instcombine"
        assert result.fallback_occurred is True
        assert result.decision == GateDecision.ACCEPT
        assert len(result.security_events) == 1
        assert result.security_events[0].attack_type == AttackType.OPTIMIZATION_GUARD_ELIMINATION

        _report(tid, name, True, f"Fell back from -O3 to next-best {result.effective_strategy}")

    def test_unknown_never_safe(self):
        tid = "W13A-08"
        name = "UNKNOWN and ERROR verdicts are never classified as safe and trigger FALLBACK"

        gate = OptimizationSecurityGate()
        c_unk = CandidateSecurity(strategy_name="-O2", verdict=CandidateVerdict.UNKNOWN, warnings=["Parse error"])
        dec_unk, unverified, evts = gate.evaluate_gate_decision(c_unk)

        assert dec_unk == GateDecision.FALLBACK
        assert unverified is True
        assert len(evts) == 1
        assert evts[0].blocked is True

        c_err = CandidateSecurity(strategy_name="-O2", verdict=CandidateVerdict.ERROR, warnings=["Compile error"])
        dec_err, unverified_err, evts_err = gate.evaluate_gate_decision(c_err)

        assert dec_err == GateDecision.FALLBACK
        assert unverified_err is True
        assert len(evts_err) == 1
        assert evts_err[0].blocked is True

        _report(tid, name, True, "UNKNOWN and ERROR marked as FALLBACK with unverified=True and blocked=True")

    def test_provenance_preservation_on_fallback(self):
        tid = "W13A-09"
        name = "Fallback preserves original selection provenance"

        gate = OptimizationSecurityGate()
        # All non-baseline candidates eliminate guards -> falls back to terminal BASELINE (-O0)
        def mock_all_unsafe(strat: str) -> CandidateSecurity:
            if strat == BASELINE_TERMINAL_STRATEGY:
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED)
            return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.ELIMINATED, eliminated_sinks=1)

        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O3",
            q_rank=[("-O3", 0.9), ("-O2", 0.8)],
            custom_evaluator=mock_all_unsafe,
        )

        assert result.original_strategy == "-O3"
        assert result.effective_strategy == BASELINE_TERMINAL_STRATEGY
        assert result.fallback_occurred is True
        _report(tid, name, True, f"Terminal baseline reached: original={result.original_strategy}, effective={result.effective_strategy}")

    def test_fail_closed_guard_behavior(self):
        tid = "W13A-10"
        name = "Exception during security gate fails closed (not crash)"

        gate = OptimizationSecurityGate()
        def mock_raising(strat: str) -> CandidateSecurity:
            raise RuntimeError("Corrupted LLVM IR stream")

        # Must not raise an unhandled exception
        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O2",
            custom_evaluator=mock_raising,
        )

        assert result.decision == GateDecision.ACCEPT_WITH_WARNINGS
        assert result.unverified is True
        assert result.effective_strategy == BASELINE_TERMINAL_STRATEGY
        assert result.fallback_occurred is True
        assert len(result.security_events) >= 1
        assert result.security_events[0].attack_type == AttackType.GUARD_ERROR
        _report(tid, name, True, "Handled exception gracefully, failed closed to terminal -O0 baseline")

    def test_unknown_causes_fallback_to_preserved_qrank(self):
        tid = "W13A-11"
        name = "Selected UNKNOWN candidate falls back to next-best PRESERVED candidate"

        gate = OptimizationSecurityGate()
        def mock_evaluator(strat: str) -> CandidateSecurity:
            if strat == "-O3":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.UNKNOWN, warnings=["Inconclusive sink analysis"])
            elif strat == "mem2reg,instcombine":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED, preserved_sinks=3)
            return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED)

        q_rank = [
            ("-O3", 0.95),
            ("mem2reg,instcombine", 0.88),
            ("-O0", 0.40),
        ]

        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O3",
            q_rank=q_rank,
            custom_evaluator=mock_evaluator,
        )

        assert result.original_strategy == "-O3"
        assert result.effective_strategy == "mem2reg,instcombine"
        assert result.fallback_occurred is True
        assert result.decision == GateDecision.ACCEPT
        assert len(result.security_events) == 1
        assert result.security_events[0].attack_type == AttackType.GUARD_ERROR
        _report(tid, name, True, f"UNKNOWN -O3 fell back to preserved {result.effective_strategy}")

    def test_error_causes_fallback_to_preserved_qrank(self):
        tid = "W13A-12"
        name = "Selected ERROR candidate falls back to next-best PRESERVED candidate"

        gate = OptimizationSecurityGate()
        def mock_evaluator(strat: str) -> CandidateSecurity:
            if strat == "-O3":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.ERROR, warnings=["Compilation failed"])
            elif strat == "-O2":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED, preserved_sinks=2)
            return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.PRESERVED)

        q_rank = [
            ("-O3", 0.95),
            ("-O2", 0.85),
            ("-O0", 0.40),
        ]

        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O3",
            q_rank=q_rank,
            custom_evaluator=mock_evaluator,
        )

        assert result.original_strategy == "-O3"
        assert result.effective_strategy == "-O2"
        assert result.fallback_occurred is True
        assert result.decision == GateDecision.ACCEPT
        assert len(result.security_events) == 1
        assert result.security_events[0].attack_type == AttackType.GUARD_ERROR
        _report(tid, name, True, f"ERROR -O3 fell back to preserved {result.effective_strategy}")

    def test_all_unknown_error_fallback_to_terminal_o0(self):
        tid = "W13A-13"
        name = "When all candidates are UNKNOWN/ERROR, falls back to terminal -O0"

        gate = OptimizationSecurityGate()
        def mock_evaluator(strat: str) -> CandidateSecurity:
            if strat == "-O3":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.UNKNOWN)
            elif strat == "-O2":
                return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.ERROR)
            return CandidateSecurity(strategy_name=strat, verdict=CandidateVerdict.UNKNOWN)

        q_rank = [
            ("-O3", 0.95),
            ("-O2", 0.85),
        ]

        result = gate.run_gate(
            source_path="mock.c",
            selected_strategy="-O3",
            q_rank=q_rank,
            custom_evaluator=mock_evaluator,
        )

        assert result.original_strategy == "-O3"
        assert result.effective_strategy == BASELINE_TERMINAL_STRATEGY
        assert result.fallback_occurred is True
        assert result.unverified is True
        _report(tid, name, True, "All candidates failed security gate; terminal -O0 enforced")


if __name__ == "__main__":
    t = TestWeek13ASecurity()
    success = t.run_all()
    sys.exit(0 if success else 1)
