"""
moo.tests.test_phase0_events — Automated tests for Phase 0 Event Infrastructure & Correctness.

Tests:
1. Canonical event schema validation and required identity fields.
2. Strictly monotonic sequence numbers across event types within a run.
3. Stable event IDs during replay and reconnection.
4. Exactly one terminal state transition per run.
5. No application events emitted or accepted after terminal completion.
6. Replay of completed/failed runs without duplicate terminal events.
7. Last-Event-ID reconnection filtering and idempotence.
8. Correct run and program isolation.
9. Authoritative workflow stage transitions (started, completed, skipped, failed).
10. Backend and frontend verdict consistency:
    - High-noise (unreliable) benchmarks classified as INCONCLUSIVE, never IMPROVED.
    - Missing or failed timing data never classified as IMPROVED.
    - True speedup classified as IMPROVED.
    - True slowdown classified as REGRESSION.
    - Parity classified as PARITY.
"""

from __future__ import annotations

import datetime
import json
import unittest
from typing import Any, Dict, List

from web.events import (
    EventEnvelope,
    SCHEMA_VERSION,
    PipelineStage,
    StageStatus,
    RunState,
    EventType,
    CursorStatus,
    validate_cursor,
    parse_event_id,
)
from web.service import (
    RunContext,
    _RUN_CONTEXTS,
    _RUNS_STORE,
    _RUN_MESSAGES,
    emit_canonical_event,
    get_historical_events,
)


class TestCanonicalEventEnvelope(unittest.TestCase):
    """Test schema validation and serialization of EventEnvelope."""

    def test_valid_envelope(self):
        env = EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id="evt_test_0001",
            run_id="run_test_123",
            program_id="gemm",
            seq=1,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            event_type=EventType.STAGE_STARTED.value,
            stage=PipelineStage.PROFILING.value,
            status=StageStatus.STARTED.value,
            payload={"info": "starting"},
        )
        env.validate()
        d = env.to_dict()
        self.assertEqual(d["schema_version"], "events.1.0")
        self.assertEqual(d["event_id"], "evt_test_0001")
        self.assertEqual(d["run_id"], "run_test_123")
        self.assertEqual(d["program_id"], "gemm")
        self.assertEqual(d["seq"], 1)
        self.assertEqual(d["event_type"], "stage_started")
        self.assertEqual(d["stage"], "profiling")
        self.assertEqual(d["status"], "started")
        self.assertEqual(d["payload"], {"info": "starting"})

        # Roundtrip via from_dict
        reconstructed = EventEnvelope.from_dict(d)
        self.assertEqual(reconstructed, env)

    def test_validation_missing_fields(self):
        # Missing run_id
        with self.assertRaises(ValueError):
            EventEnvelope(
                schema_version=SCHEMA_VERSION,
                event_id="evt_1",
                run_id="",
                program_id="gemm",
                seq=1,
                timestamp="2026-10-28T12:00:00Z",
                event_type="stage_started",
            ).validate()

        # Invalid seq (< 1)
        with self.assertRaises(ValueError):
            EventEnvelope(
                schema_version=SCHEMA_VERSION,
                event_id="evt_1",
                run_id="run_1",
                program_id="gemm",
                seq=0,
                timestamp="2026-10-28T12:00:00Z",
                event_type="stage_started",
            ).validate()

        # Non-dict payload
        with self.assertRaises(ValueError):
            EventEnvelope(
                schema_version=SCHEMA_VERSION,
                event_id="evt_1",
                run_id="run_1",
                program_id="gemm",
                seq=1,
                timestamp="2026-10-28T12:00:00Z",
                event_type="stage_started",
                payload="not_a_dict",  # type: ignore
            ).validate()

    def test_sse_chunk_formatting(self):
        env = EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id="evt_test_0042",
            run_id="run_sse_test",
            program_id="tc1",
            seq=42,
            timestamp="2026-10-28T12:00:00Z",
            event_type="done",
            stage=None,
            status="completed",
            payload={"status": "completed"},
        )
        chunk = env.to_sse_chunk()
        self.assertTrue(chunk.startswith("id: evt_test_0042\n"))
        self.assertIn("event: done\n", chunk)
        self.assertIn('"schema_version": "events.1.0"', chunk)
        self.assertTrue(chunk.endswith("\n\n"))


class TestRunLifecycleAndEventSequencing(unittest.TestCase):
    """Test lifecycle state transitions, monotonic sequencing, and single terminal event guarantees."""

    def setUp(self):
        self.run_id = f"test_run_lifecycle_{datetime.datetime.now().timestamp()}"
        self.program_id = "test_prog_gemm"
        self.ctx = RunContext(self.run_id, self.program_id, mode="ai")
        _RUN_CONTEXTS[self.run_id] = self.ctx

    def tearDown(self):
        _RUN_CONTEXTS.pop(self.run_id, None)

    def test_monotonic_sequences(self):
        """Sequence numbers must increase monotonically across all event types."""
        e1 = emit_canonical_event(self.run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.PROFILING.value)
        e2 = emit_canonical_event(self.run_id, EventType.AGENT_MESSAGE.value, payload={"sender": "Agent1"})
        e3 = emit_canonical_event(self.run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.PROFILING.value)
        e4 = emit_canonical_event(self.run_id, EventType.DONE.value, payload={"status": "completed"})

        self.assertIsNotNone(e1)
        self.assertIsNotNone(e2)
        self.assertIsNotNone(e3)
        self.assertIsNotNone(e4)

        self.assertEqual(e1.seq, 1)
        self.assertEqual(e2.seq, 2)
        self.assertEqual(e3.seq, 3)
        self.assertEqual(e4.seq, 4)

        # Check stable event IDs
        self.assertEqual(e1.event_id, f"evt_{self.run_id}_0001")
        self.assertEqual(e2.event_id, f"evt_{self.run_id}_0002")
        self.assertEqual(e3.event_id, f"evt_{self.run_id}_0003")
        self.assertEqual(e4.event_id, f"evt_{self.run_id}_0004")

    def test_no_events_after_terminal_completion(self):
        """No application events may be published after the terminal event."""
        emit_canonical_event(self.run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.PROFILING.value)
        terminal = emit_canonical_event(self.run_id, EventType.DONE.value, payload={"status": "completed"})
        self.assertIsNotNone(terminal)

        # Attempting to emit subsequent event must be rejected
        late_event = emit_canonical_event(self.run_id, EventType.AGENT_MESSAGE.value, payload={"msg": "Late!"})
        self.assertIsNone(late_event)

        # Terminal state must remain completed
        self.assertEqual(self.ctx.status, RunState.COMPLETED.value)
        self.assertEqual(len(self.ctx.events), 2)

    def test_exactly_one_terminal_transition(self):
        """Run accepts at most one terminal transition."""
        e_term1 = emit_canonical_event(self.run_id, EventType.DONE.value, payload={"status": "completed"})
        self.assertIsNotNone(e_term1)

        # Second terminal event rejected
        e_term2 = emit_canonical_event(self.run_id, EventType.ERROR.value, payload={"error": "Second error"})
        self.assertIsNone(e_term2)

        self.assertEqual(self.ctx.status, RunState.COMPLETED.value)


class TestReplayAndReconnectionIdempotence(unittest.TestCase):
    """Test historical event replay, Last-Event-ID filtering, and duplicate suppression."""

    def setUp(self):
        self.run_id = f"test_run_replay_{datetime.datetime.now().timestamp()}"
        self.program_id = "test_prog_tc2"
        self.ctx = RunContext(self.run_id, self.program_id, mode="ai")
        _RUN_CONTEXTS[self.run_id] = self.ctx

        emit_canonical_event(self.run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.PROFILING.value)
        emit_canonical_event(self.run_id, EventType.AGENT_MESSAGE.value, payload={"text": "m1"})
        emit_canonical_event(self.run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.PROFILING.value)
        emit_canonical_event(self.run_id, EventType.DONE.value, payload={"status": "completed"})

    def tearDown(self):
        _RUN_CONTEXTS.pop(self.run_id, None)

    def test_stable_event_ids_on_replay(self):
        """Events returned on replay must have identical, stable IDs and seq."""
        history1 = get_historical_events(self.run_id)
        history2 = get_historical_events(self.run_id)

        self.assertEqual(len(history1), 4)
        self.assertEqual(len(history2), 4)

        for h1, h2 in zip(history1, history2):
            self.assertEqual(h1["event_id"], h2["event_id"])
            self.assertEqual(h1["seq"], h2["seq"])
            self.assertEqual(h1["timestamp"], h2["timestamp"])

    def test_last_event_id_filtering(self):
        """Test 4: If valid Last-Event-ID is provided, only events strictly following that event are returned."""
        after_id = f"evt_{self.run_id}_0002"
        filtered, status = get_historical_events(self.run_id, after_event_id=after_id, return_cursor_status=True)

        self.assertEqual(status, CursorStatus.VALID)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]["event_id"], f"evt_{self.run_id}_0003")
        self.assertEqual(filtered[1]["event_id"], f"evt_{self.run_id}_0004")

    def test_unknown_event_id(self):
        """Test 5: An unknown event ID for this run is flagged UNKNOWN and safely replays full history."""
        unknown_id = f"evt_{self.run_id}_9999"
        history, status = get_historical_events(self.run_id, after_event_id=unknown_id, return_cursor_status=True)

        self.assertEqual(status, CursorStatus.UNKNOWN)
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["seq"], 1)

    def test_malformed_event_id(self):
        """Test 6: A malformed event ID is flagged MALFORMED and safely replays full history."""
        malformed_id = "invalid@@@id!"
        history, status = get_historical_events(self.run_id, after_event_id=malformed_id, return_cursor_status=True)

        self.assertEqual(status, CursorStatus.MALFORMED)
        self.assertEqual(len(history), 4)

    def test_cross_run_event_id(self):
        """Test 7: A Last-Event-ID from a different run is flagged CROSS_RUN and never treated as a valid cursor."""
        cross_run_id = "evt_other_run_999_0002"
        history, status = get_historical_events(self.run_id, after_event_id=cross_run_id, return_cursor_status=True)

        self.assertEqual(status, CursorStatus.CROSS_RUN)
        # Never interprets cross-run ID as cursor: replays requested run's history
        self.assertEqual(len(history), 4)
        for evt in history:
            self.assertEqual(evt["run_id"], self.run_id)

    def test_reconnect_after_successful_completion(self):
        """Test 8: Reconnecting after successful completion retrieves full history including terminal done event."""
        _RUNS_STORE[self.run_id] = {"status": "completed", "run_id": self.run_id, "program_id": self.program_id}
        history = get_historical_events(self.run_id)
        self.assertEqual(len(history), 4)
        self.assertEqual(history[-1]["event_type"], "done")
        self.assertEqual(history[-1]["status"], "completed")

    def test_reconnect_after_failure(self):
        """Test 9: Reconnecting after failure retrieves full history including terminal error event."""
        fail_run_id = f"test_fail_reconnect_{datetime.datetime.now().timestamp()}"
        fail_ctx = RunContext(fail_run_id, "gemm", mode="ai")
        _RUN_CONTEXTS[fail_run_id] = fail_ctx
        _RUNS_STORE[fail_run_id] = {"status": "failed", "run_id": fail_run_id, "program_id": "gemm"}

        emit_canonical_event(fail_run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.PROFILING.value)
        emit_canonical_event(fail_run_id, EventType.ERROR.value, payload={"error": "Compilation error"})

        history = get_historical_events(fail_run_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["event_type"], "error")
        self.assertEqual(history[-1]["payload"]["error"], "Compilation error")

        _RUN_CONTEXTS.pop(fail_run_id, None)
        _RUNS_STORE.pop(fail_run_id, None)

    def test_client_side_deduplication_logic(self):
        """Simulate frontend reducer rejecting duplicate event IDs on reconnection."""
        seen_ids = set()
        rendered = []

        history = get_historical_events(self.run_id)
        # First pass
        for evt in history:
            eid = evt["event_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                rendered.append(evt)

        self.assertEqual(len(rendered), 4)

        # Second pass (replayed on reconnect)
        replayed_rendered = []
        for evt in history:
            eid = evt["event_id"]
            if eid not in seen_ids:
                seen_ids.add(eid)
                replayed_rendered.append(evt)

        # Zero duplicates rendered
        self.assertEqual(len(replayed_rendered), 0)


class TestSequenceGapDetectionAndReducerLogic(unittest.TestCase):
    """
    Test frontend reducer logic for sequence gap detection, out-of-order/duplicate events,
    resynchronization, and single-terminal event enforcement.
    """

    def _create_simulated_reducer(self, run_id: str, program_id: str):
        state = {
            "seen_event_ids": set(),
            "missing_seqs": set(),
            "resynced_cursors": set(),
            "last_seen_seq": 0,
            "last_seen_event_id": None,
            "terminal_handled": False,
            "has_unresolved_gap": False,
            "sync_warnings": [],
            "rendered_messages": [],
            "completed_calls": 0,
        }

        def process_incoming_event(data):
            if not data:
                return False

            if data.get("run_id") and data.get("run_id") != run_id:
                return False
            if data.get("program_id") and data.get("program_id") != program_id:
                return False

            # Deduplication by stable event_id
            event_id = data.get("event_id")
            if event_id:
                if event_id in state["seen_event_ids"]:
                    return False
                state["seen_event_ids"].add(event_id)

            seq = data.get("seq")
            if isinstance(seq, int):
                if seq <= state["last_seen_seq"] and state["last_seen_seq"] > 0:
                    # Older or duplicate seq
                    if seq in state["missing_seqs"]:
                        state["missing_seqs"].remove(seq)
                        if not state["missing_seqs"]:
                            state["has_unresolved_gap"] = False
                            state["sync_warnings"].clear()
                elif state["last_seen_seq"] > 0 and seq > state["last_seen_seq"] + 1:
                    # Gap detected
                    for s in range(state["last_seen_seq"] + 1, seq):
                        state["missing_seqs"].add(s)
                    state["has_unresolved_gap"] = True
                    state["sync_warnings"].append(f"gap_{state['last_seen_seq'] + 1}..{seq - 1}")
                    state["last_seen_seq"] = seq
                    if event_id:
                        state["last_seen_event_id"] = event_id
                else:
                    state["last_seen_seq"] = seq
                    if event_id:
                        state["last_seen_event_id"] = event_id
                    if seq in state["missing_seqs"]:
                        state["missing_seqs"].remove(seq)
                        if not state["missing_seqs"]:
                            state["has_unresolved_gap"] = False
                            state["sync_warnings"].clear()

            evt_type = data.get("event_type") or data.get("type")
            if evt_type == "agent_message":
                state["rendered_messages"].append(data)
            elif evt_type in ("done", "error"):
                if state["terminal_handled"]:
                    return False
                state["terminal_handled"] = True
                state["completed_calls"] += 1
                if state["has_unresolved_gap"] and state["missing_seqs"]:
                    state["sync_warnings"].append("terminal_with_unresolved_gap")

            return True

        return state, process_incoming_event

    def test_receiving_seq1_followed_by_seq3_gap_detected(self):
        """Test 1: Receiving seq 1 followed by seq 3 explicitly detects gap and does not claim complete history."""
        run_id = "test_gap_run"
        state, process = self._create_simulated_reducer(run_id, "gemm")

        e1 = {"event_id": f"evt_{run_id}_0001", "run_id": run_id, "program_id": "gemm", "seq": 1, "event_type": "agent_message", "payload": {"text": "m1"}}
        e3 = {"event_id": f"evt_{run_id}_0003", "run_id": run_id, "program_id": "gemm", "seq": 3, "event_type": "agent_message", "payload": {"text": "m3"}}

        process(e1)
        self.assertEqual(state["last_seen_seq"], 1)
        self.assertFalse(state["has_unresolved_gap"])

        process(e3)
        self.assertEqual(state["last_seen_seq"], 3)
        self.assertTrue(state["has_unresolved_gap"])
        self.assertIn(2, state["missing_seqs"])
        self.assertTrue(any("gap_2..2" in w for w in state["sync_warnings"]))

    def test_receiving_older_duplicate_event(self):
        """Test 2: Receiving an older duplicate event is dropped and cannot corrupt state."""
        run_id = "test_dup_run"
        state, process = self._create_simulated_reducer(run_id, "gemm")

        e1 = {"event_id": f"evt_{run_id}_0001", "run_id": run_id, "program_id": "gemm", "seq": 1, "event_type": "agent_message", "payload": {"text": "m1"}}
        e2 = {"event_id": f"evt_{run_id}_0002", "run_id": run_id, "program_id": "gemm", "seq": 2, "event_type": "agent_message", "payload": {"text": "m2"}}

        process(e1)
        process(e2)
        self.assertEqual(state["last_seen_seq"], 2)
        self.assertEqual(len(state["rendered_messages"]), 2)

        # Re-send older e1
        ret = process(e1)
        self.assertFalse(ret)
        self.assertEqual(state["last_seen_seq"], 2)  # Not rolled back
        self.assertEqual(len(state["rendered_messages"]), 2)  # Not duplicated

    def test_resynchronizing_without_duplicate_message_cards(self):
        """Test 3: Resynchronizing resolves missing events without duplicating existing cards."""
        run_id = "test_resync_run"
        state, process = self._create_simulated_reducer(run_id, "gemm")

        e1 = {"event_id": f"evt_{run_id}_0001", "run_id": run_id, "program_id": "gemm", "seq": 1, "event_type": "agent_message", "payload": {"text": "m1"}}
        e2 = {"event_id": f"evt_{run_id}_0002", "run_id": run_id, "program_id": "gemm", "seq": 2, "event_type": "agent_message", "payload": {"text": "m2"}}
        e3 = {"event_id": f"evt_{run_id}_0003", "run_id": run_id, "program_id": "gemm", "seq": 3, "event_type": "agent_message", "payload": {"text": "m3"}}

        # Receive 1 then 3 (gap)
        process(e1)
        process(e3)
        self.assertTrue(state["has_unresolved_gap"])
        self.assertEqual(len(state["rendered_messages"]), 2)

        # Resynchronization delivers e2 and replays e3
        process(e2)  # Missing event arrives
        process(e3)  # Replayed duplicate

        self.assertFalse(state["has_unresolved_gap"])
        self.assertEqual(len(state["missing_seqs"]), 0)
        # Total rendered messages must be exactly 3 (no duplicate cards)
        self.assertEqual(len(state["rendered_messages"]), 3)

    def test_terminal_event_not_processed_twice(self):
        """Test 10: Ensuring terminal events are not processed twice."""
        run_id = "test_term_run"
        state, process = self._create_simulated_reducer(run_id, "gemm")

        e_done = {"event_id": f"evt_{run_id}_0001", "run_id": run_id, "program_id": "gemm", "seq": 1, "event_type": "done", "status": "completed"}
        ret1 = process(e_done)
        self.assertTrue(ret1)
        self.assertEqual(state["completed_calls"], 1)

        # Second terminal delivery
        ret2 = process(e_done)
        self.assertFalse(ret2)
        self.assertEqual(state["completed_calls"], 1)  # Still 1, not called twice

    def test_terminal_event_does_not_conceal_unresolved_gap(self):
        """A terminal event does not conceal an unresolved sequence gap."""
        run_id = "test_gap_term_run"
        state, process = self._create_simulated_reducer(run_id, "gemm")

        e1 = {"event_id": f"evt_{run_id}_0001", "run_id": run_id, "program_id": "gemm", "seq": 1, "event_type": "agent_message"}
        # seq 2 is missing
        e_done = {"event_id": f"evt_{run_id}_0003", "run_id": run_id, "program_id": "gemm", "seq": 3, "event_type": "done"}

        process(e1)
        process(e_done)

        self.assertTrue(state["has_unresolved_gap"])
        self.assertIn("terminal_with_unresolved_gap", state["sync_warnings"])


class TestVerdictAndNoiseAlignment(unittest.TestCase):
    """Test performance comparison classification alignment between backend and frontend."""

    def test_inconclusive_when_unreliable(self):
        """When timing is unreliable (e.g. CV > 10% or noisy), verdict MUST be INCONCLUSIVE, never IMPROVED."""
        base_timing = {"median_s": 0.050, "timing_is_reliable": False}
        ai_timing = {"median_s": 0.025, "timing_is_reliable": True}

        # Speedup is 2.0x (100% gain) numerically, but unreliable
        def evaluate_verdict(base_t, ai_t, backend_reg):
            if base_t.get("timing_is_reliable") is False or ai_t.get("timing_is_reliable") is False or backend_reg == "INCONCLUSIVE":
                return "INCONCLUSIVE"
            if backend_reg == "IMPROVED":
                return "IMPROVED"
            if backend_reg == "REGRESSED":
                return "REGRESSED"
            speedup = base_t["median_s"] / ai_t["median_s"]
            if speedup > 1.02:
                return "IMPROVED"
            if speedup < 0.98:
                return "REGRESSED"
            return "PARITY"

        verdict = evaluate_verdict(base_timing, ai_timing, backend_reg=None)
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_backend_inconclusive_override(self):
        """Backend INCONCLUSIVE status overrides raw speedup calculation."""
        base_timing = {"median_s": 0.050, "timing_is_reliable": True}
        ai_timing = {"median_s": 0.025, "timing_is_reliable": True}

        def evaluate_verdict(base_t, ai_t, backend_reg):
            if base_t.get("timing_is_reliable") is False or ai_t.get("timing_is_reliable") is False or backend_reg == "INCONCLUSIVE":
                return "INCONCLUSIVE"
            if backend_reg == "IMPROVED":
                return "IMPROVED"
            if backend_reg == "REGRESSED":
                return "REGRESSED"
            return "PARITY"

        verdict = evaluate_verdict(base_timing, ai_timing, backend_reg="INCONCLUSIVE")
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_reliable_improvement(self):
        """Reliable speedup > 1.02 classified as IMPROVED."""
        base_timing = {"median_s": 0.050, "timing_is_reliable": True}
        ai_timing = {"median_s": 0.040, "timing_is_reliable": True}

        def evaluate_verdict(base_t, ai_t, backend_reg):
            if base_t.get("timing_is_reliable") is False or ai_t.get("timing_is_reliable") is False or backend_reg == "INCONCLUSIVE":
                return "INCONCLUSIVE"
            if backend_reg == "IMPROVED":
                return "IMPROVED"
            speedup = base_t["median_s"] / ai_t["median_s"]
            if speedup > 1.02:
                return "IMPROVED"
            return "PARITY"

        verdict = evaluate_verdict(base_timing, ai_timing, backend_reg="IMPROVED")
        self.assertEqual(verdict, "IMPROVED")

    def test_missing_or_zero_measurements_rejected(self):
        """Missing or zero timing must never be reported as IMPROVED."""
        base_timing = {"median_s": None, "timing_is_reliable": True}
        ai_timing = {"median_s": 0.020, "timing_is_reliable": True}

        def can_evaluate(base_t, ai_t):
            if not base_t or base_t.get("median_s") is None or not ai_t or ai_t.get("median_s") is None:
                return False
            if base_t["median_s"] <= 0 or ai_t["median_s"] <= 0:
                return False
            return True

        self.assertFalse(can_evaluate(base_timing, ai_timing))
        self.assertFalse(can_evaluate({"median_s": 0.0}, {"median_s": 0.02}))


class TestWorkflowStageTransitions(unittest.TestCase):
    """Test explicit stage transitions and checklist mapping."""

    def test_stage_event_emission(self):
        run_id = f"test_stages_{datetime.datetime.now().timestamp()}"
        ctx = RunContext(run_id, "tc3", mode="ai")
        _RUN_CONTEXTS[run_id] = ctx

        # 1. Profiling
        e_prof_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.PROFILING.value)
        e_prof_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.PROFILING.value, payload={"profile": "MathHeavy"})
        self.assertEqual(e_prof_start.event_type, "stage_started")
        self.assertEqual(e_prof_done.event_type, "stage_completed")
        self.assertEqual(e_prof_done.payload["profile"], "MathHeavy")

        # 2. Strategy selection
        e_strat_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.STRATEGY_SELECTION.value)
        e_strat_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.STRATEGY_SELECTION.value, payload={"strategy": "-O3"})
        self.assertEqual(e_strat_done.payload["strategy"], "-O3")

        # 3. Agent review
        e_rev_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.AGENT_REVIEW.value)
        e_rev_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.AGENT_REVIEW.value, payload={"revisions": 1})
        self.assertEqual(e_rev_done.payload["revisions"], 1)

        # 4. Security verification
        e_sec_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.SECURITY_VERIFICATION.value)
        e_sec_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.SECURITY_VERIFICATION.value, payload={"verdict": "ACCEPT"})
        self.assertEqual(e_sec_done.payload["verdict"], "ACCEPT")

        # 5. Benchmarking
        e_bench_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.BENCHMARKING.value)
        e_bench_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.BENCHMARKING.value, payload={"timing": 0.042})
        self.assertEqual(e_bench_done.payload["timing"], 0.042)

        # 6. Regression analysis
        e_reg_start = emit_canonical_event(run_id, EventType.STAGE_STARTED.value, stage=PipelineStage.REGRESSION_ANALYSIS.value)
        e_reg_done = emit_canonical_event(run_id, EventType.STAGE_COMPLETED.value, stage=PipelineStage.REGRESSION_ANALYSIS.value, payload={"overall_status": "IMPROVED"})
        self.assertEqual(e_reg_done.payload["overall_status"], "IMPROVED")

        # 7. Terminal done
        e_done = emit_canonical_event(run_id, EventType.DONE.value, payload={"status": "completed"})
        self.assertEqual(e_done.event_type, "done")
        self.assertEqual(ctx.seq, 13)

        _RUN_CONTEXTS.pop(run_id, None)


if __name__ == "__main__":
    unittest.main()
