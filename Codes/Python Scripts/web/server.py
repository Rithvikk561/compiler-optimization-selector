"""
web.server — Tornado-based async web server and SSE streaming backend for TOACD.

Provides:
- Static dashboard serving (Theme 2: Professional Navy IDE layout)
- REST API for toolchain status and benchmark samples
- Asynchronous task dispatching via ThreadPoolExecutor
- Server-Sent Events (SSE) streaming for real-time multi-agent communication
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import asyncio
import logging
from typing import Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

import tornado.ioloop
import tornado.web
import tornado.httpserver

# Ensure python path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.dirname(_current_dir)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from web.events import CursorStatus
from web.service import (
    get_toolchain_status,
    list_sample_benchmarks,
    get_sample_source,
    get_historical_messages,
    get_historical_events,
    get_run_result,
    get_workflow_report,
    register_listener,
    unregister_listener,
    execute_run_task,
)

logger = logging.getLogger("toacd.web")
_executor = ThreadPoolExecutor(max_workers=4)


class BaseHandler(tornado.web.RequestHandler):
    """Base handler setting JSON headers and CORS."""

    def set_default_headers(self) -> None:
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def options(self, *args, **kwargs) -> None:
        self.set_status(204)
        self.finish()

    def write_json(self, data: Any, status_code: int = 200) -> None:
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.write(json.dumps(data, indent=2, default=str))


class IndexHandler(tornado.web.RequestHandler):
    """Serves the main application single-page dashboard."""

    def get(self) -> None:
        index_path = os.path.join(_current_dir, "static", "index.html")
        if os.path.isfile(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.write(f.read())
        else:
            self.set_status(404)
            self.write("TOACD Web Dashboard index.html not found.")


class StatusHandler(BaseHandler):
    """Toolchain & environment status."""

    def get(self) -> None:
        status = get_toolchain_status()
        self.write_json(status)


class SamplesHandler(BaseHandler):
    """Lists available C benchmarks."""

    def get(self) -> None:
        samples = list_sample_benchmarks()
        self.write_json({"samples": samples})


class SampleDetailHandler(BaseHandler):
    """Returns source code for a specific sample benchmark."""

    def get(self, sample_id: str) -> None:
        code = get_sample_source(sample_id)
        self.write_json({
            "sample_id": sample_id,
            "source_code": code,
        })


class RunHandler(BaseHandler):
    """Starts an optimization or baseline run."""

    async def post(self) -> None:
        try:
            body = json.loads(self.request.body.decode("utf-8")) if self.request.body else {}
        except Exception:
            self.write_json({"error": "Invalid JSON body"}, 400)
            return

        source_code = body.get("source_code", "").strip()
        if not source_code:
            self.write_json({"error": "Missing or empty source_code"}, 400)
            return

        mode = body.get("mode", "ai").lower()
        if mode not in ("ai", "normal"):
            mode = "ai"

        program_id = str(body.get("program_id") or "custom")
        strategy = body.get("strategy")
        warmup = int(body.get("warmup_runs", 1))
        measure = int(body.get("measure_runs", 3))
        timeout = int(body.get("timeout_s", 10))

        run_id = f"run_{uuid.uuid4().hex[:12]}"

        # Submit background task without blocking event loop
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            _executor,
            execute_run_task,
            run_id,
            source_code,
            mode,
            strategy,
            warmup,
            measure,
            timeout,
            program_id,
        )

        self.write_json({
            "run_id": run_id,
            "status": "started",
            "mode": mode,
            "program_id": program_id,
        }, 202)


class EventsHandler(tornado.web.RequestHandler):
    """
    Server-Sent Events (SSE) streaming endpoint for real-time agent messages.
    """

    def set_default_headers(self) -> None:
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache, no-transform")
        self.set_header("Connection", "keep-alive")
        self.set_header("X-Accel-Buffering", "no")
        self.set_header("Access-Control-Allow-Origin", "*")

    async def get(self, run_id: str) -> None:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def on_event(event: Dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        # Check Last-Event-ID header or query parameter for reconnection support
        last_event_id = self.request.headers.get("Last-Event-ID") or self.get_query_argument("last_event_id", None)

        # Replay historical events with cursor validation
        history, cursor_status = get_historical_events(run_id, after_event_id=last_event_id, return_cursor_status=True)

        if cursor_status != CursorStatus.NONE:
            self.set_header("X-TOACD-Cursor-Status", cursor_status.value)
            if cursor_status != CursorStatus.VALID:
                # Inform client that an invalid cursor resulted in a safe full-history replay
                self.write(f": toacd_replay_notice cursor_status={cursor_status.value} full_replay=true\n\n")

        for evt in history:
            await self._send_sse(evt)

        # Signal that historical replay is complete; subsequent events on this connection are live
        self.write("event: backfill_complete\ndata: {}\n\n")
        await self.flush()

        # Check if run has already reached an authoritative terminal state
        run_data = get_run_result(run_id)
        if run_data and run_data.get("status") in ("completed", "failed", "error", "blocked"):
            # All events through the terminal event were already replayed in history.
            # Close stream cleanly without emitting duplicate terminal events.
            self.finish()
            return

        register_listener(run_id, on_event)

        try:
            while True:
                # Wait for next event or timeout check
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    await self._send_sse(event)
                    evt_type = event.get("event_type") or event.get("type")
                    if evt_type in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment (ignored by application event listeners)
                    self.write(": ping\n\n")
                    await self.flush()
        except tornado.iostream.StreamClosedError:
            pass
        finally:
            unregister_listener(run_id, on_event)
            self.finish()

    async def _send_sse(self, event: Dict[str, Any]) -> None:
        event_id = event.get("event_id")
        event_type = event.get("event_type") or event.get("type", "message")
        payload_str = json.dumps(event, default=str)
        if event_id:
            chunk = f"id: {event_id}\nevent: {event_type}\ndata: {payload_str}\n\n"
        else:
            chunk = f"event: {event_type}\ndata: {payload_str}\n\n"
        self.write(chunk)
        await self.flush()


class ResultsHandler(BaseHandler):
    """Fetches complete run record and views for a given run."""

    def get(self, run_id: str) -> None:
        data = get_run_result(run_id)
        if not data:
            self.write_json({"error": f"Run '{run_id}' not found"}, 404)
            return

        self.write_json(data)


class ReportHandler(BaseHandler):
    """Fetches Plain-English Workflow Report for a given run."""

    def get(self, run_id: str) -> None:
        report = get_workflow_report(run_id)
        if not report:
            self.write_json({"error": f"Report for run '{run_id}' not found"}, 404)
            return

        self.write_json(report)


def make_app() -> tornado.web.Application:
    """Build the Tornado application routes."""
    static_dir = os.path.join(_current_dir, "static")
    os.makedirs(static_dir, exist_ok=True)

    handlers = [
        (r"/", IndexHandler),
        (r"/api/status", StatusHandler),
        (r"/api/samples", SamplesHandler),
        (r"/api/sample/([^/]+)", SampleDetailHandler),
        (r"/api/run", RunHandler),
        (r"/api/events/([^/]+)", EventsHandler),
        (r"/api/results/([^/]+)", ResultsHandler),
        (r"/api/report/([^/]+)", ReportHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": static_dir}),
    ]
    return tornado.web.Application(
        handlers,
        debug=False,
        autoreload=False,
    )


def start_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the web server."""
    app = make_app()
    server = tornado.httpserver.HTTPServer(app)
    server.listen(port, address=host)
    print(f"================================================================")
    print(f"  TOACD Compiler Research Platform — Web Interface")
    print(f"  Listening on: http://{host}:{port}")
    print(f"================================================================")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TOACD Web Server")
    parser.add_argument("--host", default="127.0.0.1", help="Binding host")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()
    start_server(host=args.host, port=args.port)
