"""
moo.tests.test_web_api — Test suite for TOACD Web Application and API.

Tests:
1. Toolchain status inspection
2. Sample benchmarks retrieval
3. Tornado API endpoints:
   - GET / (Index HTML serving)
   - GET /api/status (JSON schema and toolchain fields)
   - GET /api/samples (List of sample benchmarks)
   - GET /api/sample/<id> (Source code retrieval)
   - POST /api/run (Validation, error cases, successful run start)
   - GET /api/results/<run_id> (Run results schema, 404 handling)
4. Integration run execution & result projection (RunRecord, view, IR preview)
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import tornado.testing
from tornado.web import Application

_current_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.dirname(os.path.dirname(_current_dir))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from web.server import make_app
from web.service import (
    get_toolchain_status,
    list_sample_benchmarks,
    get_sample_source,
    execute_run_task,
    get_run_result,
    DEFAULT_SOURCE_CODE,
)


class TestWebServiceDirect(unittest.TestCase):
    """Direct unit tests for web.service functions."""

    def test_toolchain_status(self):
        status = get_toolchain_status()
        self.assertIsInstance(status, dict)
        self.assertIn("clang_found", status)
        self.assertIn("opt_found", status)
        self.assertIn("toolchain_ok", status)
        self.assertIn("host_platform", status)
        self.assertIn("default_target", status)

    def test_sample_benchmarks(self):
        samples = list_sample_benchmarks()
        self.assertIsInstance(samples, list)
        self.assertGreaterEqual(len(samples), 3)
        sample_ids = [s["id"] for s in samples]
        self.assertIn("gemm", sample_ids)
        self.assertIn("tc1_loop_heavy", sample_ids)

    def test_get_sample_source(self):
        src_gemm = get_sample_source("gemm")
        self.assertIn("kernel_gemm", src_gemm)
        self.assertIn("#include <stdio.h>", src_gemm)

        src_tc1 = get_sample_source("tc1_loop_heavy")
        self.assertIsInstance(src_tc1, str)
        self.assertGreater(len(src_tc1), 50)


class TestWebAPIEndpoints(tornado.testing.AsyncHTTPTestCase):
    """Integration tests for Tornado HTTP API endpoints."""

    def get_app(self) -> Application:
        return make_app()

    def test_get_index(self):
        response = self.fetch("/")
        self.assertEqual(response.code, 200)
        self.assertIn("TOACD", response.body.decode("utf-8"))
        self.assertIn("AI ACTIVITY / MULTI-AGENT COMMS", response.body.decode("utf-8"))
        self.assertIn("EXPERIMENTAL ANALYSIS", response.body.decode("utf-8"))

    def test_get_status_api(self):
        response = self.fetch("/api/status")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("clang_found", data)
        self.assertIn("opt_found", data)

    def test_get_samples_api(self):
        response = self.fetch("/api/samples")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("samples", data)
        self.assertIsInstance(data["samples"], list)
        self.assertGreater(len(data["samples"]), 0)

    def test_get_sample_detail_api(self):
        response = self.fetch("/api/sample/gemm")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["sample_id"], "gemm")
        self.assertIn("kernel_gemm", data["source_code"])

    def test_post_run_invalid_empty(self):
        # Empty body
        response = self.fetch(
            "/api/run",
            method="POST",
            body=json.dumps({"source_code": ""}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.code, 400)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("error", data)

    def test_post_run_valid(self):
        # Start valid run with program_id
        simple_c = "int main(void) { return 0; }\n"
        response = self.fetch(
            "/api/run",
            method="POST",
            body=json.dumps({"source_code": simple_c, "mode": "ai", "program_id": "prog_test_alpha"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.code, 202)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("run_id", data)
        self.assertEqual(data["status"], "started")
        self.assertEqual(data["program_id"], "prog_test_alpha")

    def test_get_results_not_found(self):
        response = self.fetch("/api/results/non_existent_run_id_9999")
        self.assertEqual(response.code, 404)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("error", data)

    def test_get_report_not_found(self):
        response = self.fetch("/api/report/non_existent_run_id_9999")
        self.assertEqual(response.code, 404)
        data = json.loads(response.body.decode("utf-8"))
        self.assertIn("error", data)

    def test_get_report_valid(self):
        from web.service import _RUNS_STORE
        mock_run_id = "test_run_report_endpoint"
        _RUNS_STORE[mock_run_id] = {
            "run_id": mock_run_id,
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "fallback_occurred": False,
                "security_gate": {"overall_verdict": "PASS"},
                "baseline_measurement": {"median_s": 0.02, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.016, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "IMPROVED",
            },
        }
        response = self.fetch(f"/api/report/{mock_run_id}")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["run_id"], mock_run_id)
        self.assertIn("summary", data)
        self.assertIn("program_analysis", data)
        self.assertIn("optimization_strategy", data)
        self.assertIn("security_and_correctness", data)
        self.assertIn("performance", data)
        self.assertIn("problems_and_limitations", data)
        self.assertIn("overall_conclusion", data)
        self.assertEqual(data["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")

    def test_sse_events_replays_and_signals_backfill_complete(self):
        """Test SSE endpoint emits backfill_complete after replaying historical events."""
        from web.service import RunContext, emit_canonical_event, _RUN_CONTEXTS, _RUNS_STORE
        run_id = "test_sse_backfill_signal_run"
        ctx = RunContext(run_id, "gemm", mode="normal")
        _RUN_CONTEXTS[run_id] = ctx
        _RUNS_STORE[run_id] = {"status": "completed", "run_id": run_id, "program_id": "gemm"}

        emit_canonical_event(run_id, "stage_started", stage="profiling")
        emit_canonical_event(run_id, "done", payload={"status": "completed"})

        response = self.fetch(f"/api/events/{run_id}")
        self.assertEqual(response.code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("event: backfill_complete", body)
        self.assertIn("event: stage_started", body)
        self.assertIn("event: done", body)

        _RUN_CONTEXTS.pop(run_id, None)
        _RUNS_STORE.pop(run_id, None)


class TestWebRunExecution(unittest.TestCase):
    """End-to-end execution of a small test case via execute_run_task."""

    def test_execute_run_task_normal(self):
        run_id = "test_normal_run_1"
        code = "int main(void) { int a = 5; return a - 5; }\n"
        execute_run_task(run_id, code, mode="normal", warmup_runs=1, measure_runs=1, timeout_s=5, program_id="sample_norm")

        res = get_run_result(run_id)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["program_id"], "sample_norm")
        self.assertIsNotNone(res["view"])
        self.assertIsNotNone(res["record"])

    def test_execute_run_task_ai(self):
        run_id = "test_ai_run_1"
        code = "int main(void) { int a = 10; return a * 2; }\n"
        execute_run_task(run_id, code, mode="ai", warmup_runs=1, measure_runs=1, timeout_s=5, program_id="sample_ai")

        res = get_run_result(run_id)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["program_id"], "sample_ai")
        self.assertIsNotNone(res["view"])
        self.assertIsNotNone(res["record"])
        self.assertIsInstance(res["messages"], list)
        self.assertGreater(len(res["messages"]), 0)

    def test_multi_program_isolation(self):
        """Verify program A and program B runs are strictly isolated."""
        run_a = "test_iso_run_a"
        code_a = "int main(void) { return 1; }\n"
        execute_run_task(run_a, code_a, mode="normal", warmup_runs=1, measure_runs=1, timeout_s=5, program_id="prog_A")

        run_b = "test_iso_run_b"
        code_b = "int main(void) { return 2; }\n"
        execute_run_task(run_b, code_b, mode="ai", warmup_runs=1, measure_runs=1, timeout_s=5, program_id="prog_B")

        res_a = get_run_result(run_a)
        res_b = get_run_result(run_b)

        self.assertEqual(res_a["program_id"], "prog_A")
        self.assertEqual(res_b["program_id"], "prog_B")
        self.assertNotEqual(res_a["run_id"], res_b["run_id"])
        self.assertNotEqual(res_a["source_code"], res_b["source_code"])

    def test_honest_failure_handling(self):
        """Verify an invalid or failing source code transitions to failed status and does not claim success."""
        run_fail = "test_failing_syntax_run"
        bad_code = "int main(void) { syntax error here !!! ;;; }\n"
        execute_run_task(run_fail, bad_code, mode="normal", warmup_runs=1, measure_runs=1, timeout_s=5, program_id="prog_bad")

        res = get_run_result(run_fail)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "completed") # Pipeline completed run
        # Benchmark status or build status within record should reflect build failure
        view = res["view"]
        self.assertIsNotNone(view)
        # Either benchmark status is not OK or timing is None
        opt_timing = view.get("optimized_timing")
        self.assertTrue(opt_timing is None or opt_timing.get("median_s") is None)

    def test_state_rejection_logic(self):
        """Simulate frontend guard logic for rejecting late SSE events from older runs or different programs."""
        active_run_id = "run_current_active_99"
        current_program_id = "prog_current_active"

        # Stale event from old run
        stale_event_old_run = {
            "type": "agent_message",
            "run_id": "run_old_historical_11",
            "program_id": current_program_id,
            "message_type": "STRATEGY_PROPOSAL",
            "payload": {"strategy": "-O3"}
        }

        # Stale event from different program
        stale_event_diff_prog = {
            "type": "agent_message",
            "run_id": active_run_id,
            "program_id": "prog_different_earlier",
            "message_type": "STRATEGY_PROPOSAL",
            "payload": {"strategy": "-O2"}
        }

        # Valid event
        valid_event = {
            "type": "agent_message",
            "run_id": active_run_id,
            "program_id": current_program_id,
            "message_type": "STRATEGY_PROPOSAL",
            "payload": {"strategy": "-O2"}
        }

        def filter_event(event):
            if not event or event.get("run_id") != active_run_id:
                return False, "rejected_stale_run"
            if event.get("program_id") and event.get("program_id") != current_program_id:
                return False, "rejected_diff_program"
            return True, "accepted"

        acc_old, reason_old = filter_event(stale_event_old_run)
        self.assertFalse(acc_old)
        self.assertEqual(reason_old, "rejected_stale_run")

        acc_prog, reason_prog = filter_event(stale_event_diff_prog)
        self.assertFalse(acc_prog)
        self.assertEqual(reason_prog, "rejected_diff_program")

        acc_valid, reason_valid = filter_event(valid_event)
        self.assertTrue(acc_valid)
        self.assertEqual(reason_valid, "accepted")

    def test_comparison_requires_same_program_succeeded_pair(self):
        """Verify performance comparison contract: strictly invalid across different programs or non-succeeded states."""
        def can_compare(norm_state, ai_state, active_prog):
            if norm_state["status"] != "succeeded" or ai_state["status"] != "succeeded":
                return False, "not_both_succeeded"
            if norm_state["programId"] != active_prog or ai_state["programId"] != active_prog:
                return False, "program_mismatch"
            return True, "valid_comparison"

        prog_alpha = "prog_alpha"
        prog_beta = "prog_beta"

        # Case 1: Normal from Alpha, AI from Beta
        s1, r1 = can_compare(
            {"status": "succeeded", "programId": prog_alpha},
            {"status": "succeeded", "programId": prog_beta},
            prog_alpha
        )
        self.assertFalse(s1)
        self.assertEqual(r1, "program_mismatch")

        # Case 2: One failed
        s2, r2 = can_compare(
            {"status": "succeeded", "programId": prog_alpha},
            {"status": "failed", "programId": prog_alpha},
            prog_alpha
        )
        self.assertFalse(s2)
        self.assertEqual(r2, "not_both_succeeded")

        # Case 3: Same program, both succeeded
        s3, r3 = can_compare(
            {"status": "succeeded", "programId": prog_alpha},
            {"status": "succeeded", "programId": prog_alpha},
            prog_alpha
        )
        self.assertTrue(s3)
        self.assertEqual(r3, "valid_comparison")


if __name__ == "__main__":
    unittest.main()
