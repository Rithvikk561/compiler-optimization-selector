"""
moo/bench/runner.py — Repeatable batch benchmark runner.

Delegates all measurement to the existing pipeline.evaluate_program() engine.
Does NOT create a new measurement implementation.

Features
--------
- Sequential execution (one program at a time) for timing reliability.
- Per-program isolation: each program runs in its own subprocess call.
- Structured status: each program produces a ProgramRecord.
- Run manifest: written at suite start, updated at completion.
- Environment/toolchain capture: clang/opt version strings.
- Resumability: already-written result files are skipped.
- Failure isolation: one program's pipeline error does not abort the suite.
- Deterministic ordering: follows the corpus entry list order exactly.

Output locations
----------------
Run outputs are written to:
  <run_dir>/run_manifest.json
  <run_dir>/results/<program_id>.json

These are SEPARATE from moo/reports/ to avoid interfering with the
selector_bridge cache.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
from typing import Optional

from .schema import (
    BENCH_SCHEMA_VERSION,
    CorpusEntry,
    RunManifest,
    ProgramRecord,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_git_commit() -> Optional[str]:
    """Return HEAD SHA of the current git repo, or None if not available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def _get_tool_version(tool_path: Optional[str]) -> Optional[str]:
    """Return first line of ``<tool> --version`` output, or None."""
    if not tool_path or not os.path.isfile(tool_path):
        return None
    try:
        r = subprocess.run(
            [tool_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        out = (r.stdout + r.stderr).strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def _get_platform_info() -> dict:
    """Capture basic platform information for reproducibility."""
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "processor": platform.processor() or "unknown",
    }


def _make_run_id(suite_name: str) -> str:
    """Generate a unique, deterministic-enough run ID."""
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    # Short hash of timestamp + suite name for uniqueness
    h = hashlib.sha256(f"{ts}:{suite_name}".encode()).hexdigest()[:8]
    return f"{ts}-{h}"


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """
    Batch runner that evaluates a list of CorpusEntry objects using the
    existing pipeline.evaluate_program() measurement engine.

    Parameters
    ----------
    run_dir      : directory where run outputs are written
    suite_name   : human label for this benchmark suite
    warmup_runs  : warm-up runs per candidate (default: from config)
    measure_runs : timed runs per candidate (default: from config)
    timeout_s    : per-run timeout in seconds (default: from config)
    actions      : strategy list to evaluate (default: from config.ACTIONS)
    resume       : if True, skip programs whose result file already exists

    Usage
    -----
    runner = BenchmarkRunner(run_dir="Codes/Benchmarks/runs/my_run")
    manifest = runner.run(corpus_entries)
    """

    def __init__(
        self,
        run_dir: str,
        suite_name: str = "week9_benchmark",
        warmup_runs: Optional[int] = None,
        measure_runs: Optional[int] = None,
        timeout_s: Optional[int] = None,
        actions: Optional[list[str]] = None,
        resume: bool = True,
    ):
        self.run_dir = os.path.abspath(run_dir)
        self.suite_name = suite_name
        self.resume = resume
        self._results_dir = os.path.join(self.run_dir, "results")

        # Import config lazily to avoid circular imports and allow mocking
        from ..config import (
            WARMUP_RUNS,
            MEASURE_RUNS,
            RUN_TIMEOUT_S,
            ACTIONS,
            CV_WARN_THRESHOLD,
            CLANG_PATH,
            OPT_PATH,
        )
        self.warmup_runs = warmup_runs if warmup_runs is not None else WARMUP_RUNS
        self.measure_runs = measure_runs if measure_runs is not None else MEASURE_RUNS
        self.timeout_s = timeout_s if timeout_s is not None else RUN_TIMEOUT_S
        self.actions = actions if actions is not None else ACTIONS
        self.cv_threshold = CV_WARN_THRESHOLD
        self._clang_path = CLANG_PATH
        self._opt_path = OPT_PATH

    def _result_path(self, program_id: str) -> str:
        return os.path.join(self._results_dir, f"{program_id}.json")

    def _manifest_path(self) -> str:
        return os.path.join(self.run_dir, "run_manifest.json")

    def _build_toolchain_info(self) -> Optional[dict]:
        """Capture toolchain version strings."""
        clang_ver = _get_tool_version(self._clang_path)
        opt_ver = _get_tool_version(self._opt_path)
        if clang_ver is None and opt_ver is None:
            return None
        return {
            "clang_path": self._clang_path,
            "clang_version": clang_ver,
            "opt_path": self._opt_path,
            "opt_version": opt_ver,
        }

    def _save_manifest(self, manifest: RunManifest) -> None:
        """Write (or overwrite) the run manifest JSON."""
        os.makedirs(self.run_dir, exist_ok=True)
        with open(self._manifest_path(), "w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2)

    def _save_record(self, record: ProgramRecord) -> None:
        """Write a per-program result JSON."""
        os.makedirs(self._results_dir, exist_ok=True)
        with open(self._result_path(record.program_id), "w", encoding="utf-8") as fh:
            json.dump(record.to_dict(), fh, indent=2)

    def _load_record(self, program_id: str) -> Optional[ProgramRecord]:
        """Load an existing per-program result (for resume support)."""
        path = self._result_path(program_id)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return ProgramRecord.from_dict(json.load(fh))
            except Exception:
                pass
        return None

    def _evaluate_one(
        self,
        run_id: str,
        entry: CorpusEntry,
    ) -> ProgramRecord:
        """
        Evaluate one C program using the existing pipeline.

        Returns a ProgramRecord.  Never raises — failures are recorded.
        """
        ts = datetime.datetime.now().isoformat(timespec="seconds")

        if entry.excluded:
            return ProgramRecord(
                schema_version=BENCH_SCHEMA_VERSION,
                run_id=run_id,
                program_id=entry.program_id,
                corpus_entry=entry.to_dict(),
                status="excluded",
                evaluated_at=ts,
                pipeline_error=f"Excluded from corpus: {entry.exclusion_reason}",
            )

        if not entry.source_path or not os.path.isfile(entry.source_path):
            return ProgramRecord(
                schema_version=BENCH_SCHEMA_VERSION,
                run_id=run_id,
                program_id=entry.program_id,
                corpus_entry=entry.to_dict(),
                status="pipeline_error",
                evaluated_at=ts,
                pipeline_error=f"Source file not found: {entry.source_path!r}",
            )

        # Import pipeline lazily (requires toolchain)
        try:
            from ..pipeline import evaluate_program
        except ImportError as exc:
            return ProgramRecord(
                schema_version=BENCH_SCHEMA_VERSION,
                run_id=run_id,
                program_id=entry.program_id,
                corpus_entry=entry.to_dict(),
                status="pipeline_error",
                evaluated_at=ts,
                pipeline_error=f"pipeline import failed: {exc}",
            )

        try:
            moo_result = evaluate_program(
                source_path=entry.source_path,
                source_name=entry.program_id,
                warmup_runs=self.warmup_runs,
                measure_runs=self.measure_runs,
                timeout_s=self.timeout_s,
                actions=self.actions,
            )
        except Exception as exc:
            return ProgramRecord(
                schema_version=BENCH_SCHEMA_VERSION,
                run_id=run_id,
                program_id=entry.program_id,
                corpus_entry=entry.to_dict(),
                status="pipeline_error",
                evaluated_at=ts,
                pipeline_error=f"evaluate_program raised: {exc}",
            )

        # Extract results
        if moo_result.pipeline_error:
            status = "pipeline_error"
        elif not moo_result.pareto_frontier:
            status = "no_valid_candidates"
        else:
            status = "ok"

        # Candidates serialized as list of dicts
        candidates_dicts = None
        if moo_result.candidates:
            candidates_dicts = [c.to_dict() for c in moo_result.candidates]

        return ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id=run_id,
            program_id=entry.program_id,
            corpus_entry=entry.to_dict(),
            status=status,
            evaluated_at=ts,
            pipeline_error=moo_result.pipeline_error,
            baseline=(
                moo_result.baseline.to_dict()
                if moo_result.baseline else None
            ),
            candidates=candidates_dicts,
            pareto_frontier=list(moo_result.pareto_frontier),
            pareto_dominated=list(moo_result.pareto_dominated),
            pareto_invalid=list(moo_result.pareto_invalid),
            objectives_used=list(moo_result.objectives_used),
            toolchain_notes=list(moo_result.toolchain_notes),
        )

    def run(
        self,
        entries: list[CorpusEntry],
        verbose: bool = True,
    ) -> RunManifest:
        """
        Run the benchmark suite across all active (non-excluded) corpus entries.

        Parameters
        ----------
        entries : list of CorpusEntry (typically from build_corpus_manifest)
        verbose : if True, print per-program status to stdout

        Returns
        -------
        Completed RunManifest.
        """
        run_id = _make_run_id(self.suite_name)
        os.makedirs(self.run_dir, exist_ok=True)
        os.makedirs(self._results_dir, exist_ok=True)

        active_entries = [e for e in entries if not e.excluded]
        program_ids = [e.program_id for e in active_entries]

        manifest = RunManifest(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id=run_id,
            created_at=datetime.datetime.now().isoformat(timespec="seconds"),
            suite_name=self.suite_name,
            program_ids=program_ids,
            strategies=list(self.actions),
            warmup_runs=self.warmup_runs,
            measure_runs=self.measure_runs,
            timeout_s=self.timeout_s,
            cv_threshold=self.cv_threshold,
            toolchain=self._build_toolchain_info(),
            platform=_get_platform_info(),
            baseline_convention=(
                "O0 correctness/normalization baseline: compiled with "
                "'clang -O0 <source> -o ref.exe'; all candidates normalized "
                "against this measurement.  See moo/bench/schema.py for the "
                "full three-convention O0 documentation."
            ),
            feature_convention=(
                "8 canonical IR features from moo.xai.CANONICAL_IR_FEATURE_NAMES: "
                "BasicBlocksCount, InstructionsCount, BranchCount, MemInstCount, "
                "MathInstCount, FloatInstCount, VectorInstCount, CallInstCount."
            ),
            n_programs_total=len(entries),
            status="running",
        )
        self._save_manifest(manifest)

        if verbose:
            print(f"[bench] Run {run_id}: evaluating {len(active_entries)} programs")
            print(f"[bench] Run dir: {self.run_dir}")

        n_ok = 0
        n_failed = 0

        for i, entry in enumerate(active_entries):
            pid = entry.program_id

            # Resumability: skip if result already exists
            if self.resume and os.path.isfile(self._result_path(pid)):
                if verbose:
                    print(f"  [{i+1}/{len(active_entries)}] SKIP (resume): {pid}")
                existing = self._load_record(pid)
                if existing and existing.status == "ok":
                    n_ok += 1
                else:
                    n_failed += 1
                continue

            if verbose:
                print(f"  [{i+1}/{len(active_entries)}] Evaluating: {pid} ...", end="", flush=True)

            record = self._evaluate_one(run_id, entry)
            self._save_record(record)

            if record.status == "ok":
                n_ok += 1
                if verbose:
                    n_frontier = len(record.pareto_frontier or [])
                    print(f" OK (frontier={n_frontier})")
            else:
                n_failed += 1
                if verbose:
                    print(f" {record.status.upper()}: {record.pipeline_error or ''}")

        # Finalize manifest
        manifest.n_programs_run = len(active_entries)
        manifest.n_programs_ok = n_ok
        manifest.n_programs_failed = n_failed
        manifest.completed_at = datetime.datetime.now().isoformat(timespec="seconds")
        manifest.git_commit = _get_git_commit()
        manifest.status = "completed"
        self._save_manifest(manifest)

        if verbose:
            print(f"[bench] Completed: {n_ok} ok, {n_failed} failed/errors")

        return manifest

    def load_records(self, run_id: Optional[str] = None) -> list[ProgramRecord]:
        """
        Load all per-program result files from the results directory.

        Parameters
        ----------
        run_id : if provided, only load records matching this run_id

        Returns
        -------
        List of ProgramRecord objects, in deterministic (filename-sorted) order.
        """
        records: list[ProgramRecord] = []
        if not os.path.isdir(self._results_dir):
            return records

        for fn in sorted(os.listdir(self._results_dir)):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(self._results_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                rec = ProgramRecord.from_dict(d)
                if run_id is None or rec.run_id == run_id:
                    records.append(rec)
            except Exception:
                pass

        return records
