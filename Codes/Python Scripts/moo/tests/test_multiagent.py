"""
moo/tests/test_multiagent.py — Multi-Agent Communication Test Suite.

Covers:
- MA-SCHEMA: AgentMessage serialization, deserialization, type safety, monotonic step order.
- MA-LOG: MessageLog append-only ordering, filtering, and JSON persistence.
- MA-AGENTS: Unit testing of individual agents with structured inputs and outputs.
- MA-PROPOSAL: Strategist initial proposal formatting and provenance.
- MA-REVIEW-ACCEPT: Clean proposal review acceptance without alert findings.
- MA-REVIEW-REJECT: Conflicted proposal review rejection with structured feedback.
- MA-REVISION: Strategist revision on receiving rejection feedback (candidate progression).
- MA-REVISION-LIMIT: Strict revision bound enforcement (MAX_REVISIONS = 2).
- MA-BENCHMARK: BenchmarkAgent execution and failure handling without zero fabrication.
- MA-FINAL: FinalDecisionAgent applying security gate and fallback logic.
- MA-ORCHESTRATOR: Full end-to-end multi-agent execution producing valid RunRecord.
- MA-IMMUT: Message immutability and context preservation.
- MA-FAILURE: Missing file, compiler error, and toolchain absence handling.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(_HERE))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from moo.multiagent.schema import (
    AgentMessage,
    MessageType,
    ROLE_CODE_ANALYST,
    ROLE_PROGRAM_PROFILING,
    ROLE_OPTIMIZATION_STRATEGIST,
    ROLE_OPTIMIZATION_REVIEWER,
    ROLE_BENCHMARK,
    ROLE_FINAL_DECISION,
    ROLE_ORCHESTRATOR,
    MSG_IR_FEATURES,
    MSG_PROFILE,
    MSG_STRATEGY_PROPOSAL,
    MSG_REVIEW_ACCEPT,
    MSG_REVIEW_REJECT,
    MSG_STRATEGY_REVISED,
    MSG_BENCHMARK_RESULT,
    MSG_FINAL_DECISION,
    MSG_ERROR,
)
from moo.multiagent.message_log import MessageLog
from moo.multiagent.agents import (
    CodeAnalystAgent,
    ProgramProfilingAgent,
    OptimizationStrategistAgent,
    OptimizationReviewerAgent,
    BenchmarkAgent,
    FinalDecisionAgent,
)
from moo.multiagent.orchestrator import MultiAgentOrchestrator
from moo.runrecord.schema import RunRecord, RunStatus, MeasurementStatus


class TestMultiAgentSystem(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sample_c = os.path.join(self.temp_dir, "sample.c")
        with open(self.sample_c, "w", encoding="utf-8") as f:
            f.write("int main(void) { int sum = 0; for(int i=0; i<10; i++) sum += i; return sum; }\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ----------------------------------------------------------------
    # 1. MA-SCHEMA: Message Protocol and Serialization
    # ----------------------------------------------------------------
    def test_schema_message_serialization_roundtrip(self):
        msg = AgentMessage.create(
            sender=ROLE_CODE_ANALYST,
            recipient=ROLE_ORCHESTRATOR,
            message_type=MSG_IR_FEATURES,
            payload={"ir_features": {"BasicBlocksCount": 3.0}},
            run_id="run_test_01",
            step=1,
        )
        d = msg.to_dict()
        self.assertEqual(d["sender"], ROLE_CODE_ANALYST)
        self.assertEqual(d["message_type"], MSG_IR_FEATURES)
        self.assertEqual(d["step"], 1)

        restored = AgentMessage.from_dict(d)
        self.assertEqual(restored.message_id, msg.message_id)
        self.assertEqual(restored.payload, msg.payload)
        self.assertEqual(restored.timestamp, msg.timestamp)

    def test_schema_immutability(self):
        msg = AgentMessage.create(
            sender=ROLE_OPTIMIZATION_STRATEGIST,
            recipient=ROLE_OPTIMIZATION_REVIEWER,
            message_type=MSG_STRATEGY_PROPOSAL,
            payload={"strategy": "-O2"},
            run_id="run_test_01",
            step=1,
        )
        with self.assertRaises(Exception):
            msg.step = 2  # frozen dataclass

    # ----------------------------------------------------------------
    # 2. MA-LOG: MessageLog Management
    # ----------------------------------------------------------------
    def test_messagelog_append_and_filtering(self):
        log = MessageLog(run_id="run_log_01")
        m1 = AgentMessage.create(ROLE_CODE_ANALYST, ROLE_ORCHESTRATOR, MSG_IR_FEATURES, {}, "run_log_01", 1)
        m2 = AgentMessage.create(ROLE_PROGRAM_PROFILING, ROLE_ORCHESTRATOR, MSG_PROFILE, {}, "run_log_01", 2)
        log.append(m1)
        log.append(m2)

        self.assertEqual(len(log), 2)
        self.assertEqual(len(log.filter_by_sender(ROLE_CODE_ANALYST)), 1)
        self.assertEqual(len(log.filter_by_type(MSG_PROFILE)), 1)

        raw_list = log.to_list()
        self.assertEqual(len(raw_list), 2)
        restored = MessageLog.from_list(raw_list, run_id="run_log_01")
        self.assertEqual(len(restored), 2)

    # ----------------------------------------------------------------
    # 3. MA-AGENTS: CodeAnalyst & ProgramProfiling
    # ----------------------------------------------------------------
    def test_code_analyst_valid_and_missing_source(self):
        agent = CodeAnalystAgent()
        res = agent.analyze(self.sample_c, run_id="run_ca_01", step=1)
        self.assertEqual(res.message_type, MSG_IR_FEATURES)
        self.assertIn("ir_features", res.payload)

        # Missing source
        res_missing = agent.analyze("non_existent_file.c", run_id="run_ca_01", step=2)
        self.assertEqual(res_missing.message_type, MSG_ERROR)
        self.assertFalse(res_missing.payload.get("recoverable"))

    def test_program_profiling_agent(self):
        ca = CodeAnalystAgent()
        ca_msg = ca.analyze(self.sample_c, run_id="run_pp_01", step=1)

        pp = ProgramProfilingAgent()
        pp_msg = pp.profile(ca_msg, step=2)
        self.assertEqual(pp_msg.message_type, MSG_PROFILE)
        self.assertIn("label", pp_msg.payload.get("profile", {}))

    # ----------------------------------------------------------------
    # 4. MA-PROPOSAL: Strategist Initial Proposal
    # ----------------------------------------------------------------
    def test_strategist_initial_proposal(self):
        strat = OptimizationStrategistAgent()
        prop = strat.initial_proposal(self.sample_c, run_id="run_st_01", step=3)
        self.assertEqual(prop.message_type, MSG_STRATEGY_PROPOSAL)
        self.assertEqual(prop.recipient, ROLE_OPTIMIZATION_REVIEWER)
        self.assertIn("strategy", prop.payload)
        self.assertEqual(prop.payload.get("revision_number"), 0)

    # ----------------------------------------------------------------
    # 5. MA-REVIEW-ACCEPT: Clean Proposal Review Acceptance
    # ----------------------------------------------------------------
    def test_reviewer_accepts_clean_proposal(self):
        reviewer = OptimizationReviewerAgent()
        proposal = AgentMessage.create(
            sender=ROLE_OPTIMIZATION_STRATEGIST,
            recipient=ROLE_OPTIMIZATION_REVIEWER,
            message_type=MSG_STRATEGY_PROPOSAL,
            payload={
                "strategy": "-O2",
                "provenance": "DQN_MOO",
                "decision_trace": {
                    "final_strategy": "-O2",
                    "selection_method": "moo_aware",
                    "pareto_frontier": ["-O2"],
                },
                "revision_number": 0,
            },
            run_id="run_rev_01",
            step=4,
        )
        rev_msg = reviewer.review_proposal(proposal, step=5)
        self.assertEqual(rev_msg.message_type, MSG_REVIEW_ACCEPT)
        self.assertEqual(rev_msg.payload.get("decision"), "ACCEPT")
        self.assertEqual(rev_msg.payload.get("strategy"), "-O2")

    # ----------------------------------------------------------------
    # 6. MA-REVIEW-REJECT: Conflicted Proposal Feedback
    # ----------------------------------------------------------------
    def test_reviewer_rejects_conflicted_proposal(self):
        reviewer = OptimizationReviewerAgent()
        # Strategy says -O3, but trace recorded final_strategy as -O1 (ALERT mismatch)
        proposal = AgentMessage.create(
            sender=ROLE_OPTIMIZATION_STRATEGIST,
            recipient=ROLE_OPTIMIZATION_REVIEWER,
            message_type=MSG_STRATEGY_PROPOSAL,
            payload={
                "strategy": "-O3",
                "provenance": "DQN_ARGMAX",
                "decision_trace": {
                    "final_strategy": "-O1",
                    "selection_method": "moo_aware",
                },
                "revision_number": 0,
            },
            run_id="run_rev_02",
            step=4,
        )
        rev_msg = reviewer.review_proposal(proposal, step=5)
        self.assertEqual(rev_msg.message_type, MSG_REVIEW_REJECT)
        self.assertEqual(rev_msg.recipient, ROLE_OPTIMIZATION_STRATEGIST)
        self.assertIn("conflicts", rev_msg.payload.get("feedback", ""))

    # ----------------------------------------------------------------
    # 7. MA-REVISION: Strategist Revises on Feedback
    # ----------------------------------------------------------------
    def test_strategist_revision_loop(self):
        strat = OptimizationStrategistAgent()
        strat.cached_q_rank = [("-O3", 0.9), ("-O2", 0.8), ("-O1", 0.7)]
        strat.tried_strategies = ["-O3"]

        rejection = AgentMessage.create(
            sender=ROLE_OPTIMIZATION_REVIEWER,
            recipient=ROLE_OPTIMIZATION_STRATEGIST,
            message_type=MSG_REVIEW_REJECT,
            payload={
                "strategy": "-O3",
                "feedback": "Conflict detected",
                "revision_number": 0,
            },
            run_id="run_rev_03",
            step=5,
        )

        revised = strat.revise_proposal(rejection, step=6)
        self.assertEqual(revised.message_type, MSG_STRATEGY_REVISED)
        self.assertEqual(revised.payload.get("strategy"), "-O2")  # Next highest Q
        self.assertEqual(revised.payload.get("revision_number"), 1)
        self.assertIn("-O2", strat.tried_strategies)

    # ----------------------------------------------------------------
    # 8. MA-REVISION-LIMIT: Max Revisions Enforcement
    # ----------------------------------------------------------------
    def test_orchestrator_max_revisions_enforcement(self):
        # Create a reviewer that ALWAYS rejects
        mock_reviewer = OptimizationReviewerAgent()
        mock_reviewer.review_proposal = MagicMock(
            side_effect=lambda prop, step, **kwargs: AgentMessage.create(
                sender=ROLE_OPTIMIZATION_REVIEWER,
                recipient=ROLE_OPTIMIZATION_STRATEGIST,
                message_type=MSG_REVIEW_REJECT,
                payload={"strategy": prop.payload["strategy"], "feedback": "Permanent reject", "revision_number": prop.payload["revision_number"]},
                run_id=prop.run_id,
                step=step,
            )
        )

        orch = MultiAgentOrchestrator(reviewer=mock_reviewer)
        record, log = orch.run(self.sample_c, run_benchmarks=False, run_security=False, max_revisions=2)

        # Revision count must be bounded at 2
        rejections = log.filter_by_type(MSG_REVIEW_REJECT)
        self.assertLessEqual(len(rejections), 3)
        self.assertTrue(any("Max revisions (2) exhausted" in n for n in record.run_notes))

    # ----------------------------------------------------------------
    # 9. MA-BENCHMARK: BenchmarkAgent Measurement & Failure
    # ----------------------------------------------------------------
    def test_benchmark_agent_mock_success_and_failure(self):
        agent = BenchmarkAgent()

        with patch("moo.pipeline.evaluate_program") as mock_eval:
            mock_eval.return_value = MagicMock(to_dict=lambda: {"status": "OK", "timing": 0.05})
            res = agent.benchmark(self.sample_c, "-O2", "run_b_01", step=6)
            self.assertEqual(res.message_type, MSG_BENCHMARK_RESULT)
            self.assertEqual(res.payload.get("status"), "OK")

        with patch("moo.pipeline.evaluate_program", side_effect=RuntimeError("Clang timeout")):
            res_fail = agent.benchmark(self.sample_c, "-O2", "run_b_02", step=7)
            self.assertEqual(res_fail.message_type, MSG_BENCHMARK_RESULT)
            self.assertEqual(res_fail.payload.get("status"), "FAILED")
            self.assertIn("Clang timeout", res_fail.payload.get("error", ""))

    # ----------------------------------------------------------------
    # 10. MA-FINAL: FinalDecisionAgent & Security Gate Fallback
    # ----------------------------------------------------------------
    def test_final_decision_agent_security_fallback(self):
        fda = FinalDecisionAgent()

        # Gate mock triggering fallback to -O1
        with patch("moo.security.gate.OptimizationSecurityGate.run_gate") as mock_gate:
            gate_mock_res = MagicMock(
                effective_strategy="-O1",
                fallback_occurred=True,
                security_events=[],
                to_dict=lambda: {"effective_strategy": "-O1", "fallback_occurred": True},
            )
            mock_gate.return_value = gate_mock_res

            msg = fda.decide(
                source_path=self.sample_c,
                selected_strategy="-O3",
                q_rank=[("-O3", 0.9), ("-O1", 0.7)],
                decision_trace=None,
                run_id="run_fd_01",
                step=8,
                run_security=True,
                toolchain_ok=True,
            )

            self.assertEqual(msg.message_type, MSG_FINAL_DECISION)
            self.assertEqual(msg.payload.get("selected_strategy"), "-O3")
            self.assertEqual(msg.payload.get("effective_strategy"), "-O1")
            self.assertTrue(msg.payload.get("fallback_occurred"))

    # ----------------------------------------------------------------
    # 11. MA-ORCHESTRATOR: Full Pipeline Coordination
    # ----------------------------------------------------------------
    def test_orchestrator_full_run_produces_runrecord_and_log(self):
        orch = MultiAgentOrchestrator()
        record, log = orch.run(
            self.sample_c,
            run_benchmarks=False,  # Skip live clang compilation in unit test
            run_security=False,
            run_regression=False,
            run_adaptive=False,
            run_agentic=True,
        )

        self.assertIsInstance(record, RunRecord)
        self.assertGreater(len(log), 4)

        # Monotonic steps
        steps = [m.step for m in log]
        self.assertEqual(steps, sorted(steps))

        # Check that chronological multiagent log was attached
        log_notes = [n for n in record.run_notes if n.startswith("[MULTIAGENT_LOG]")]
        self.assertTrue(len(log_notes) > 0)

        # Deserialization test of embedded log
        raw_json = log_notes[0].replace("[MULTIAGENT_LOG] ", "")
        parsed = json.loads(raw_json)
        self.assertIsInstance(parsed, list)
        self.assertEqual(parsed[0]["sender"], ROLE_CODE_ANALYST)


if __name__ == "__main__":
    unittest.main()
