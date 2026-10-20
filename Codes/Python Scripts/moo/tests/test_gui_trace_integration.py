"""
moo/tests/test_gui_trace_integration.py — GUI Decision Trace Integration Tests.

Validates that CompilerGUI in gui_app.py correctly handles dictionary-based,
object-based, and missing-field decision traces without throwing AttributeError,
preserves the exact MOO display logic, isolates optional MOO exceptions,
and updates Dashboard, Optimization, Benchmark, Security, and Reports views.
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure Python Scripts directory is on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(_HERE))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import ttkbootstrap as ttk
from gui_app import CompilerGUI
from moo.decision_trace import (
    DecisionTrace,
    SELECTION_METHOD_MOO_AWARE,
    SELECTION_METHOD_ARGMAX_NO_FRONTIER,
)
from moo.runrecord.builder import RunRecordBuilder
from moo.runrecord.projections import to_gui_view, security_display_text


class TestGUITraceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a hidden Tk root for GUI tests
        cls.root = ttk.Window()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.gui = CompilerGUI(self.root)
        self.gui.strategy = "-O2"
        self.gui.results = {
            "o3": {"time": 0.012345, "size": 10240, "security": "Baseline (-O3)"},
            "ai": {"time": 0.009876, "size": 9120, "security": "[OK] Preserved"},
        }

    def test_get_trace_field_accessor(self):
        """Test _get_trace_field helper on dict, object, None, and unknown types."""
        # Dict
        d = {"ai_top_choice": "instcombine", "moo_active": True}
        self.assertEqual(CompilerGUI._get_trace_field(d, "ai_top_choice"), "instcombine")
        self.assertEqual(CompilerGUI._get_trace_field(d, "moo_active"), True)
        self.assertEqual(CompilerGUI._get_trace_field(d, "missing", "default"), "default")

        # Object
        class DummyObj:
            ai_top_choice = "-O2"
            moo_active = False

        obj = DummyObj()
        self.assertEqual(CompilerGUI._get_trace_field(obj, "ai_top_choice"), "-O2")
        self.assertEqual(CompilerGUI._get_trace_field(obj, "moo_active"), False)
        self.assertEqual(CompilerGUI._get_trace_field(obj, "missing", 42), 42)

        # None
        self.assertIsNone(CompilerGUI._get_trace_field(None, "ai_top_choice"))
        self.assertEqual(CompilerGUI._get_trace_field(None, "ai_top_choice", "fallback"), "fallback")

        # Primitive
        self.assertEqual(CompilerGUI._get_trace_field(12345, "ai_top_choice", "def"), "def")

    def test_dict_trace_pareto_optimal(self):
        """Dict trace: MOO active and AI choice Pareto-optimal."""
        self.gui.last_trace = {
            "ai_choice_was_pareto_optimal": True,
            "moo_active": True,
            "ai_top_choice": "-O2",
            "selection_method": "moo_aware",
        }
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        opt_text = self.gui.optlabel.cget("text")

        self.assertIn("[MOO: AI choice was Pareto-optimal]", strat_text)
        self.assertIn("[moo_aware]", opt_text)

    def test_dict_trace_not_pareto_optimal(self):
        """Dict trace: AI choice was not Pareto-optimal."""
        self.gui.last_trace = {
            "ai_choice_was_pareto_optimal": False,
            "moo_active": True,
            "ai_top_choice": "instcombine,loop-unroll",
            "selection_method": "moo_aware",
        }
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        opt_text = self.gui.optlabel.cget("text")

        self.assertIn("[MOO: AI preferred 'instcombine,loop-unroll' — not Pareto-optimal]", strat_text)
        self.assertIn("[moo_aware]", opt_text)

    def test_dict_trace_moo_inactive(self):
        """Dict trace: MOO inactive, pure AI selection."""
        self.gui.last_trace = {
            "ai_choice_was_pareto_optimal": None,
            "moo_active": False,
            "ai_top_choice": "-O3",
            "selection_method": "argmax_fallback_no_frontier",
        }
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        opt_text = self.gui.optlabel.cget("text")

        self.assertIn("[No MOO data — pure AI selection]", strat_text)
        self.assertIn("[argmax_fallback_no_frontier]", opt_text)

    def test_dict_trace_missing_fields_no_invented_conclusion(self):
        """Dict trace with missing fields must not invent a conclusion."""
        self.gui.last_trace = {}
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        opt_text = self.gui.optlabel.cget("text")

        # Must not contain any invented MOO conclusion
        self.assertNotIn("Pareto-optimal", strat_text)
        self.assertNotIn("No MOO data", strat_text)
        self.assertEqual(strat_text, "-O2")
        self.assertEqual(opt_text, "-O2")

    def test_none_trace_handled_cleanly(self):
        """None trace must display default strategy without errors."""
        self.gui.last_trace = None
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        opt_text = self.gui.optlabel.cget("text")

        self.assertEqual(strat_text, "-O2")
        self.assertEqual(opt_text, "-O2")

    def test_object_trace_dataclass_support(self):
        """DecisionTrace dataclass object is supported seamlessly."""
        trace = DecisionTrace(
            ai_top_choice="instcombine",
            ai_top_q=0.85,
            q_rank_full=[("instcombine", 0.85), ("-O2", 0.75)],
            pareto_frontier=["-O2"],
            pareto_dominated=["instcombine"],
            pareto_invalid=[],
            objectives_used=["execution_time", "code_size"],
            moo_active=True,
            ai_choice_was_pareto_optimal=False,
            candidates_considered=["-O2"],
            filtered_out=["instcombine"],
            final_strategy="-O2",
            selection_reason="Highest Q-value on Pareto frontier",
            selection_method=SELECTION_METHOD_MOO_AWARE,
            objective_snapshot=[],
        )
        self.gui.last_trace = trace
        self.gui.refresh()

        strat_text = self.gui.strategy_text.cget("text")
        self.assertIn("[MOO: AI preferred 'instcombine' — not Pareto-optimal]", strat_text)
        self.assertIn("[moo_aware]", self.gui.optlabel.cget("text"))

    def test_moo_display_exception_isolation(self):
        """An exception in MOO property extraction must not crash refresh() or halt UI updates."""
        class BrokenTrace:
            @property
            def ai_choice_was_pareto_optimal(self):
                raise RuntimeError("Simulated broken trace accessor")

        self.gui.last_trace = BrokenTrace()
        # Must complete without raising RuntimeError or AttributeError
        self.gui.refresh()

        # Strategy text still gets default strategy label
        self.assertEqual(self.gui.strategy_text.cget("text"), "-O2")
        # Optimization table still populated
        items = self.gui.table.get_children()
        self.assertEqual(len(items), 3)

    def test_all_gui_views_update(self):
        """Verify Dashboard, Optimization, Benchmark, and Reports views update properly."""
        self.gui.last_trace = {
            "ai_choice_was_pareto_optimal": True,
            "moo_active": True,
            "ai_top_choice": "-O2",
            "selection_method": "moo_aware",
        }
        self.gui.refresh()

        # 1. Dashboard View
        self.assertEqual(self.gui.dtime.cget("text"), "0.009876 s")
        self.assertEqual(self.gui.dsize.cget("text"), "9,120 B")
        self.assertEqual(self.gui.dsec.cget("text"), "[OK] Preserved")
        self.assertEqual(self.gui.dstrategy.cget("text"), "AI Selected")
        self.assertIn("[MOO: AI choice was Pareto-optimal]", self.gui.strategy_text.cget("text"))

        # Dashboard comparison rows
        row_time = [w.cget("text") for w in self.gui.rows["time"]]
        self.assertEqual(row_time[0], "0.012345 s")
        self.assertEqual(row_time[1], "0.009876 s")
        self.assertTrue(row_time[2].startswith("↓"))  # improvement

        # 2. Optimization View
        self.assertEqual(self.gui.optlabel.cget("text"), "-O2  [moo_aware]")
        table_rows = [self.gui.table.item(item)["values"] for item in self.gui.table.get_children()]
        self.assertEqual(len(table_rows), 3)
        self.assertEqual(table_rows[0][0], "Execution Time")
        self.assertEqual(table_rows[1][0], "Code Size")
        self.assertEqual(table_rows[2][0], "Security")

        # 3. Benchmark View
        self.assertEqual(self.gui.btime1.cget("text"), "0.012345 s")
        self.assertEqual(self.gui.btime2.cget("text"), "0.009876 s")
        self.assertEqual(self.gui.bsize1.cget("text"), "10,240 B")
        self.assertEqual(self.gui.bsize2.cget("text"), "9,120 B")

        # 4. Security View
        self.assertEqual(self.gui.sec1.cget("text"), "Baseline (-O3)")
        self.assertEqual(self.gui.sec2.cget("text"), "[OK] Preserved")

        # 5. Reports View
        report_content = self.gui.report.get("1.0", "end")
        self.assertIn("TOACD COMPILER OPTIMIZATION EXPERIMENT", report_content)
        self.assertIn("AI Strategy: -O2", report_content)
        self.assertIn("0.012345 s", report_content)
        self.assertIn("0.009876 s", report_content)
        self.assertIn("[OK] Preserved", report_content)

    def test_pipeline_runrecord_dict_trace_integration(self):
        """Simulate a pipeline run with RunRecord containing dict decision_trace and verify full refresh."""
        trace = DecisionTrace(
            ai_top_choice="instcombine",
            ai_top_q=0.9,
            q_rank_full=[("instcombine", 0.9), ("-O2", 0.8)],
            pareto_frontier=["-O2"],
            pareto_dominated=["instcombine"],
            pareto_invalid=[],
            objectives_used=["execution_time"],
            moo_active=True,
            ai_choice_was_pareto_optimal=False,
            candidates_considered=["-O2"],
            filtered_out=["instcombine"],
            final_strategy="-O2",
            selection_reason="Highest Q on Pareto frontier",
            selection_method=SELECTION_METHOD_MOO_AWARE,
            objective_snapshot=[],
        )
        builder = RunRecordBuilder(source_path="sample.c", run_id="run_sample_01")
        builder.set_selection(selected_strategy="-O2", decision_trace=trace)
        builder.set_effective_strategy("-O2", fallback_occurred=False)
        builder.set_baseline_measurement({
            "timing": {"median_s": 0.015, "n_samples": 3},
            "code_size": {"primary_value": 12000},
        })
        builder.set_optimized_measurement("-O2", {
            "timing": {"median_s": 0.011, "n_samples": 3},
            "code_size": {"primary_value": 10500},
        })
        record = builder.build()

        # Verify runtime structure: record.decision_trace is indeed a dictionary!
        self.assertIsInstance(record.decision_trace, dict)
        self.assertEqual(record.decision_trace["ai_choice_was_pareto_optimal"], False)

        # Replicate GUI ingestion logic from _run_thread
        view = to_gui_view(record)
        selected = view.get("selected_strategy") or "—"
        effective = view.get("effective_strategy") or selected
        self.gui.strategy = effective
        self.gui.last_trace = record.decision_trace

        base_timing = view.get("baseline_timing")
        if base_timing and base_timing.get("median_s") is not None:
            self.gui.results["o3"]["time"] = base_timing["median_s"]
            self.gui.results["o3"]["size"] = base_timing.get("code_size_bytes")
            self.gui.results["o3"]["security"] = "Baseline (-O0)"

        opt_timing = view.get("optimized_timing")
        t = opt_timing.get("median_s") if opt_timing else None
        size = opt_timing.get("code_size_bytes") if opt_timing else None
        sec = security_display_text(view)
        self.gui.results["ai"] = {"time": t, "size": size, "security": sec}

        # Trigger refresh()
        self.gui.refresh()

        # Verify all views updated without exception
        self.assertEqual(self.gui.strategy, "-O2")
        self.assertIn("[MOO: AI preferred 'instcombine' — not Pareto-optimal]", self.gui.strategy_text.cget("text"))
        self.assertEqual(self.gui.dtime.cget("text"), "0.011000 s")
        self.assertEqual(self.gui.dsize.cget("text"), "10,500 B")
        self.assertEqual(self.gui.btime1.cget("text"), "0.015000 s")
        self.assertEqual(self.gui.btime2.cget("text"), "0.011000 s")
        self.assertEqual(self.gui.bsize1.cget("text"), "12,000 B")
        self.assertEqual(self.gui.bsize2.cget("text"), "10,500 B")

        # Optimization table has 3 rows
        self.assertEqual(len(self.gui.table.get_children()), 3)

        # Reports text updated
        report_text = self.gui.report.get("1.0", "end")
        self.assertIn("0.015000 s", report_text)
        self.assertIn("0.011000 s", report_text)


if __name__ == "__main__":
    unittest.main()
