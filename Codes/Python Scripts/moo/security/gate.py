"""
moo.security.gate — Security Gate and Fallback Ladder for Week 13A.

Verdict action rules:
- NOT_APPLICABLE: ACCEPT
- PRESERVED: ACCEPT
- REDUCED: ACCEPT_WITH_WARNINGS (create LOW security event)
- ELIMINATED: REJECT candidate (create OPTIMIZATION_GUARD_VIOLATION event), trigger fallback ladder
- UNKNOWN / ERROR with baseline guards: ACCEPT_WITH_WARNINGS (unverified=True, create event), never claim safe

Fallback ladder:
  selected strategy -> up to 2 next-best strategies from q_rank -> BASELINE (-O0)
  BASELINE is terminal.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
import os
import tempfile
from typing import Any, Callable, Optional, Sequence

from .models import CandidateSecurity, CandidateVerdict
from .candidate import evaluate_candidate_security
from .ir_artifacts import emit_baseline_ir, emit_candidate_ir
from ..secevent.schema import (
    ThreatDomain,
    AttackType,
    EventSource,
    RiskLevel,
    ActionAttempted,
    ActionTaken,
    SecurityEvent,
)
from ..secevent.risk import Signal, compute_risk_assessment
from ..secevent.log import SecurityEventLog

BASELINE_TERMINAL_STRATEGY = "-O0"


class GateDecision(str, Enum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_WARNINGS = "ACCEPT_WITH_WARNINGS"
    FALLBACK = "FALLBACK"
    REJECT = "REJECT"


@dataclasses.dataclass
class GateResult:
    """Outcome of passing through the 13A Security Gate."""
    decision: GateDecision
    effective_strategy: str
    original_strategy: str
    candidate_security: CandidateSecurity
    fallback_occurred: bool = False
    fallback_history: list[str] = dataclasses.field(default_factory=list)
    unverified: bool = False
    security_events: list[SecurityEvent] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value if isinstance(self.decision, GateDecision) else str(self.decision),
            "effective_strategy": self.effective_strategy,
            "original_strategy": self.original_strategy,
            "candidate_security": self.candidate_security.to_dict(),
            "fallback_occurred": self.fallback_occurred,
            "fallback_history": list(self.fallback_history),
            "unverified": self.unverified,
            "security_events": [e.to_dict() for e in self.security_events],
            "notes": list(self.notes),
        }


class OptimizationSecurityGate:
    """
    Enforces candidate security verification and executes fallback ladder if necessary.
    """

    def __init__(
        self,
        event_log: Optional[SecurityEventLog] = None,
        clang_path: Optional[str] = None,
        opt_path: Optional[str] = None,
    ) -> None:
        self.event_log = event_log if event_log is not None else SecurityEventLog()
        self.clang_path = clang_path
        self.opt_path = opt_path

    def evaluate_gate_decision(
        self,
        candidate_sec: CandidateSecurity,
        run_id: Optional[str] = None,
    ) -> tuple[GateDecision, bool, list[SecurityEvent]]:
        """
        Map CandidateVerdict to GateDecision, unverified flag, and security events.
        """
        verdict = candidate_sec.verdict
        events: list[SecurityEvent] = []
        seq = self.event_log.next_sequence

        if verdict in (CandidateVerdict.NOT_APPLICABLE, CandidateVerdict.PRESERVED):
            return GateDecision.ACCEPT, False, []

        elif verdict == CandidateVerdict.REDUCED:
            sig = Signal("G_RED", "guard_reduced", 3, 0.80, evidence=f"Strategy {candidate_sec.strategy_name} merged/folded guards")
            risk = compute_risk_assessment([sig])
            evt = SecurityEvent.create(
                sequence=seq,
                threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
                attack_type=AttackType.OPTIMIZATION_GUARD_REDUCTION,
                source=EventSource.OPTIMIZATION_SECURITY_GATE,
                risk_level=risk.risk_level,
                score=risk.score,
                confidence=risk.confidence,
                evidence=f"{candidate_sec.merged_sinks} merged, {candidate_sec.folded_sinks} folded guards",
                action_attempted=ActionAttempted.REDUCE_GUARD,
                action_taken=ActionTaken.ALLOW_FLAGGED,
                blocked=False,
                reason="Optimization merged or folded security guards without outright elimination",
                affected_run_id=run_id,
                policy_rules=["GUARD_PRESERVATION_WARN"],
            )
            self.event_log.append(evt)
            events.append(evt)
            return GateDecision.ACCEPT_WITH_WARNINGS, False, events

        elif verdict == CandidateVerdict.ELIMINATED:
            sig = Signal("G_ELIM", "guard_elimination", 7, 0.95, evidence=f"{candidate_sec.eliminated_sinks} guards eliminated")
            risk = compute_risk_assessment([sig])
            evt = SecurityEvent.create(
                sequence=seq,
                threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
                attack_type=AttackType.OPTIMIZATION_GUARD_ELIMINATION,
                source=EventSource.OPTIMIZATION_SECURITY_GATE,
                risk_level=risk.risk_level,
                score=risk.score,
                confidence=risk.confidence,
                evidence=f"Strategy {candidate_sec.strategy_name} eliminated {candidate_sec.eliminated_sinks} guards",
                action_attempted=ActionAttempted.ELIMINATE_GUARD,
                action_taken=ActionTaken.BLOCK,
                blocked=True,
                reason="Optimization eliminated required security guards (HAZ-003 / CWE-570 violation)",
                affected_run_id=run_id,
                policy_rules=["GUARD_PRESERVATION_HARD"],
            )
            self.event_log.append(evt)
            events.append(evt)
            return GateDecision.FALLBACK, False, events

        elif verdict == CandidateVerdict.UNKNOWN:
            sig = Signal("G_UNK", "guard_unverified", 5, 0.60, evidence=f"Inconclusive verdict: {verdict}")
            risk = compute_risk_assessment([sig])
            evt = SecurityEvent.create(
                sequence=seq,
                threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
                attack_type=AttackType.GUARD_ERROR,
                source=EventSource.OPTIMIZATION_SECURITY_GATE,
                risk_level=risk.risk_level,
                score=risk.score,
                confidence=risk.confidence,
                evidence="; ".join(candidate_sec.warnings)[:256] or f"Verdict: {verdict}",
                action_attempted=ActionAttempted.UNKNOWN_ACTION,
                action_taken=ActionTaken.BLOCK,
                blocked=True,
                reason="Candidate IR security verification inconclusive (UNKNOWN); failing closed to fallback ladder",
                affected_run_id=run_id,
                policy_rules=["VERIFICATION_INTEGRITY_FAIL_CLOSED"],
            )
            self.event_log.append(evt)
            events.append(evt)
            return GateDecision.FALLBACK, True, events

        else:  # CandidateVerdict.ERROR
            sig = Signal("G_ERR", "guard_error", 6, 0.70, evidence=f"Verification error: {verdict}")
            risk = compute_risk_assessment([sig])
            evt = SecurityEvent.create(
                sequence=seq,
                threat_domain=ThreatDomain.OPTIMIZATION_SAFETY,
                attack_type=AttackType.GUARD_ERROR,
                source=EventSource.OPTIMIZATION_SECURITY_GATE,
                risk_level=risk.risk_level,
                score=risk.score,
                confidence=risk.confidence,
                evidence="; ".join(candidate_sec.warnings)[:256] or f"Verdict: {verdict}",
                action_attempted=ActionAttempted.UNKNOWN_ACTION,
                action_taken=ActionTaken.BLOCK,
                blocked=True,
                reason="Candidate IR security verification failed (ERROR); failing closed to fallback ladder",
                affected_run_id=run_id,
                policy_rules=["VERIFICATION_INTEGRITY_FAIL_CLOSED"],
            )
            self.event_log.append(evt)
            events.append(evt)
            return GateDecision.FALLBACK, True, events

    def run_gate(
        self,
        source_path: str,
        selected_strategy: str,
        q_rank: Optional[Sequence[tuple[str, float]]] = None,
        run_id: Optional[str] = None,
        custom_evaluator: Optional[Callable[[str], CandidateSecurity]] = None,
    ) -> GateResult:
        """
        Execute Security Gate with full Fallback Ladder.
        """
        fallback_history: list[str] = [selected_strategy]
        all_events: list[SecurityEvent] = []

        # Determine candidates in fallback order:
        # selected -> up to 2 next-best from q_rank -> BASELINE (-O0)
        candidates: list[str] = [selected_strategy]
        if q_rank:
            next_best = [s for s, _ in q_rank if s != selected_strategy and s != BASELINE_TERMINAL_STRATEGY]
            candidates.extend(next_best[:2])
        if BASELINE_TERMINAL_STRATEGY not in candidates:
            candidates.append(BASELINE_TERMINAL_STRATEGY)

        effective_sec: Optional[CandidateSecurity] = None
        effective_decision: GateDecision = GateDecision.FALLBACK
        effective_strat = selected_strategy
        unverified_flag = False

        with tempfile.TemporaryDirectory() as workdir:
            base_ir, base_err = emit_baseline_ir(source_path, workdir, self.clang_path) if not custom_evaluator else (None, None)

            for cand_strat in candidates:
                try:
                    if custom_evaluator:
                        cand_sec = custom_evaluator(cand_strat)
                    else:
                        if not base_ir:
                            cand_sec = CandidateSecurity(
                                strategy_name=cand_strat,
                                verdict=CandidateVerdict.ERROR,
                                warnings=[base_err or "Baseline IR emission failed"],
                            )
                        else:
                            cand_ir, cand_err = emit_candidate_ir(cand_strat, source_path, workdir, self.clang_path, self.opt_path)
                            if not cand_ir:
                                cand_sec = CandidateSecurity(
                                    strategy_name=cand_strat,
                                    verdict=CandidateVerdict.ERROR,
                                    warnings=[cand_err or "Candidate IR compilation failed"],
                                )
                            else:
                                cand_sec = evaluate_candidate_security(cand_strat, base_ir, cand_ir)
                except Exception as exc:
                    cand_sec = CandidateSecurity(
                        strategy_name=cand_strat,
                        verdict=CandidateVerdict.ERROR,
                        warnings=[f"Guard evaluation exception: {exc}"],
                    )

                decision, unverified, evts = self.evaluate_gate_decision(cand_sec, run_id=run_id)
                all_events.extend(evts)

                if decision in (GateDecision.ACCEPT, GateDecision.ACCEPT_WITH_WARNINGS):
                    effective_sec = cand_sec
                    effective_decision = decision
                    effective_strat = cand_strat
                    unverified_flag = unverified
                    break
                else:
                    # ELIMINATED or rejected -> continue down ladder
                    if cand_strat != BASELINE_TERMINAL_STRATEGY:
                        # Record next attempt in history
                        next_idx = candidates.index(cand_strat) + 1
                        if next_idx < len(candidates):
                            fallback_history.append(candidates[next_idx])

            # If all candidates rejected or failed, terminal baseline is enforced
            if effective_sec is None:
                effective_strat = BASELINE_TERMINAL_STRATEGY
                effective_decision = GateDecision.ACCEPT_WITH_WARNINGS
                unverified_flag = True
                effective_sec = CandidateSecurity(
                    strategy_name=BASELINE_TERMINAL_STRATEGY,
                    verdict=CandidateVerdict.UNKNOWN,
                    warnings=["All optimization candidates failed security gate; terminal baseline applied"],
                )

        fallback_occurred = (effective_strat != selected_strategy)

        return GateResult(
            decision=effective_decision,
            effective_strategy=effective_strat,
            original_strategy=selected_strategy,
            candidate_security=effective_sec,
            fallback_occurred=fallback_occurred,
            fallback_history=fallback_history,
            unverified=unverified_flag,
            security_events=all_events,
            notes=[
                f"Original: {selected_strategy}, Effective: {effective_strat}, Decision: {effective_decision.value}"
            ],
        )
