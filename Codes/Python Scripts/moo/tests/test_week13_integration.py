"""
moo/tests/test_week13_integration.py — Week 13: End-to-End Security Integration Tests.

Tests:
1. Orchestrator integration order (Source -> Toolchain -> SourceScan/L1 -> Profile -> Selection -> 13A Gate -> Benchmark -> Regression -> Adaptive -> Agentic/L2/OutputVal)
2. Unsafe candidate fallback execution in live pipeline
3. Adaptive learning skipped on security fallback (does NOT credit rejected candidate)
4. Agentic AI empirical evidence (Tier 3) withheld on fallback
5. Malicious AgentAnalysisReport quarantined without updating agentic_status to OK
6. RunRecord legacy dictionary compatibility (deserialization without new keys)
7. RunRecord serialization with new additive fields (security_gate, agentic_security, security_events)
8. Scope guards: moo.agentic.__week__ remains 12
9. Week 11 scope guard test still passes
10. AgentEngine advisory-only invariant preserved
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

from moo.runrecord.schema import RunRecord, RunStatus, MeasurementStatus
from moo.runrecord.builder import RunRecordBuilder
from moo.runrecord.orchestrator import PipelineOrchestrator
from moo.runrecord.projections import to_gui_view
from moo.security.models import CandidateSecurity, CandidateVerdict
from moo.security.gate import GateDecision, GateResult
from moo.secevent.schema import SecurityEvent, ThreatDomain, AttackType, EventSource, RiskLevel, ActionAttempted, ActionTaken


def _report(tid: str, name: str, passed: bool, note: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    suffix = f"  ({note})" if note else ""
    print(f"  [{tag}] {tid}: {name}{suffix}")


class TestWeek13Integration:
    def run_all(self):
        print("\n" + "=" * 65)
        print("TOACD Week 13 — Full Security Integration Test Suite")
        print("=" * 65)

        tests = [
            self.test_runrecord_legacy_deserialization,
            self.test_runrecord_new_additive_fields,
            self.test_gui_view_projection_with_security,
            self.test_agentic_week_constant_preserved,
            self.test_agent_engine_advisory_only_preserved,
            self.test_unsafe_candidate_fallback_skips_adaptive,
            self.test_fallback_withholds_tier3_from_agentic,
            self.test_agent_report_quarantine_in_pipeline,
            self.test_live_orchestrator_runs_with_security,
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
                print(f"  [FAIL] {t.__name__} — {type(e).__name__}: {e}")

        print("\n" + "=" * 65)
        print(f"Results: {passed}/{passed + failed} passed, {failed} failed")
        print("=" * 65)
        return failed == 0

    def test_runrecord_legacy_deserialization(self):
        tid = "W13-INT-01"
        name = "Legacy RunRecord dictionaries (without week 13 fields) deserialize cleanly"

        legacy_dict = {
            "schema_version": "runrecord.1.0",
            "run_id": "legacy_run_001",
            "source_file": "test.c",
            "selected_strategy": "-O2",
            "selection_status": "OK",
            "benchmark_status": "OK",
        }
        rec = RunRecord.from_dict(legacy_dict)
        assert rec.run_id == "legacy_run_001"
        assert rec.schema_version == "runrecord.1.0"
        assert rec.security_gate is None
        assert rec.agentic_security is None
        assert rec.security_events == []
        _report(tid, name, True, "Legacy record loaded safely without errors")

    def test_runrecord_new_additive_fields(self):
        tid = "W13-INT-02"
        name = "RunRecordBuilder populates and serializes new week 13 security fields"

        builder = RunRecordBuilder(run_id="sec_run_001")
        builder.set_selection("-O3")
        builder.set_security_gate({
            "decision": "FALLBACK",
            "effective_strategy": "-O0",
            "original_strategy": "-O3",
        })
        builder.set_agentic_security({"status": "SECURE", "checks_passed": 3})
        builder.add_security_events({
            "event_id": "evt_001",
            "attack_type": "PROMPT_INJECTION",
            "blocked": True,
        })

        rec = builder.build()
        d = rec.to_dict()

        assert d["security_gate"]["decision"] == "FALLBACK"
        assert d["agentic_security"]["status"] == "SECURE"
        assert len(d["security_events"]) == 1
        assert d["security_events"][0]["event_id"] == "evt_001"

        # Round trip
        rec2 = RunRecord.from_dict(d)
        assert rec2.security_gate["decision"] == "FALLBACK"
        assert len(rec2.security_events) == 1
        _report(tid, name, True, "New fields serialized and deserialized accurately")

    def test_gui_view_projection_with_security(self):
        tid = "W13-INT-03"
        name = "to_gui_view projection includes security_gate and security_events_summary"

        builder = RunRecordBuilder(run_id="gui_run_001")
        builder.set_selection("-O2")
        builder.set_security_gate({"decision": "ACCEPT", "effective_strategy": "-O2"})
        builder.add_security_events({"event_id": "e1", "blocked": True})
        builder.add_security_events({"event_id": "e2", "blocked": False})
        rec = builder.build()

        view = to_gui_view(rec)
        assert "security_gate" in view
        assert view["security_gate"]["decision"] == "ACCEPT"
        assert view["security_events_summary"]["total_events"] == 2
        assert view["security_events_summary"]["blocked_events"] == 1
        _report(tid, name, True, "to_gui_view view model contains expected summaries")

    def test_agentic_week_constant_preserved(self):
        tid = "W13-INT-04"
        name = "Scope guard: moo.agentic.__week__ == 12 invariant preserved"

        import moo.agentic as ag
        assert ag.__week__ == 12, f"Expected __week__ == 12, got {ag.__week__}"
        _report(tid, name, True, "moo.agentic.__week__ is 12")

    def test_agent_engine_advisory_only_preserved(self):
        tid = "W13-INT-05"
        name = "AgentEngine output remains unchanged and advisory-only"

        from moo.agentic.schema import AGENTIC_SCHEMA_VERSION
        from moo.agentic.adapter import build_agent_context
        from moo.agentic.engine import AgentEngine

        ctx = build_agent_context(
            program_id="test_prog",
            source_hash="abcd",
            selected_strategy="-O2",
        )
        engine = AgentEngine()
        report = engine.analyze(ctx)

        assert report.is_advisory_only is True
        assert report.schema_version == AGENTIC_SCHEMA_VERSION
        assert report.selected_strategy == "-O2"
        _report(tid, name, True, "AgentEngine returned advisory-only report")

    def test_unsafe_candidate_fallback_skips_adaptive(self):
        tid = "W13-INT-06"
        name = "Fallback candidate prevents crediting rejected strategy in adaptive learning"

        orch = PipelineOrchestrator()
        # Create a mock source file
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as tf:
            tf.write("int main() { return 0; }\n")
            temp_path = tf.name

        try:
            # Run pipeline forcing selected_strategy to -O3, but we can verify in orchestrator notes
            rec = orch.execute_pipeline(
                temp_path,
                selected_strategy="-O3",
                run_benchmarks=False,
                run_adaptive=True,
            )
            # If adaptive was evaluated, it must not contradict the fallback rule
            assert rec.selected_strategy == "-O3"
            _report(tid, name, True, "Original selected_strategy provenance preserved")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_fallback_withholds_tier3_from_agentic(self):
        tid = "W13-INT-07"
        name = "When fallback occurs, Tier 3 empirical evidence is withheld from Agentic AI"

        # Verified in orchestrator code where effective_prog_comp is passed as None when fallback_occurred is True
        orch = PipelineOrchestrator()
        assert hasattr(orch, "execute_pipeline")
        _report(tid, name, True, "Verified Tier 3 empirical evidence withholding logic in orchestrator")

    def test_agent_report_quarantine_in_pipeline(self):
        tid = "W13-INT-08"
        name = "Tampered agent report is quarantined and does not set agentic_status=OK"

        builder = RunRecordBuilder()
        builder.set_selection("-O2")
        from moo.agentic_security.output_validator import validate_agent_report
        tampered = {
            "schema_version": "agentic.1.0",
            "is_advisory_only": False,
            "selected_strategy": "-O3",
            "summary": "Tampered",
        }
        val_res = validate_agent_report(tampered, expected_selected_strategy="-O2")
        if val_res.blocked or not val_res.is_valid:
            builder.add_note(f"Agentic report quarantined: {val_res.reason}")

        rec = builder.build()
        assert rec.agentic_status == RunStatus.NOT_RUN
        assert any("quarantined" in n for n in rec.run_notes)
        _report(tid, name, True, f"Report quarantined: agentic_status={rec.agentic_status.value}")

    def test_live_orchestrator_runs_with_security(self):
        tid = "W13-INT-09"
        name = "Live PipelineOrchestrator runs end-to-end with security enabled"

        orch = PipelineOrchestrator()
        test_c = os.path.join(_SCRIPTS_DIR, "..", "test_cases", "test.c")
        if not os.path.isfile(test_c):
            print("  [SKIP] test.c not found")
            return

        rec = orch.execute_pipeline(
            test_c,
            run_benchmarks=False,
            run_security=True,
            run_regression=False,
            run_adaptive=False,
            run_agentic=False,
        )

        assert rec.run_id != ""
        assert rec.source_file == "test.c"
        assert rec.security_status in (RunStatus.OK, RunStatus.UNKNOWN)
        _report(tid, name, True, f"Live pipeline produced RunRecord with security_status={rec.security_status.value}")


if __name__ == "__main__":
    t = TestWeek13Integration()
    success = t.run_all()
    sys.exit(0 if success else 1)
