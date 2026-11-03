"""
moo/tests/test_workflow_report.py — Deterministic tests for Phase 1C Plain-English Workflow Report.

Verifies:
1. Successful normal run.
2. Successful AI-optimized run.
3. Compilation failure.
4. Security blocked operation.
5. Security fallback.
6. Correctness-verification failure.
7. Inconclusive benchmark.
8. Confirmed performance improvement.
9. Confirmed performance regression.
10. Missing performance measurements.
11. Missing correctness-verification data.
12. Missing security-verification data.
13. Missing optimization rationale.
14. Missing or malformed run records.
15. Ensuring events from different runs are never mixed.
16. Correct use of the authoritative benchmark verdict.
17. Safe provenance categorization.
"""

import unittest
from web.report import generate_workflow_report, ReportProvenance


class TestWorkflowReport(unittest.TestCase):

    def test_01_successful_normal_run(self):
        run_data = {
            "run_id": "run_norm_01",
            "program_id": "gemm",
            "mode": "normal",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3",
                "effective_strategy": "-O3",
                "fallback_occurred": False,
                "ir_features": {
                    "total_instructions": 120,
                    "vectorizable_loops": 3,
                    "load_instructions": 40,
                    "store_instructions": 20,
                    "branch_instructions": 10,
                },
                "program_profile": {
                    "label": "loop_oriented",
                    "dominant_feature": "vectorizable_loops",
                },
                "baseline_measurement": None,
                "optimized_measurement": {
                    "median_s": 0.015,
                    "code_size_bytes": 1420,
                    "timing_is_reliable": True,
                    "status": "OK",
                },
            },
            "view": {
                "optimized_timing": {"median_s": 0.015, "code_size_bytes": 1420},
            },
            "is_valid_reference": True,
            "elapsed_s": 0.45,
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["run_id"], "run_norm_01")
        self.assertEqual(rep["mode"], "normal")
        self.assertEqual(rep["status"], "completed")
        self.assertEqual(rep["summary"]["mode_label"], "Standard Baseline Reference (-O3)")
        self.assertTrue(rep["summary"]["is_conclusive"])
        self.assertIn("Baseline Reference Run (-O3) Completed", rep["summary"]["headline"])
        self.assertEqual(rep["security_and_correctness"]["security_status"], "Skipped")
        self.assertEqual(rep["security_and_correctness"]["compilation_status"], "Passed")
        self.assertEqual(rep["security_and_correctness"]["correctness_status"], "Passed")
        self.assertEqual(rep["program_analysis"]["profile_label"], "loop_oriented")
        self.assertEqual(rep["program_analysis"]["provenance"], ReportProvenance.PROFILED.value)
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "BASELINE_READY")
        self.assertTrue(rep["overall_conclusion"]["execution_succeeded"])
        self.assertTrue(rep["overall_conclusion"]["compilation_succeeded"])
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])  # Normal run does not claim AI speedup

    def test_02_successful_ai_optimized_run(self):
        run_data = {
            "run_id": "run_ai_01",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "fallback_occurred": False,
                "decision_trace": {
                    "selection_reason": "High loop density favors -O2 pipeline balancing code size and throughput.",
                },
                "security_gate": {
                    "overall_verdict": "PASS",
                    "fallback_triggered": False,
                },
                "baseline_measurement": {
                    "median_s": 0.020,
                    "code_size_bytes": 1600,
                    "timing_is_reliable": True,
                    "status": "OK",
                },
                "optimized_measurement": {
                    "median_s": 0.016,
                    "code_size_bytes": 1450,
                    "timing_is_reliable": True,
                    "status": "OK",
                },
                "regression_overall_status": "IMPROVED",
            },
            "view": {
                "regression_overall_status": "IMPROVED",
                "baseline_timing": {"median_s": 0.020, "code_size_bytes": 1600},
                "optimized_timing": {"median_s": 0.016, "code_size_bytes": 1450},
            },
            "elapsed_s": 0.85,
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["mode"], "ai")
        self.assertEqual(rep["summary"]["execution_outcome"], "Completed successfully")
        self.assertTrue(rep["summary"]["is_conclusive"])
        self.assertEqual(rep["optimization_strategy"]["selected_strategy"], "-O2")
        self.assertEqual(rep["optimization_strategy"]["effective_strategy"], "-O2")
        self.assertFalse(rep["optimization_strategy"]["fallback_occurred"])
        self.assertIn("High loop density", rep["optimization_strategy"]["decision_rationale"])
        self.assertEqual(rep["security_and_correctness"]["security_status"], "Passed")
        self.assertEqual(rep["security_and_correctness"]["correctness_status"], "Passed")
        self.assertEqual(rep["performance"]["benchmark_verdict"], "IMPROVED")
        self.assertEqual(rep["performance"]["speedup_ratio"], 1.25)
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")
        self.assertTrue(rep["overall_conclusion"]["performance_improved"])

    def test_03_compilation_failure(self):
        run_data = {
            "run_id": "run_fail_comp",
            "program_id": "broken",
            "mode": "ai",
            "status": "failed",
            "error": "clang: error: syntax error in input.c: unexpected identifier",
            "record": None,
            "view": None,
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["status"], "failed")
        self.assertIn("Compilation Failed", rep["summary"]["headline"])
        self.assertFalse(rep["summary"]["is_conclusive"])
        self.assertEqual(rep["security_and_correctness"]["compilation_status"], "Failed")
        self.assertIn("syntax error", rep["security_and_correctness"]["compilation_details"])
        self.assertEqual(rep["performance"]["benchmark_verdict"], "NOT_RUN")
        self.assertFalse(rep["overall_conclusion"]["compilation_succeeded"])
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "COMPILATION_FAILED")
        self.assertTrue(any("Compilation Error" in p["title"] for p in rep["problems_and_limitations"]))

    def test_04_security_blocked_operation(self):
        run_data = {
            "run_id": "run_sec_block",
            "program_id": "unsafe",
            "mode": "ai",
            "status": "blocked",
            "record": {
                "selected_strategy": "custom_unsafe_pass",
                "effective_strategy": None,
                "fallback_occurred": False,
                "security_gate": {
                    "overall_verdict": "BLOCKED",
                    "fallback_triggered": False,
                },
            },
            "error": "Security Gate rejected candidate optimization due to unsafe memory write.",
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["security_and_correctness"]["security_status"], "Blocked")
        self.assertEqual(rep["security_and_correctness"]["fallback_handling"], "Blocked")
        self.assertFalse(rep["overall_conclusion"]["security_passed"])
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "SECURITY_BLOCKED")
        self.assertTrue(any("Security Policy Blocked" in p["title"] for p in rep["problems_and_limitations"]))

    def test_05_security_fallback(self):
        run_data = {
            "run_id": "run_sec_fb",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "aggressive_unroll",
                "effective_strategy": "-O2",
                "fallback_occurred": True,
                "security_gate": {
                    "overall_verdict": "PASS",
                    "fallback_triggered": True,
                },
                "baseline_measurement": {"median_s": 0.020, "status": "OK", "timing_is_reliable": True},
                "optimized_measurement": {"median_s": 0.019, "status": "OK", "timing_is_reliable": True},
                "regression_overall_status": "PARITY",
            },
            "view": {
                "selected_strategy": "aggressive_unroll",
                "effective_strategy": "-O2",
                "fallback_occurred": True,
                "regression_overall_status": "PARITY",
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["optimization_strategy"]["selected_strategy"], "aggressive_unroll")
        self.assertEqual(rep["optimization_strategy"]["effective_strategy"], "-O2")
        self.assertTrue(rep["optimization_strategy"]["fallback_occurred"])
        self.assertTrue(rep["optimization_strategy"]["strategies_differ"])
        self.assertIn("Passed (via Fallback)", rep["security_and_correctness"]["security_status"])
        self.assertEqual(rep["security_and_correctness"]["fallback_handling"], "Triggered (Safe Baseline)")
        self.assertTrue(rep["overall_conclusion"]["security_passed"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "FALLBACK_APPLIED")
        self.assertTrue(any("Security Fallback Activated" in p["title"] for p in rep["problems_and_limitations"]))

    def test_06_correctness_verification_failure(self):
        run_data = {
            "run_id": "run_corr_fail",
            "program_id": "gemm",
            "mode": "ai",
            "status": "failed",
            "error": "Correctness verification failed: numerical drift exceeds tolerance 1e-4",
            "record": {
                "selected_strategy": "-O3",
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["security_and_correctness"]["correctness_status"], "Failed")
        self.assertFalse(rep["overall_conclusion"]["correctness_verified"])
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])

    def test_07_inconclusive_benchmark_unreliable_timing(self):
        run_data = {
            "run_id": "run_noisy",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3",
                "effective_strategy": "-O3",
                "fallback_occurred": False,
                "baseline_measurement": {"median_s": 0.020, "timing_is_reliable": False, "status": "OK"},
                "optimized_measurement": {"median_s": 0.015, "timing_is_reliable": False, "status": "OK"},
                "regression_overall_status": "INCONCLUSIVE",
            },
            "view": {
                "regression_overall_status": "INCONCLUSIVE",
                "baseline_timing": {"median_s": 0.020, "timing_is_reliable": False},
                "optimized_timing": {"median_s": 0.015, "timing_is_reliable": False},
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertFalse(rep["summary"]["is_conclusive"])
        self.assertIn("variability", rep["summary"]["conclusive_reason"].lower())
        self.assertEqual(rep["performance"]["benchmark_verdict"], "INCONCLUSIVE")
        self.assertFalse(rep["performance"]["timing_is_reliable"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "INCONCLUSIVE")
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertTrue(any("High Measurement Noise" in p["title"] for p in rep["problems_and_limitations"]))

    def test_08_confirmed_performance_regression(self):
        run_data = {
            "run_id": "run_regressed",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O1",
                "effective_strategy": "-O1",
                "baseline_measurement": {"median_s": 0.010, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.015, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "REGRESSED",
            },
            "view": {
                "regression_overall_status": "REGRESSED",
                "baseline_timing": {"median_s": 0.010},
                "optimized_timing": {"median_s": 0.015},
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertTrue(rep["summary"]["is_conclusive"])
        self.assertEqual(rep["performance"]["benchmark_verdict"], "REGRESSED")
        self.assertIn("slowdown", rep["performance"]["speedup_text"].lower())
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "REGRESSION")
        self.assertTrue(any("Performance Regression Detected" in p["title"] for p in rep["problems_and_limitations"]))

    def test_09_missing_performance_measurements(self):
        run_data = {
            "run_id": "run_no_bench",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "baseline_measurement": None,
                "optimized_measurement": None,
            },
            "view": {
                "baseline_timing": None,
                "optimized_timing": None,
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertFalse(rep["performance"]["available"])
        self.assertIsNone(rep["performance"]["speedup_ratio"])
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertEqual(rep["performance"]["provenance"], ReportProvenance.NOT_RECORDED.value)

    def test_10_missing_security_and_correctness_data(self):
        run_data = {
            "run_id": "run_sparse",
            "mode": "ai",
            "status": "completed",
            "record": {},
        }

        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["security_and_correctness"]["security_status"], "Not recorded")
        self.assertEqual(rep["security_and_correctness"]["correctness_status"], "Not recorded")
        self.assertEqual(rep["security_and_correctness"]["security_provenance"], ReportProvenance.NOT_RECORDED.value)
        self.assertFalse(rep["overall_conclusion"]["security_passed"])
        self.assertFalse(rep["overall_conclusion"]["correctness_verified"])

    def test_11_missing_optimization_rationale(self):
        run_data = {
            "run_id": "run_no_rat",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "decision_trace": None,
                "xai_result": None,
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertIn("detailed decision rationale was not recorded", rep["optimization_strategy"]["decision_rationale"])

    def test_12_malformed_and_none_run_data(self):
        rep = generate_workflow_report(None)
        self.assertEqual(rep["status"], "not_recorded")
        self.assertEqual(rep["summary"]["headline"], "Run Record Unavailable")
        self.assertFalse(rep["overall_conclusion"]["execution_succeeded"])

        rep_empty = generate_workflow_report({})
        self.assertEqual(rep_empty["status"], "unknown")

    def test_13_run_scoped_events_isolation(self):
        events = [
            {"run_id": "other_run_1", "stage": "benchmarking", "status": "failed", "payload": {"error": "WRONG_RUN"}},
            {"run_id": "target_run", "stage": "benchmarking", "status": "completed", "payload": {"status": "OK"}},
            {"run_id": "other_run_2", "stage": "security", "status": "blocked", "payload": {"verdict": "BLOCKED"}},
        ]
        run_data = {
            "run_id": "target_run",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "security_gate": {"overall_verdict": "PASS"},
                "optimized_measurement": {"status": "OK", "median_s": 0.01, "timing_is_reliable": True},
            },
        }

        rep = generate_workflow_report(run_data, events=events)
        # Should not pick up errors or blocks from other_run_1 or other_run_2
        self.assertEqual(rep["run_id"], "target_run")
        self.assertEqual(rep["security_and_correctness"]["security_status"], "Passed")
        self.assertNotIn("WRONG_RUN", str(rep["problems_and_limitations"]))

    def test_14_selection_does_not_claim_speedup_without_measurements(self):
        # Even if optimization selection succeeded and strategy was chosen,
        # performance_improved must be FALSE if measurements were not taken or unverified.
        run_data = {
            "run_id": "run_sel_only",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3",
                "effective_strategy": "-O3",
                "q_value_selected": 0.95,
                "baseline_measurement": None,
                "optimized_measurement": None,
            },
        }

        rep = generate_workflow_report(run_data)
        self.assertFalse(rep["overall_conclusion"]["performance_improved"])
        self.assertNotEqual(rep["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")

    def test_15_authoritative_benchmark_verdict_preserved(self):
        # Backend regression verdict must be strictly preserved
        for status_val in ("IMPROVED", "PARITY", "REGRESSED"):
            run_data = {
                "run_id": f"run_verd_{status_val}",
                "mode": "ai",
                "status": "completed",
                "record": {
                    "selected_strategy": "-O2",
                    "effective_strategy": "-O2",
                    "baseline_measurement": {"median_s": 0.02, "timing_is_reliable": True, "status": "OK"},
                    "optimized_measurement": {"median_s": 0.018, "timing_is_reliable": True, "status": "OK"},
                    "regression_overall_status": status_val,
                },
            }
            rep = generate_workflow_report(run_data)
            self.assertEqual(rep["performance"]["benchmark_verdict"], status_val)

    def test_16_genuinely_running_run_is_provisional_and_not_failed(self):
        """Condition 1: Running state must be marked provisional IN_PROGRESS, never EXECUTION_FAILED."""
        run_data = {
            "run_id": "run_live_01",
            "program_id": "gemm",
            "mode": "ai",
            "status": "running",
            "record": None,
            "view": None,
        }
        rep = generate_workflow_report(run_data)
        self.assertTrue(rep["is_provisional"])
        self.assertEqual(rep["status"], "running")
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "IN_PROGRESS")
        self.assertIn("In Progress (Provisional)", rep["summary"]["headline"])
        self.assertIn("provisional", rep["summary"]["execution_outcome"].lower())
        self.assertFalse(rep["summary"]["is_conclusive"])
        self.assertNotEqual(rep["overall_conclusion"]["verdict_badge"], "EXECUTION_FAILED")
        self.assertNotIn("Unknown error", rep["summary"]["plain_text"])
        self.assertIn("Workflow In Progress", rep["overall_conclusion"]["verdict_badge_explanation"])

    def test_17_failed_run_with_missing_error_details(self):
        """Condition 4: Failed run with missing error details produces FAILED_NO_DETAILS."""
        run_data = {
            "run_id": "run_fail_empty",
            "program_id": "gemm",
            "mode": "ai",
            "status": "failed",
            "error": None,
            "record": None,
            "view": None,
        }
        rep = generate_workflow_report(run_data)
        self.assertFalse(rep["is_provisional"])
        self.assertEqual(rep["status"], "failed")
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "FAILED_NO_DETAILS")
        self.assertIn("Failed (No Details)", rep["overall_conclusion"]["headline"])
        self.assertNotIn("Unknown error", rep["summary"]["plain_text"])
        self.assertIn("Execution Failed", rep["overall_conclusion"]["verdict_badge_explanation"])

    def test_18_completed_run_with_incomplete_profiling_not_failed(self):
        """Condition 5: Completed run with missing/partial profiling data must not fail."""
        run_data = {
            "run_id": "run_no_profile",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "ir_features": {},
                "program_profile": {},
                "baseline_measurement": {"median_s": 0.02, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.015, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "IMPROVED",
            },
            "view": {
                "regression_overall_status": "IMPROVED",
                "baseline_timing": {"median_s": 0.02},
                "optimized_timing": {"median_s": 0.015},
            },
        }
        rep = generate_workflow_report(run_data)
        self.assertFalse(rep["is_provisional"])
        self.assertEqual(rep["status"], "completed")
        self.assertFalse(rep["program_analysis"]["available"])
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")
        self.assertTrue(rep["overall_conclusion"]["execution_succeeded"])
        self.assertTrue(rep["overall_conclusion"]["compilation_succeeded"])

    def test_19_completed_run_without_benchmarks(self):
        """Completed run without benchmarks gets COMPLETED_WITHOUT_BENCHMARKS."""
        run_data = {
            "run_id": "run_no_bench",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "baseline_measurement": None,
                "optimized_measurement": None,
            },
        }
        rep = generate_workflow_report(run_data)
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "COMPLETED_WITHOUT_BENCHMARKS")
        self.assertIn("Benchmarks Not Recorded", rep["overall_conclusion"]["headline"])

    def test_20_service_refreshing_report_on_terminal_state(self):
        """Condition 8: Premature report caching does not block final completed report."""
        import web.service as svc
        test_run_id = "test_run_cache_refresh"
        svc._RUNS_STORE[test_run_id] = {
            "run_id": test_run_id,
            "program_id": "gemm",
            "mode": "ai",
            "status": "running",
            "record": None,
            "view": None,
        }

        # Query while running
        rep_running = svc.get_run_result(test_run_id)["report"]
        self.assertTrue(rep_running["is_provisional"])
        self.assertEqual(rep_running["overall_conclusion"]["verdict_badge"], "IN_PROGRESS")

        # Now simulate run completion
        svc._RUNS_STORE[test_run_id].update({
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "baseline_measurement": {"median_s": 0.025, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.020, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "IMPROVED",
            },
            "view": {
                "regression_overall_status": "IMPROVED",
                "baseline_timing": {"median_s": 0.025},
                "optimized_timing": {"median_s": 0.020},
            },
        })

        # Query after completion — MUST refresh and not return stale IN_PROGRESS or EXECUTION_FAILED!
        rep_completed = svc.get_run_result(test_run_id)["report"]
        self.assertFalse(rep_completed["is_provisional"])
        self.assertEqual(rep_completed["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")
        self.assertTrue(rep_completed["overall_conclusion"]["performance_improved"])

        # Cleanup
        svc._RUNS_STORE.pop(test_run_id, None)

    def test_21_cross_run_and_run_id_isolation(self):
        """Condition 7: Events and data from different runs are strictly isolated."""
        from web.events import EventEnvelope, EventType, PipelineStage
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        evt_a = EventEnvelope(
            schema_version="1.0",
            event_id="evt_run_a_0001",
            run_id="run_A",
            program_id="gemm",
            seq=1,
            timestamp=now,
            event_type=EventType.ERROR.value,
            stage=PipelineStage.SECURITY_VERIFICATION.value,
            status="failed",
            payload={"error": "Security failure in run A"},
        )
        evt_b = EventEnvelope(
            schema_version="1.0",
            event_id="evt_run_b_0001",
            run_id="run_B",
            program_id="gemm",
            seq=1,
            timestamp=now,
            event_type=EventType.STAGE_COMPLETED.value,
            stage=PipelineStage.SECURITY_VERIFICATION.value,
            status="completed",
            payload={"passed": True},
        )

        run_b_data = {
            "run_id": "run_B",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "security_gate": {"overall_verdict": "PASS"},
            },
        }

        # Provide both events to run B's report generation
        rep_b = generate_workflow_report(run_b_data, events=[evt_a, evt_b])
        self.assertEqual(rep_b["run_id"], "run_B")
        self.assertEqual(rep_b["security_and_correctness"]["security_status"], "Passed")
        self.assertNotIn("Security failure in run A", str(rep_b["problems_and_limitations"]))

    def test_22_slowdown_with_authoritative_verdict_and_time_comparison(self):
        """Condition 9: Explains 24.69 ms vs 31.21 ms without claiming regression unless authoritative."""
        # Scenario A: Backend comparator confirmed regression
        run_data_reg = {
            "run_id": "run_reg_6f39baf187b1",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "mem2reg, instcombine, simplifycfg, gvn, loop-unroll",
                "effective_strategy": "mem2reg, instcombine, simplifycfg, gvn, loop-unroll",
                "baseline_measurement": {"median_s": 0.02469, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.03121, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "REGRESSED",
            },
            "view": {
                "regression_overall_status": "REGRESSED",
                "baseline_timing": {"median_s": 0.02469},
                "optimized_timing": {"median_s": 0.03121},
            },
        }
        rep_reg = generate_workflow_report(run_data_reg)
        self.assertIn(rep_reg["overall_conclusion"]["verdict_badge"], ("REGRESSION", "REGRESSED"))
        self.assertIn("24.69 ms", rep_reg["performance"]["time_comparison_explanation"])
        self.assertIn("31.21 ms", rep_reg["performance"]["time_comparison_explanation"])
        self.assertIn("statistically verified performance regression", rep_reg["performance"]["time_comparison_explanation"])

        # Scenario B: Measured 31.21 ms vs 24.69 ms but measurement variance was high (INCONCLUSIVE)
        run_data_noisy = {
            "run_id": "run_noisy_perf",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "baseline_measurement": {"median_s": 0.02469, "timing_is_reliable": False, "status": "OK"},
                "optimized_measurement": {"median_s": 0.03121, "timing_is_reliable": False, "status": "OK"},
                "regression_overall_status": "INCONCLUSIVE",
            },
            "view": {
                "regression_overall_status": "INCONCLUSIVE",
                "baseline_timing": {"median_s": 0.02469},
                "optimized_timing": {"median_s": 0.03121},
            },
        }
        rep_noisy = generate_workflow_report(run_data_noisy)
        self.assertEqual(rep_noisy["overall_conclusion"]["verdict_badge"], "INCONCLUSIVE")
        self.assertIn("measurement noise", rep_noisy["performance"]["time_comparison_explanation"].lower())
        self.assertFalse(rep_noisy["summary"]["is_conclusive"])

    def test_23_verdict_badge_explanations_comprehensive(self):
        """Condition 10: Clear plain-English explanations for all technical statuses."""
        from web.report import VERDICT_BADGE_EXPLANATIONS
        required_badges = [
            "EXECUTION_FAILED",
            "BASELINE_READY",
            "SPEEDUP_VERIFIED",
            "PARITY",
            "REGRESSED",
            "INCONCLUSIVE",
            "FALLBACK_APPLIED",
            "SECURITY_BLOCKED",
            "COMPILATION_FAILED",
            "FAILED_NO_DETAILS",
            "IN_PROGRESS",
            "COMPLETED_WITHOUT_BENCHMARKS",
            "COMPLETED",
            "UNAVAILABLE",
        ]
        for badge in required_badges:
            self.assertIn(badge, VERDICT_BADGE_EXPLANATIONS)
            self.assertGreater(len(VERDICT_BADGE_EXPLANATIONS[badge]), 15)

    def test_24_workflow_narrative_successful_ai_run(self):
        """Feature 1: Chronological narrative generation for successful AI run."""
        run_data = {
            "run_id": "run_narrative_ai_01",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3 -funroll-loops",
                "effective_strategy": "-O3 -funroll-loops",
                "ir_features": {"total_instructions": 1200, "vectorizable_loops": 3, "load_instructions": 250, "store_instructions": 100},
                "program_profile": {"label": "compute_heavy", "dominant_feature": "loop_computation"},
                "security_gate": {"overall_verdict": "PASS", "pointer_safety": "verified"},
                "baseline_measurement": {"median_s": 0.030, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.020, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "IMPROVED",
            },
            "view": {
                "regression_overall_status": "IMPROVED",
                "baseline_timing": {"median_s": 0.030},
                "optimized_timing": {"median_s": 0.020},
                "speedup_ratio": 1.5,
            },
        }
        rep = generate_workflow_report(run_data)
        self.assertIn("workflow_narrative", rep)
        narrative = rep["workflow_narrative"]
        self.assertEqual(len(narrative["steps"]), 7)

        # Check Step 1: Program Analysis
        s1 = narrative["steps"][0]
        self.assertEqual(s1["step_number"], 1)
        self.assertEqual(s1["status"], "completed")
        self.assertIn("1,200", s1["simple_explanation"])
        self.assertIn("1200", s1["technical_explanation"])

        # Check Step 2: Strategy Selection
        s2 = narrative["steps"][1]
        self.assertEqual(s2["step_number"], 2)
        self.assertEqual(s2["status"], "completed")
        self.assertIn("-O3 -funroll-loops", s2["simple_explanation"])

        # Check Step 4: Security Verification
        s4 = narrative["steps"][3]
        self.assertEqual(s4["step_number"], 4)
        self.assertEqual(s4["status"], "completed")
        self.assertEqual(s4["badge"], "PASSED")

        # Check Step 6: Benchmarking
        s6 = narrative["steps"][5]
        self.assertEqual(s6["step_number"], 6)
        self.assertEqual(s6["status"], "completed")
        self.assertIn("30.00 ms", s6["simple_explanation"])
        self.assertIn("20.00 ms", s6["simple_explanation"])

        # Check Step 7: Final Outcome
        s7 = narrative["steps"][6]
        self.assertEqual(s7["step_number"], 7)
        self.assertEqual(s7["status"], "completed")
        self.assertEqual(s7["badge"], "SPEEDUP_VERIFIED")

    def test_25_workflow_narrative_baseline_run(self):
        """Feature 1: Chronological narrative generation for baseline run (steps 3 & 4 skipped)."""
        run_data = {
            "run_id": "run_narrative_baseline_01",
            "program_id": "gemm",
            "mode": "normal",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3",
                "effective_strategy": "-O3",
                "baseline_measurement": {"median_s": 0.025, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.025, "timing_is_reliable": True, "status": "OK"},
            },
        }
        rep = generate_workflow_report(run_data)
        narrative = rep["workflow_narrative"]
        self.assertEqual(len(narrative["steps"]), 7)

        # Step 3: Reviewer must be skipped in baseline mode
        s3 = narrative["steps"][2]
        self.assertEqual(s3["status"], "skipped")
        self.assertEqual(s3["badge"], "SKIPPED")
        self.assertIn("Multi-agent peer review is omitted", s3["simple_explanation"])

        # Step 4: Security Gate must be skipped in baseline mode
        s4 = narrative["steps"][3]
        self.assertEqual(s4["status"], "skipped")
        self.assertEqual(s4["badge"], "SKIPPED")
        self.assertIn("intentionally skipped", s4["simple_explanation"])

    def test_26_workflow_narrative_incomplete_or_missing_data(self):
        """Feature 1: Narrative generation with incomplete or missing record fields."""
        run_data = {
            "run_id": "run_narrative_sparse",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {},
            "view": {},
        }
        rep = generate_workflow_report(run_data)
        narrative = rep["workflow_narrative"]
        self.assertEqual(len(narrative["steps"]), 7)
        for step in narrative["steps"]:
            self.assertIsInstance(step["simple_explanation"], str)
            self.assertIsInstance(step["technical_explanation"], str)
            self.assertIsInstance(step["evidence"], list)
            self.assertIsInstance(step["technical_details"], dict)

    def test_27_workflow_narrative_reviewer_rejection_and_revision(self):
        """Feature 1: Reviewer rejection and revision cycles reflected in Step 3."""
        run_data = {
            "run_id": "run_narrative_rev",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O2",
                "effective_strategy": "-O2",
                "reviewer_verdict": "REJECT",
                "reviewer_feedback": "Excessive code expansion alert",
                "revision_count": 2,
            },
        }
        rep = generate_workflow_report(run_data)
        s3 = rep["workflow_narrative"]["steps"][2]
        self.assertIn("rejected", s3["simple_explanation"].lower())
        self.assertIn("Excessive code expansion alert", s3["simple_explanation"])
        self.assertIn("2 revisions", s3["simple_explanation"])

    def test_28_workflow_narrative_compilation_and_correctness_failure(self):
        """Feature 1: Step 5 marks failure accurately for compilation or verification failure."""
        run_data = {
            "run_id": "run_narrative_fail",
            "program_id": "gemm",
            "mode": "ai",
            "status": "failed",
            "record": {
                "compilation_success": False,
                "compilation_error": "Syntax error in LLVM IR",
                "correctness_verified": False,
            },
        }
        rep = generate_workflow_report(run_data)
        s5 = rep["workflow_narrative"]["steps"][4]
        self.assertEqual(s5["status"], "failed")
        self.assertEqual(s5["badge"], "COMPILATION_FAILED")
        self.assertIn("failed", s5["simple_explanation"].lower())

    def test_29_workflow_narrative_provisional_running_state(self):
        """Feature 1: Provisional running state generates in-progress narrative steps."""
        run_data = {
            "run_id": "run_narrative_prog",
            "program_id": "gemm",
            "mode": "ai",
            "status": "running",
            "record": None,
        }
        rep = generate_workflow_report(run_data)
        narrative = rep["workflow_narrative"]
        self.assertTrue(narrative["is_provisional"])
        s7 = narrative["steps"][6]
        self.assertEqual(s7["status"], "running")
        self.assertEqual(s7["badge"], "IN_PROGRESS")
        self.assertIn("underway", s7["simple_explanation"].lower())

    def test_30_explain_agent_message_all_types(self):
        """Feature 2: Deterministic explanations for all supported message types and fallbacks."""
        from web.report import explain_agent_message

        # 1. IR_FEATURES
        m1 = {"sender": "Analyst", "message_type": "IR_FEATURES", "payload": {"ir_features": {"total_instructions": 500, "vectorizable_loops": 2, "load_instructions": 100, "store_instructions": 50}}}
        exp1 = explain_agent_message(m1)
        self.assertEqual(exp1["category"], "observation")
        self.assertIn("counted 500 instructions", exp1["simple_explanation"] if "simple_explanation" in exp1 else exp1["simple_text"])

        # 2. PROFILE
        m2 = {"sender": "Analyst", "message_type": "PROFILE", "payload": {"profile": {"label": "memory_bound", "dominant_feature": "loads"}}}
        exp2 = explain_agent_message(m2)
        self.assertEqual(exp2["category"], "observation")
        self.assertIn("memory_bound", exp2["simple_text"])

        # 3. STRATEGY_PROPOSAL
        m3 = {"sender": "Strategist", "message_type": "STRATEGY_PROPOSAL", "payload": {"strategy": "-O3 -fno-inline"}}
        exp3 = explain_agent_message(m3)
        self.assertEqual(exp3["category"], "proposal")
        self.assertIn("-O3 -fno-inline", exp3["simple_text"])

        # 4. REVIEW_ACCEPT
        m4 = {"sender": "Reviewer", "message_type": "REVIEW_ACCEPT", "payload": {"strategy": "-O3"}}
        exp4 = explain_agent_message(m4)
        self.assertEqual(exp4["category"], "review")
        self.assertIn("approved", exp4["simple_text"].lower())

        # 5. REVIEW_REJECT
        m5 = {"sender": "Reviewer", "message_type": "REVIEW_REJECT", "payload": {"strategy": "-O3", "feedback": "Loop count violation", "revision_number": 1}}
        exp5 = explain_agent_message(m5)
        self.assertEqual(exp5["category"], "review")
        self.assertIn("rejected", exp5["simple_text"].lower())
        self.assertIn("Loop count violation", exp5["simple_text"])

        # 6. STRATEGY_REVISED
        m6 = {"sender": "Strategist", "message_type": "STRATEGY_REVISED", "payload": {"strategy": "-O2", "revising_strategy": "-O3", "revision_number": 1}}
        exp6 = explain_agent_message(m6)
        self.assertEqual(exp6["category"], "proposal")
        self.assertIn("-O2", exp6["simple_text"])
        self.assertIn("-O3", exp6["simple_text"])

        # 7. FINAL_DECISION (normal & fallback)
        m7_pass = {"sender": "SecurityGate", "message_type": "FINAL_DECISION", "payload": {"effective_strategy": "-O3", "fallback_occurred": False, "security_gate_result": {"overall_verdict": "PASS"}}}
        exp7_pass = explain_agent_message(m7_pass)
        self.assertEqual(exp7_pass["category"], "security")
        self.assertIn("authorizing '-O3'", exp7_pass["simple_text"])

        m7_fb = {"sender": "SecurityGate", "message_type": "FINAL_DECISION", "payload": {"effective_strategy": "baseline", "fallback_occurred": True}}
        exp7_fb = explain_agent_message(m7_fb)
        self.assertEqual(exp7_fb["category"], "security")
        self.assertIn("substituted verified baseline", exp7_fb["simple_text"])

        # 8. BENCHMARK_RESULT
        m8 = {"sender": "Benchmark", "message_type": "BENCHMARK_RESULT", "payload": {"status": "OK", "timing": {"median_s": 0.0245}}}
        exp8 = explain_agent_message(m8)
        self.assertEqual(exp8["category"], "benchmark")
        self.assertIn("24.5 ms", exp8["simple_text"])

        # 9. CODE_ANALYSIS
        m9 = {"sender": "Analyst", "message_type": "CODE_ANALYSIS", "payload": {"analysis": "Analyzed standard gemm kernel."}}
        exp9 = explain_agent_message(m9)
        self.assertEqual(exp9["category"], "observation")
        self.assertIn("Analyzed standard gemm kernel.", exp9["simple_text"])

        # 10. ERROR
        m10 = {"sender": "Runner", "message_type": "ERROR", "payload": {"stage": "compilation", "error": "Internal compiler crash"}}
        exp10 = explain_agent_message(m10)
        self.assertEqual(exp10["category"], "error")
        self.assertIn("Internal compiler crash", exp10["simple_text"])

        # 11. Unknown / Fallback
        m11 = {"sender": "UnknownAgent", "message_type": "CUSTOM_TYPE", "payload": {"foo": "bar"}}
        exp11 = explain_agent_message(m11)
        self.assertEqual(exp11["category"], "coordination")
        self.assertIn("CUSTOM_TYPE", exp11["simple_text"])

    def test_31_toggle_neutrality_and_dual_views(self):
        """Feature 3: Narrative steps contain both Simple English and Technical explanations simultaneously."""
        run_data = {
            "run_id": "run_neutral_01",
            "program_id": "gemm",
            "mode": "ai",
            "status": "completed",
            "record": {
                "selected_strategy": "-O3",
                "effective_strategy": "-O3",
                "baseline_measurement": {"median_s": 0.025, "timing_is_reliable": True, "status": "OK"},
                "optimized_measurement": {"median_s": 0.020, "timing_is_reliable": True, "status": "OK"},
                "regression_overall_status": "IMPROVED",
            },
            "view": {
                "regression_overall_status": "IMPROVED",
                "baseline_timing": {"median_s": 0.025},
                "optimized_timing": {"median_s": 0.020},
            },
        }
        rep = generate_workflow_report(run_data)
        narrative = rep["workflow_narrative"]
        for step in narrative["steps"]:
            # Both views must be pre-rendered deterministically
            self.assertTrue(len(step["simple_explanation"]) > 0)
            self.assertTrue(len(step["technical_explanation"]) > 0)
            # The backend report structure is completely independent of client view mode
            self.assertIn("evidence", step)
            self.assertIn("technical_details", step)

        # Verdict and outcome are not modified by explanation text
        self.assertEqual(rep["overall_conclusion"]["verdict_badge"], "SPEEDUP_VERIFIED")
        self.assertTrue(rep["overall_conclusion"]["performance_improved"])


if __name__ == "__main__":
    unittest.main()
