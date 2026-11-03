"""
web.service — Execution service connecting Web UI to TOACD backend engines.

Coordinates:
- MultiAgentOrchestrator for genuine multi-agent deliberation & optimization
- PipelineOrchestrator for baseline -O3 reference execution
- Toolchain inspection and runtime diagnostics
- Safe temporary file isolation and automatic cleanup
- Result serialization for the Web UI (RunRecord, to_gui_view, IR diff, XAI)
"""

from __future__ import annotations

import os
import sys
import shutil
import tempfile
import uuid
import time
import datetime
import threading
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor

# Ensure parent directory is on sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.dirname(_current_dir)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from web.events import (
    EventEnvelope,
    SCHEMA_VERSION,
    PipelineStage,
    StageStatus,
    RunState,
    EventType,
    CursorStatus,
    validate_cursor,
)
from moo.multiagent.schema import AgentMessage, ROLE_ORCHESTRATOR
from moo.multiagent.orchestrator import MultiAgentOrchestrator
from moo.multiagent.message_log import MessageLog
from moo.runrecord.orchestrator import PipelineOrchestrator
from moo.runrecord.projections import to_gui_view, security_display_text, validate_reference_run
from moo.runrecord.schema import RunRecord, RunStatus, MeasurementStatus
from moo.toolchain import verify_toolchain
from moo.config import CLANG_PATH, OPT_PATH
from web.report import generate_workflow_report

logger = logging.getLogger(__name__)

# Sample benchmarks repository path
_TEST_CASES_DIR = os.path.normpath(
    os.path.join(_scripts_dir, "..", "test_cases")
)


class RunContext:
    """
    Thread-safe lifecycle context and event recorder for a single execution run.
    """
    def __init__(self, run_id: str, program_id: str, mode: str) -> None:
        self.run_id: str = run_id
        self.program_id: str = program_id
        self.mode: str = mode
        self.status: str = RunState.RUNNING.value
        self.seq: int = 0
        self.events: List[EventEnvelope] = []
        self.terminal_event_emitted: bool = False
        self.lock: threading.Lock = threading.Lock()


# In-memory stores
_RUNS_STORE: Dict[str, Dict[str, Any]] = {}
_RUN_CONTEXTS: Dict[str, RunContext] = {}
_RUN_MESSAGES: Dict[str, List[Dict[str, Any]]] = {}
_RUN_LISTENERS: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

DEFAULT_SOURCE_CODE = """// Polybench GEMM benchmark - compute C = alpha*A*B + beta*C
#include <stdio.h>

#define NI 64
#define NJ 64
#define NK 64

void kernel_gemm(int ni, int nj, int nk,
                 double alpha, double beta,
                 double C[NI][NJ],
                 double A[NI][NK],
                 double B[NK][NJ]) {
  // Affine loop nest: candidate for vectorization and loop tiling
  for (int i = 0; i < ni; i++) {
    for (int j = 0; j < nj; j++) {
      C[i][j] *= beta;
    }
    for (int k = 0; k < nk; k++) {
      for (int j = 0; j < nj; j++) {
        C[i][j] += alpha * A[i][k] * B[k][j];
      }
    }
  }
}

int main(void) {
  static double C[NI][NJ];
  static double A[NI][NK];
  static double B[NK][NJ];

  for (int i = 0; i < NI; i++)
    for (int j = 0; j < NK; j++)
      A[i][j] = (double)(i * j % 1024) / 1024.0;

  for (int i = 0; i < NK; i++)
    for (int j = 0; j < NJ; j++)
      B[i][j] = (double)(i * j % 512) / 512.0;

  for (int i = 0; i < NI; i++)
    for (int j = 0; j < NJ; j++)
      C[i][j] = 0.5;

  kernel_gemm(NI, NJ, NK, 1.5, 1.2, C, A, B);
  printf("C[0][0] = %f\\n", C[0][0]);
  return 0;
}
"""

def get_toolchain_status() -> Dict[str, Any]:
    """Inspect and return Clang/LLVM toolchain status."""
    clang_info, opt_info, incomp = verify_toolchain()
    clang_found = bool(getattr(clang_info, "found", False))
    opt_found = bool(getattr(opt_info, "found", False))

    clang_v = getattr(clang_info, "version_string", "") or ""
    opt_v = getattr(opt_info, "version_string", "") or ""

    # Extract short version line
    clang_short = clang_v.splitlines()[0] if clang_v else "Not Installed"
    opt_short = opt_v.splitlines()[0] if opt_v else "Not Installed"

    return {
        "clang_found": clang_found,
        "clang_path": getattr(clang_info, "path", None),
        "clang_version": clang_short,
        "clang_version_full": clang_v,
        "opt_found": opt_found,
        "opt_path": getattr(opt_info, "path", None),
        "opt_version": opt_short,
        "opt_version_full": opt_v,
        "incompatibilities": [str(i) for i in incomp],
        "toolchain_ok": clang_found and opt_found and len(incomp) == 0,
        "host_platform": sys.platform,
        "default_target": "x86_64 znver4 / raptorlake",
    }


def list_sample_benchmarks() -> List[Dict[str, str]]:
    """List available C benchmark samples."""
    samples = [
        {
            "id": "gemm",
            "name": "Polybench GEMM (Matrix Multiplication)",
            "description": "Affine triple-nested loop computing C = alpha*A*B + beta*C. High SIMD potential.",
            "category": "Math & SIMD",
        },
        {
            "id": "tc1_loop_heavy",
            "name": "TC1: Heavy Loops Accumulation",
            "description": "Heavy loops accumulation and reduction with SIMD and loop unrolling potential.",
            "category": "Loop Optimization",
        },
        {
            "id": "tc2_security_bounds",
            "name": "TC2: Security Bounds & Assert Guards",
            "description": "Buffer access with assert_failed bounds checking. Tests security gate preservation.",
            "category": "Security Verification",
        },
        {
            "id": "tc3_math_intensive",
            "name": "TC3: Math Intensive Float Pipeline",
            "description": "Trigonometric and polynomial computations evaluating vector arithmetic.",
            "category": "Math & SIMD",
        },
        {
            "id": "tc4_security_null",
            "name": "TC4: Null Pointer & Overflow Guard",
            "description": "Pointer sanitization and integer overflow safety checks.",
            "category": "Security Verification",
        },
        {
            "id": "bubble_sort",
            "name": "Bubble Sort (Memory & Branching)",
            "description": "Quadratic element swapping with dependent branch conditions.",
            "category": "Sorting & Memory",
        },
    ]
    return samples


def get_sample_source(sample_id: str) -> str:
    """Load sample benchmark source code."""
    if sample_id == "gemm":
        return DEFAULT_SOURCE_CODE

    filename_map = {
        "tc1_loop_heavy": "TC1_loop_heavy.c",
        "tc2_security_bounds": "TC2_security_bounds_check.c",
        "tc3_math_intensive": "TC3_math_intensive.c",
        "tc4_security_null": "TC4_security_null_overflow.c",
        "bubble_sort": "26_bubble_sort.c",
    }

    fn = filename_map.get(sample_id)
    if fn and os.path.isdir(_TEST_CASES_DIR):
        full_path = os.path.join(_TEST_CASES_DIR, fn)
        if os.path.isfile(full_path):
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except Exception as exc:
                logger.warning("Could not read sample file %s: %s", full_path, exc)

    return DEFAULT_SOURCE_CODE


def register_listener(run_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
    """Register an SSE / message listener for a run."""
    if run_id not in _RUN_LISTENERS:
        _RUN_LISTENERS[run_id] = []
    _RUN_LISTENERS[run_id].append(callback)


def unregister_listener(run_id: str, callback: Callable[[Dict[str, Any]], None]) -> None:
    """Remove a listener."""
    if run_id in _RUN_LISTENERS:
        try:
            _RUN_LISTENERS[run_id].remove(callback)
        except ValueError:
            pass


def get_historical_events(
    run_id: str,
    after_event_id: Optional[str] = None,
    return_cursor_status: bool = False,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], CursorStatus]]:
    """
    Return canonical historical events emitted for a given run.
    Validates after_event_id (Last-Event-ID):
    - None or empty: returns full history (CursorStatus.NONE).
    - Valid ID in this run: returns events strictly after that event (CursorStatus.VALID).
    - Unknown ID for this run: logs warning, safely replays full history (CursorStatus.UNKNOWN).
    - Malformed ID: logs warning, safely replays full history (CursorStatus.MALFORMED).
    - Cross-run ID: logs warning, safely replays full history of requested run (CursorStatus.CROSS_RUN).
      Never interprets a cross-run event ID as a valid cursor for the current run.
    """
    ctx = _RUN_CONTEXTS.get(run_id)
    if ctx:
        with ctx.lock:
            all_events = [e.to_dict() for e in ctx.events]
    else:
        all_events = list(_RUN_MESSAGES.get(run_id, []))

    if not after_event_id:
        if return_cursor_status:
            return all_events, CursorStatus.NONE
        return all_events

    known_ids = [evt.get("event_id") for evt in all_events if evt.get("event_id")]
    status, seq = validate_cursor(after_event_id, run_id, known_ids)

    if status == CursorStatus.VALID:
        target_idx = -1
        for idx, evt in enumerate(all_events):
            if evt.get("event_id") == after_event_id:
                target_idx = idx
                break
        events_to_return = all_events[target_idx + 1:] if target_idx >= 0 else all_events
    elif status == CursorStatus.CROSS_RUN:
        logger.warning(
            "Rejected cross-run Last-Event-ID '%s' for run '%s'. Replaying full history of requested run.",
            after_event_id,
            run_id,
        )
        events_to_return = all_events
    elif status == CursorStatus.MALFORMED:
        logger.warning(
            "Rejected malformed Last-Event-ID '%s' for run '%s'. Replaying full history.",
            after_event_id,
            run_id,
        )
        events_to_return = all_events
    elif status == CursorStatus.UNKNOWN:
        logger.warning(
            "Unknown Last-Event-ID '%s' for run '%s' (not found in log). Replaying full history.",
            after_event_id,
            run_id,
        )
        events_to_return = all_events
    else:
        events_to_return = all_events

    if return_cursor_status:
        return events_to_return, status
    return events_to_return


def get_historical_messages(run_id: str) -> List[Dict[str, Any]]:
    """Return historical messages emitted for a given run (backward compatibility alias)."""
    return get_historical_events(run_id)


def get_workflow_report(run_id: str) -> Optional[Dict[str, Any]]:
    """Return deterministic Plain-English Workflow Report for a run."""
    run_data = _RUNS_STORE.get(run_id)
    if not run_data:
        return None
    run_ctx = _RUN_CONTEXTS.get(run_id)
    events = run_ctx.events if run_ctx else []
    report = generate_workflow_report(run_data, events)
    # If run has reached terminal state, store it so get_run_result returns it consistently
    if run_data.get("status") in ("completed", "failed", "blocked"):
        run_data["report"] = report
    return report


def get_run_result(run_id: str) -> Optional[Dict[str, Any]]:
    """Return complete run status & data, ensuring Plain-English Report matches current state."""
    data = _RUNS_STORE.get(run_id)
    if not data:
        return None
    # Invalidate and regenerate report if missing, currently running, or if cached report was provisional
    cached_report = data.get("report")
    if (
        cached_report is None
        or data.get("status") == "running"
        or (cached_report.get("is_provisional") and data.get("status") != "running")
    ):
        data["report"] = get_workflow_report(run_id)
    return data


def emit_canonical_event(
    run_id: str,
    event_type: str,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> Optional[EventEnvelope]:
    """
    Construct, validate, record, and broadcast a canonical event envelope.
    Thread-safe and enforces:
    - Strictly monotonic sequence within the run
    - Stable event IDs (evt_<run_id>_<seq:04d>)
    - At most one terminal state transition per run
    - Zero application events after terminal state
    """
    ctx = _RUN_CONTEXTS.get(run_id)
    if not ctx:
        return None

    with ctx.lock:
        if ctx.terminal_event_emitted:
            logger.warning(
                "Attempted to emit event %s after terminal state for run %s",
                event_type,
                run_id,
            )
            return None

        ctx.seq += 1
        event_id = f"evt_{run_id}_{ctx.seq:04d}"
        now_ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur_status = status or ctx.status

        # Check terminal transition
        is_terminal = False
        if event_type in (EventType.DONE.value, EventType.ERROR.value, "done", "error"):
            is_terminal = True
            if event_type in ("done", EventType.DONE.value):
                ctx.status = RunState.COMPLETED.value
            else:
                ctx.status = RunState.FAILED.value
            cur_status = ctx.status
            ctx.terminal_event_emitted = True
        elif status == StageStatus.FAILED.value and stage == "run":
            is_terminal = True
            ctx.status = RunState.FAILED.value
            cur_status = ctx.status
            ctx.terminal_event_emitted = True
        elif status == StageStatus.BLOCKED.value and stage == "run":
            is_terminal = True
            ctx.status = RunState.BLOCKED.value
            cur_status = ctx.status
            ctx.terminal_event_emitted = True

        envelope = EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id=event_id,
            run_id=run_id,
            program_id=ctx.program_id,
            seq=ctx.seq,
            timestamp=now_ts,
            event_type=event_type,
            stage=stage,
            status=cur_status,
            payload=dict(payload or {}),
        )
        envelope.validate()

        ctx.events.append(envelope)

        event_dict = envelope.to_dict()
        if run_id not in _RUN_MESSAGES:
            _RUN_MESSAGES[run_id] = []
        _RUN_MESSAGES[run_id].append(event_dict)

    # Broadcast outside of lock to avoid lock contention
    listeners = list(_RUN_LISTENERS.get(run_id, []))
    for listener in listeners:
        try:
            listener(event_dict)
        except Exception as exc:
            logger.debug("Listener callback error: %s", exc)

    return envelope


def _emit_event(run_id: str, event_data: Dict[str, Any]) -> None:
    """Legacy helper forwarding to emit_canonical_event."""
    etype = event_data.get("type") or event_data.get("event_type", "message")
    stage = event_data.get("stage")
    status = event_data.get("status")
    payload = dict(event_data.get("payload", {}))
    # If legacy fields exist at root, preserve them in payload
    for k, v in event_data.items():
        if k not in ("type", "event_type", "stage", "status", "payload", "run_id", "program_id", "schema_version", "event_id", "seq", "timestamp"):
            payload[k] = v
    emit_canonical_event(
        run_id=run_id,
        event_type=etype,
        stage=stage,
        status=status,
        payload=payload,
        timestamp=event_data.get("timestamp"),
    )


def _generate_ir_preview(source_path: str, strategy: str, workdir: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Safely compile unoptimized and optimized LLVM IR previews for the Optimized Code tab.
    """
    import subprocess
    unopt_ir_text = None
    opt_ir_text = None

    try:
        from moo.toolchain import verify_toolchain
        clang_info, _, _ = verify_toolchain()
        if not getattr(clang_info, "found", False):
            return None, None

        clang_exe = clang_info.path
        unopt_path = os.path.join(workdir, "preview_unopt.ll")
        cmd_unopt = [
            clang_exe, "-O0", "-Xclang", "-disable-O0-optnone",
            "-S", "-emit-llvm", source_path, "-o", unopt_path
        ]
        r1 = subprocess.run(cmd_unopt, capture_output=True, text=True, timeout=15)
        if r1.returncode == 0 and os.path.isfile(unopt_path):
            with open(unopt_path, "r", encoding="utf-8", errors="replace") as f:
                unopt_ir_text = f.read()

        opt_path = os.path.join(workdir, "preview_opt.ll")
        strat_flag = strategy if strategy.startswith("-") else "-O2"
        cmd_opt = [
            clang_exe, strat_flag, "-S", "-emit-llvm",
            source_path, "-o", opt_path
        ]
        r2 = subprocess.run(cmd_opt, capture_output=True, text=True, timeout=15)
        if r2.returncode == 0 and os.path.isfile(opt_path):
            with open(opt_path, "r", encoding="utf-8", errors="replace") as f:
                opt_ir_text = f.read()

    except Exception as exc:
        logger.debug("IR preview generation error: %s", exc)

    return unopt_ir_text, opt_ir_text


def execute_run_task(
    run_id: str,
    source_code: str,
    mode: str = "ai",
    strategy: Optional[str] = None,
    warmup_runs: int = 1,
    measure_runs: int = 3,
    timeout_s: int = 10,
    program_id: Optional[str] = "custom",
) -> None:
    """
    Worker task executing either MultiAgentOrchestrator (mode='ai')
    or PipelineOrchestrator baseline (mode='normal').
    """
    start_time = time.time()
    temp_dir = tempfile.mkdtemp(prefix=f"toacd_web_{run_id[:8]}_")
    source_path = os.path.join(temp_dir, "input.c")
    active_program_id = program_id or "custom"

    # Initialize authoritative RunContext
    run_ctx = RunContext(run_id=run_id, program_id=active_program_id, mode=mode)
    _RUN_CONTEXTS[run_id] = run_ctx

    _RUNS_STORE[run_id] = {
        "run_id": run_id,
        "program_id": active_program_id,
        "mode": mode,
        "status": "running",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_code": source_code,
        "record": None,
        "view": None,
        "messages": [],
        "unopt_ir": None,
        "opt_ir": None,
        "error": None,
    }

    try:
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(source_code)

        if mode == "ai":
            # Multi-agent workflow
            def on_agent_message(msg: AgentMessage) -> None:
                emit_canonical_event(
                    run_id=run_id,
                    event_type=EventType.AGENT_MESSAGE.value,
                    stage=None,
                    status=RunState.RUNNING.value,
                    payload={
                        "step": msg.step,
                        "sender": msg.sender,
                        "recipient": msg.recipient,
                        "message_type": msg.message_type,
                        "timestamp": msg.timestamp,
                        "payload": msg.payload,
                        "message_id": getattr(msg, "message_id", None),
                    },
                )

            def on_stage_transition(stage_name: str, stage_status: str, stage_payload: Optional[Dict[str, Any]] = None) -> None:
                evt_type = f"stage_{stage_status}"
                emit_canonical_event(
                    run_id=run_id,
                    event_type=evt_type,
                    stage=stage_name,
                    status=stage_status,
                    payload=stage_payload or {},
                )

            orch = MultiAgentOrchestrator()
            record, msg_log = orch.run(
                source_path=source_path,
                selected_strategy=strategy,
                run_benchmarks=True,
                run_security=True,
                run_regression=True,
                run_adaptive=True,
                run_agentic=True,
                warmup_runs=warmup_runs,
                measure_runs=measure_runs,
                timeout_s=timeout_s,
                run_id=run_id,
                on_message=on_agent_message,
                on_stage=on_stage_transition,
            )

            view = to_gui_view(record)
            effective_strat = record.effective_strategy or record.selected_strategy or "-O2"
            unopt_ir, opt_ir = _generate_ir_preview(source_path, effective_strat, temp_dir)

            _RUNS_STORE[run_id].update({
                "status": "completed",
                "program_id": active_program_id,
                "record": record.to_dict(),
                "view": view,
                "messages": msg_log.to_list(),
                "unopt_ir": unopt_ir,
                "opt_ir": opt_ir,
                "elapsed_s": round(time.time() - start_time, 3),
            })
            _RUNS_STORE[run_id]["report"] = generate_workflow_report(
                _RUNS_STORE[run_id],
                run_ctx.events if run_ctx else []
            )

            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.DONE.value,
                stage=None,
                status=RunState.COMPLETED.value,
                payload={
                    "effective_strategy": effective_strat,
                    "elapsed_s": round(time.time() - start_time, 3),
                },
            )

        else:
            # Baseline execution (-O3)
            # Stage 1: Profiling
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_STARTED.value,
                stage=PipelineStage.PROFILING.value,
                status=StageStatus.STARTED.value,
                payload={"source_path": source_path},
            )
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.AGENT_MESSAGE.value,
                stage=PipelineStage.PROFILING.value,
                status=RunState.RUNNING.value,
                payload={
                    "step": 1,
                    "sender": "CodeAnalystAgent",
                    "recipient": "Orchestrator",
                    "message_type": "CODE_ANALYSIS",
                    "analysis": "Inspecting source for -O3 baseline reference compilation.",
                },
            )
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_COMPLETED.value,
                stage=PipelineStage.PROFILING.value,
                status=StageStatus.COMPLETED.value,
                payload={"analysis": "Source inspection complete"},
            )

            # Stages 2, 3, 4: Skipped in baseline mode
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_SKIPPED.value,
                stage=PipelineStage.STRATEGY_SELECTION.value,
                status=StageStatus.SKIPPED.value,
                payload={"reason": "Baseline mode uses fixed -O3 reference"},
            )
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_SKIPPED.value,
                stage=PipelineStage.AGENT_REVIEW.value,
                status=StageStatus.SKIPPED.value,
                payload={"reason": "Baseline mode bypasses multi-agent review"},
            )
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_SKIPPED.value,
                stage=PipelineStage.SECURITY_VERIFICATION.value,
                status=StageStatus.SKIPPED.value,
                payload={"reason": "Baseline mode bypasses security gate"},
            )

            # Stage 5: Benchmarking
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_STARTED.value,
                stage=PipelineStage.BENCHMARKING.value,
                status=StageStatus.STARTED.value,
                payload={"strategy": "-O3"},
            )

            orch = PipelineOrchestrator()
            record = orch.execute_pipeline(
                source_path=source_path,
                selected_strategy="-O3",
                run_security=False,
                run_regression=False,
                run_adaptive=False,
                run_agentic=False,
                warmup_runs=warmup_runs,
                measure_runs=measure_runs,
                timeout_s=timeout_s,
            )

            view = to_gui_view(record)
            is_valid, reason = validate_reference_run(view, "-O3")
            unopt_ir, opt_ir = _generate_ir_preview(source_path, "-O3", temp_dir)

            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.AGENT_MESSAGE.value,
                stage=PipelineStage.BENCHMARKING.value,
                status=RunState.RUNNING.value,
                payload={
                    "step": 2,
                    "sender": "BenchmarkAgent",
                    "recipient": "Orchestrator",
                    "message_type": "BENCHMARK_REPORT",
                    "strategy": "-O3",
                    "valid_reference": is_valid,
                    "validation_reason": reason,
                    "timing": view.get("optimized_timing"),
                },
            )
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_COMPLETED.value,
                stage=PipelineStage.BENCHMARKING.value,
                status=StageStatus.COMPLETED.value,
                payload={
                    "strategy": "-O3",
                    "valid_reference": is_valid,
                    "timing": view.get("optimized_timing"),
                },
            )

            # Stage 6: Regression analysis (skipped in single baseline mode)
            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.STAGE_SKIPPED.value,
                stage=PipelineStage.REGRESSION_ANALYSIS.value,
                status=StageStatus.SKIPPED.value,
                payload={"reason": "Baseline reference run; regression comparison awaits AI run"},
            )

            _RUNS_STORE[run_id].update({
                "status": "completed",
                "program_id": active_program_id,
                "record": record.to_dict(),
                "view": view,
                "unopt_ir": unopt_ir,
                "opt_ir": opt_ir,
                "is_valid_reference": is_valid,
                "reference_validation_reason": reason,
                "elapsed_s": round(time.time() - start_time, 3),
            })
            _RUNS_STORE[run_id]["report"] = generate_workflow_report(
                _RUNS_STORE[run_id],
                run_ctx.events if run_ctx else []
            )

            emit_canonical_event(
                run_id=run_id,
                event_type=EventType.DONE.value,
                stage=None,
                status=RunState.COMPLETED.value,
                payload={
                    "strategy": "-O3",
                    "elapsed_s": round(time.time() - start_time, 3),
                },
            )

    except Exception as exc:
        logger.exception("Run execution failure for %s", run_id)
        _RUNS_STORE[run_id].update({
            "status": "failed",
            "program_id": active_program_id,
            "error": str(exc),
            "elapsed_s": round(time.time() - start_time, 3),
        })
        _RUNS_STORE[run_id]["report"] = generate_workflow_report(
            _RUNS_STORE[run_id],
            run_ctx.events if run_ctx else []
        )
        emit_canonical_event(
            run_id=run_id,
            event_type=EventType.ERROR.value,
            stage=None,
            status=RunState.FAILED.value,
            payload={
                "error": str(exc),
                "elapsed_s": round(time.time() - start_time, 3),
            },
        )

    finally:
        # Cleanup temporary files
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
